from odoo import fields, models


class SyncLog(models.Model):
    _name = "sync.log"
    _description = "Shopify Sync Log"
    _order = "run_at desc, id desc"

    config_id = fields.Many2one(
        "shopify.config",
        string="Store",
        required=True,
        ondelete="restrict",
        index=True,
    )
    sync_type = fields.Selection(
        [
            ("connection", "Connection"),
            ("product", "Product"),
            ("order", "Order"),
            ("inventory", "Inventory"),
        ],
        string="Sync Type",
        required=True,
        index=True,
    )
    status = fields.Selection(
        [
            ("success", "Success"),
            ("partial", "Partial"),
            ("failed", "Failed"),
        ],
        string="Status",
        required=True,
        index=True,
    )
    message = fields.Text(string="Message", required=True)
    shopify_id = fields.Char(
        string="Shopify ID",
        index=True,
    )
    external_ref = fields.Char(
        string="External Reference",
        index=True,
    )
    run_at = fields.Datetime(
        string="Run At",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )

    def create_from_config(
        self, config, sync_type, status, message, shopify_id=None, external_ref=None
    ):
        """Create a sync log entry for the given config."""
        return self.sudo().create(
            {
                "config_id": config.id,
                "sync_type": sync_type,
                "status": status,
                "message": message,
                "shopify_id": shopify_id,
                "external_ref": external_ref,
            }
        )
