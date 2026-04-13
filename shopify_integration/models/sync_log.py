from odoo import fields, models


class SyncLog(models.Model):
    _name = "sync.log"
    _description = "Shopify Sync Log"
    _order = "run_at desc, id desc"

    config_id = fields.Many2one(
        "shopify.config",
        string="Store",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sync_type = fields.Selection(
        [
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
