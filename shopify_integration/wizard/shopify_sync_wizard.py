from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..constants import (
    SYNC_TYPE_PRODUCT,
    SYNC_TYPE_ORDER,
    SYNC_TYPE_INVENTORY,
)
from ..sync_summary_template import build_sync_summary_html


class ShopifySyncWizard(models.TransientModel):
    _name = "shopify.sync.wizard"
    _description = "Shopify Manual Sync Wizard"

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        string="State",
        default="draft",
        readonly=True,
    )

    config_id = fields.Many2one(
        "shopify.config",
        string="Shopify Store",
        required=True,
        domain="[('active', '=', True)]",
    )
    sync_type = fields.Selection(
        [
            (SYNC_TYPE_PRODUCT, "Products"),
            (SYNC_TYPE_ORDER, "Orders"),
            (SYNC_TYPE_INVENTORY, "Inventory"),
            ("all", "All"),
        ],
        string="Sync Type",
        required=True,
        default="all",
    )
    date_from = fields.Datetime(
        string="Date From",
        help="Only applicable for order sync. Leave empty to use last sync date.",
    )
    date_to = fields.Datetime(
        string="Date To",
        help="Only applicable for order sync. Leave empty to sync until now.",
    )

    total_created = fields.Integer(string="Created", readonly=True)
    total_updated = fields.Integer(string="Updated", readonly=True)
    total_errors = fields.Integer(string="Errors", readonly=True)
    summary_html = fields.Html(string="Summary", readonly=True, sanitize=False)

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if (
                wizard.date_from
                and wizard.date_to
                and wizard.date_from > wizard.date_to
            ):
                raise UserError(_("Date From must be earlier than Date To."))

    def _get_sync_label(self, key):
        labels = {
            "products": _("Products"),
            "orders": _("Orders"),
            "inventory": _("Inventory"),
        }
        return labels.get(key, key.capitalize())

    def _build_summary(self, result_map):
        """Build an HTML table summary and return write-ready vals dict."""
        html = build_sync_summary_html(result_map)
        wrapped_html = f"<div class='o_field_html'><table class='table table-sm table-bordered table-hover mb-0'>{html}</table></div>"

        total_created = sum(
            int(r.get("created", 0) or 0)
            for r in result_map.values()
            if isinstance(r, dict)
        )
        total_updated = sum(
            int(r.get("updated", 0) or 0)
            for r in result_map.values()
            if isinstance(r, dict)
        )
        total_errors = sum(
            int(r.get("errors", 0) or 0)
            for r in result_map.values()
            if isinstance(r, dict)
        )

        return {
            "total_created": total_created,
            "total_updated": total_updated,
            "total_errors": total_errors,
            "summary_html": wrapped_html,
        }

    def _run_selected_sync(self):
        self.ensure_one()
        config = self.config_id

        if self.sync_type == SYNC_TYPE_PRODUCT:
            return {
                SYNC_TYPE_PRODUCT: config.sync_products(),
            }

        if self.sync_type == SYNC_TYPE_ORDER:
            return {
                SYNC_TYPE_ORDER: config.sync_orders(
                    date_from=self.date_from,
                    date_to=self.date_to,
                ),
            }

        if self.sync_type == SYNC_TYPE_INVENTORY:
            return {
                SYNC_TYPE_INVENTORY: config.sync_inventory(),
            }

        return {
            SYNC_TYPE_PRODUCT: config.sync_products(),
            SYNC_TYPE_INVENTORY: config.sync_inventory(),
            SYNC_TYPE_ORDER: config.sync_orders(
                date_from=self.date_from,
                date_to=self.date_to,
            ),
        }

    def action_sync(self):
        self.ensure_one()

        result_map = self._run_selected_sync()
        summary_vals = self._build_summary(result_map)

        self.write(
            {
                "state": "done",
                **summary_vals,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Summary"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_reset(self):
        self.ensure_one()
        self.write(
            {
                "state": "draft",
                "total_created": 0,
                "total_updated": 0,
                "total_errors": 0,
                "summary_html": False,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Manual Sync"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}
