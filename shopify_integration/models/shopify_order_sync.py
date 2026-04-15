import logging
from datetime import datetime

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class ShopifyConfigOrder(models.Model):
    """Order sync logic for shopify.config."""

    _inherit = "shopify.config"

    # ── Entry point ───────────────────────────────────────────────────────────

    def sync_orders(self, date_from=None, date_to=None):
        """Import Shopify orders into sale.order records."""
        self.ensure_one()

        params = {
            "limit": 50,
            "status": "any",
        }

        if date_from:
            params["created_at_min"] = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif self.last_sync:
            params["created_at_min"] = self.last_sync.strftime("%Y-%m-%dT%H:%M:%SZ")

        if date_to:
            params["created_at_max"] = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")

        orders = self._get_all_pages(
            "orders.json",
            params=params,
            key="orders",
            sync_type="order",
        )

        created = 0
        skipped = 0
        partial = 0

        for shopify_order in orders:
            result = self._sync_single_order(shopify_order)
            if result == "created":
                created += 1
            elif result == "skipped":
                skipped += 1
            else:
                partial += 1

        self.last_sync = fields.Datetime.now()

        self._create_sync_log(
            sync_type="order",
            status="success" if not partial else "partial",
            message=_(
                "Orders synced. Created: %(created)s, Skipped: %(skipped)s, Partial: %(partial)s"
            ) % {"created": created, "skipped": skipped, "partial": partial},
        )
        return {"created": created, "updated": 0, "errors": partial}

    # ── Single order ──────────────────────────────────────────────────────────

    def _sync_single_order(self, shopify_order):
        """Create a confirmed sale.order from a Shopify order dict."""
        self.ensure_one()
        SaleOrder = self.env["sale.order"]

        shopify_order_id = str(shopify_order["id"])

        # Idempotency check -- skip if the order was already imported
        existing_order = SaleOrder.search(
            [
                ("shopify_order_id", "=", shopify_order_id),
                ("shopify_config_id", "=", self.id),
            ],
            limit=1,
        )
        if existing_order:
            return "skipped"

        partner = self._get_or_create_customer(shopify_order)
        shipping_partner = self._get_or_create_delivery_partner(partner, shopify_order)

        # Flush and invalidate to avoid stale cache affecting the subsequent create()
        self.env.cr.flush()
        partner.invalidate_recordset()

        lines = []
        for item in shopify_order.get("line_items", []):
            sku = item.get("sku") or ""
            variant_id = str(item.get("variant_id") or "")

            product = self.env["product.product"].search(
                [
                    ("shopify_config_id", "=", self.id),
                    "|",
                    ("shopify_variant_id", "=", variant_id),
                    ("default_code", "=", sku),
                ],
                limit=1,
            )

            if not product:
                self._create_sync_log(
                    sync_type="order",
                    status="partial",
                    message=_("Missing SKU while importing order: %s") % (sku or "-"),
                    shopify_id=str(item.get("id") or ""),
                    external_ref=shopify_order.get("name"),
                )
                continue

            lines.append((0, 0, {
                "product_id": product.id,
                "name": item.get("title") or product.display_name,
                "product_uom_qty": item.get("quantity", 1),
                "price_unit": float(item.get("price") or 0.0),
                "product_uom_id": product.uom_id.id,
            }))

        if not lines:
            self._create_sync_log(
                sync_type="order",
                status="failed",
                message=_(
                    "Order %s skipped because no valid order lines were found."
                ) % (shopify_order.get("name") or shopify_order_id),
                shopify_id=shopify_order_id,
            )
            return "partial"

        order = SaleOrder.create({
            "partner_id": partner.id,
            "partner_invoice_id": partner.id,
            "partner_shipping_id": shipping_partner.id,
            "warehouse_id": self.warehouse_id.id,
            "shopify_order_id": shopify_order_id,
            "shopify_config_id": self.id,
            "client_order_ref": shopify_order.get("name") or f"shopify_{shopify_order_id}",
            "date_order": self._parse_shopify_datetime(shopify_order.get("created_at")),
            "order_line": lines,
        })

        # Re-write the shipping partner after create() to ensure computed fields
        order.write({"partner_shipping_id": shipping_partner.id})

        order.action_confirm()
        return "created"

    # ── Datetime helper ───────────────────────────────────────────────────────

    def _parse_shopify_datetime(self, value):
        """Convert a Shopify ISO-8601 timestamp (with timezone) to a naive UTC datetime."""
        if not value:
            return fields.Datetime.now()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return fields.Datetime.now()

    # ── Partner helpers ───────────────────────────────────────────────────────

    def _get_or_create_customer(self, shopify_order):
        """Return the billing res.partner for this order, creating one if needed."""
        self.ensure_one()
        Partner = self.env["res.partner"]

        customer_data = shopify_order.get("customer") or {}
        email = customer_data.get("email") or shopify_order.get("email") or ""

        if not email:
            return self.env.ref("base.public_partner")

        partner = Partner.search(
            [("email", "=", email), ("type", "=", "contact")],
            limit=1,
        )
        if partner:
            return partner

        full_name = " ".join(
            filter(
                None,
                [
                    customer_data.get("first_name"),
                    customer_data.get("last_name"),
                ],
            )
        ) or email

        return Partner.create({
            "name": full_name,
            "email": email,
            "type": "contact",
        })

    def _get_or_create_delivery_partner(self, partner, shopify_order):
        """Return the delivery res.partner (child of *partner*) for this order."""

        self.ensure_one()
        Partner = self.env["res.partner"]
        shipping = shopify_order.get("shipping_address") or {}

        if not shipping:
            return partner

        country_code = (shipping.get("country_code") or "").upper()
        country = (
            self.env["res.country"].search([("code", "=", country_code)], limit=1)
            if country_code
            else self.env["res.country"]
        )

        province_code = (shipping.get("province_code") or "").upper()
        state = (
            self.env["res.country.state"].search(
                [
                    ("code", "=", province_code),
                    ("country_id", "=", country.id if country else False),
                ],
                limit=1,
            )
            if province_code and country
            else self.env["res.country.state"]
        )

        vals = {
            "parent_id": partner.id,
            "type": "delivery",
            "name": _("Delivery Address"),
            "street": shipping.get("address1") or "",
            "street2": shipping.get("address2") or "",
            "city": shipping.get("city") or "",
            "zip": shipping.get("zip") or "",
            "phone": shipping.get("phone") or "",
            "country_id": country.id if country else False,
            "state_id": state.id if state else False,
        }

        # Deduplicate: reuse an existing delivery address with the same street and zip
        if vals["street"] or vals["zip"]:
            delivery = Partner.search(
                [
                    ("parent_id", "=", partner.id),
                    ("type", "=", "delivery"),
                    ("street", "=", vals["street"]),
                    ("zip", "=", vals["zip"]),
                ],
                limit=1,
            )
            if delivery:
                delivery.write(vals)
                return delivery

        return Partner.create(vals)
