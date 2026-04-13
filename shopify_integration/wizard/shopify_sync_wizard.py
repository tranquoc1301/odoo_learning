from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ShopifySyncWizard(models.TransientModel):
    _name = "shopify.sync.wizard"
    _description = "Shopify Manual Sync Wizard"

    config_id = fields.Many2one(
        "shopify.config",
        string="Shopify Store",
        required=True,
        domain="[('active', '=', True)]",
    )
    sync_type = fields.Selection(
        [
            ("products", "Products"),
            ("orders", "Orders"),
            ("inventory", "Inventory"),
            ("all", "All (Products + Orders + Inventory)"),
        ],
        string="Sync Type",
        required=True,
        default="all",
    )
    date_from = fields.Datetime(
        string="Date From",
        help="Only applicable for Order sync. Leave empty to use last sync date.",
    )
    date_to = fields.Datetime(
        string="Date To",
        help="Only applicable for Order sync. Leave empty to sync until now.",
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_("Date From must be earlier than Date To."))

    def action_sync(self):
        self.ensure_one()
        config = self.config_id
        result = {}

        if self.sync_type == "products":
            result["products"] = config.sync_products()
        elif self.sync_type == "orders":
            result["orders"] = config.sync_orders(
                date_from=self.date_from,
                date_to=self.date_to,
            )
        elif self.sync_type == "inventory":
            result["inventory"] = config.sync_inventory()
        else:
            result = config.sync_all()

        lines = []
        for key, res in result.items():
            if isinstance(res, dict):
                lines.append(
                    "%(type)s — Created: %(created)s, Updated: %(updated)s, Errors: %(errors)s"
                    % {
                        "type": key.capitalize(),
                        "created": res.get("created", 0),
                        "updated": res.get("updated", 0),
                        "errors": res.get("errors", 0),
                    }
                )

        message = "\n".join(lines) if lines else _("Sync completed.")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sync Completed"),
                "message": message,
                "type": "success",
                "sticky": True,
            },
        }