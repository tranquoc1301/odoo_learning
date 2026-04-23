import logging

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

from ..constants import INVENTORY_BATCH_SIZE, SYNC_TYPE_INVENTORY, STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED

_logger = logging.getLogger(__name__)

_BATCH_SIZE = INVENTORY_BATCH_SIZE


class ShopifyConfigInventory(models.Model):
    """Inventory sync logic for shopify.config."""

    _inherit = "shopify.config"

    def sync_inventory(self):
        """Pull inventory levels from Shopify and apply them to stock.quant records."""
        self.ensure_one()

        # Only process variants already mapped to a Shopify inventory item
        variants = self.env["product.product"].search(
            [
                ("shopify_config_id", "=", self.id),
                ("shopify_inventory_item_id", "!=", False),
                ("shopify_inventory_item_id", "!=", ""),
                ("active", "=", True),
            ]
        )

        if not variants:
            self.env["sync.log"].create_from_config(
                self,
                sync_type=SYNC_TYPE_INVENTORY,
                status=STATUS_PARTIAL,
                message=_("No mapped variants found. Run a Product sync first."),
            )
            return {"created": 0, "updated": 0, "errors": 1}

        location = self.warehouse_id.lot_stock_id
        if not location:
            self.env["sync.log"].create_from_config(
                self,
                sync_type=SYNC_TYPE_INVENTORY,
                status=STATUS_FAILED,
                message=_("Warehouse '%s' has no stock location configured.")
                % self.warehouse_id.name,
            )
            return {"created": 0, "updated": 0, "errors": 1}

        item_map = {v.shopify_inventory_item_id: v for v in variants}
        item_ids = list(item_map.keys())

        updated = 0
        errors = 0

        for i in range(0, len(item_ids), _BATCH_SIZE):
            batch_ids = item_ids[i: i + _BATCH_SIZE]
            try:
                data = self._get(
                    "inventory_levels.json",
                    params={"inventory_item_ids": ",".join(batch_ids)},
                )
            except UserError:
                errors += len(batch_ids)
                continue

            for level in data.get("inventory_levels", []):
                inv_item_id = str(level.get("inventory_item_id") or "")
                available = level.get("available")

                # Skip levels where Shopify has not tracked a quantity
                if available is None:
                    continue

                product = item_map.get(inv_item_id)
                if not product:
                    continue

                try:
                    changed = self._apply_qty(product, location, float(available))
                    if changed:
                        updated += 1
                except Exception as exc:
                    _logger.exception(
                        "Failed to update inventory for product %s: %s",
                        product.display_name,
                        exc,
                    )
                    errors += 1

        status = STATUS_SUCCESS if not errors else (STATUS_PARTIAL if updated else STATUS_FAILED)
        self.env["sync.log"].create_from_config(
            self,
            sync_type=SYNC_TYPE_INVENTORY,
            status=status,
            message=_(
                "Inventory sync completed. Updated: %(updated)s, Errors: %(errors)s"
            )
            % {"updated": updated, "errors": errors},
        )
        return {"created": 0, "updated": updated, "errors": errors}

    def _apply_qty(self, product, location, qty):
        StockQuant = self.env["stock.quant"]
        quant = StockQuant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
            ],
            limit=1,
        )

        if quant:
            # Compare with actual on-hand quantity, not inventory_quantity
            if float_compare(quant.quantity, qty, precision_digits=2) == 0:
                return False  # qty unchanged → skip, no stock move needed

            quant.inventory_quantity = qty
            quant.action_apply_inventory()
        else:
            StockQuant.create(
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "inventory_quantity": qty,
                }
            ).action_apply_inventory()

        return True
