from odoo import fields, models

from ..constants import (
    SYNC_TYPE_CONNECTION,
    SYNC_TYPE_PRODUCT,
    SYNC_TYPE_ORDER,
    SYNC_TYPE_INVENTORY,
    STATUS_SUCCESS,
    STATUS_PARTIAL,
    STATUS_FAILED,
)


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
            (SYNC_TYPE_CONNECTION, "Connection"),
            (SYNC_TYPE_PRODUCT, "Product"),
            (SYNC_TYPE_ORDER, "Order"),
            (SYNC_TYPE_INVENTORY, "Inventory"),
        ],
        string="Sync Type",
        required=True,
        index=True,
    )
    status = fields.Selection(
        [
            (STATUS_SUCCESS, "Success"),
            (STATUS_PARTIAL, "Partial"),
            (STATUS_FAILED, "Failed"),
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
        return self.create(
            {
                "config_id": config.id,
                "sync_type": sync_type,
                "status": status,
                "message": message,
                "shopify_id": shopify_id,
                "external_ref": external_ref,
            }
        )
