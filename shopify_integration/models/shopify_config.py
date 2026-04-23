from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .shopify_client import ShopifyClient

from ..constants import (
    SYNC_TYPE_CONNECTION,
    STATUS_SUCCESS,
    STATUS_PARTIAL,
    STATUS_FAILED,
)


class ShopifyConfig(models.Model):
    _name = "shopify.config"
    _description = "Shopify Configuration"
    _inherit = "shopify.client"
    _rec_name = "name"

    name = fields.Char(string="Name", required=True)
    shop_url = fields.Char(string="Shop URL", required=True)
    api_access_token = fields.Char(
        string="Access Token",
        required=True,
        password=True,
    )
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse", required=True)
    last_sync = fields.Datetime(string="Last Successfully Sync", copy=False, readonly=True)
    active = fields.Boolean(default=True)
    api_version = fields.Char(string="API Version", copy=False, readonly=True)
    sync_log_ids = fields.One2many("sync.log", "config_id", string="Sync Logs")

    @api.constrains("shop_url")
    def _check_shop_url(self):
        for record in self:
            hostname = record._normalize_shop_url(record.shop_url)
            if not hostname or "." not in hostname:
                raise ValidationError(_("Invalid shop URL."))

    def action_test_connection(self):
        self.ensure_one()
        try:
            shop_name = self._test_connection()
            self.env["sync.log"].create_from_config(
                self, sync_type=SYNC_TYPE_CONNECTION, status=STATUS_SUCCESS,
                message=_("Connected: %s") % shop_name,
            )
        except Exception as exc:
            self.env["sync.log"].create_from_config(
                self, sync_type=SYNC_TYPE_CONNECTION, status=STATUS_FAILED,
                message=_("Failed: %s") % exc,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {"title": _("Error"), "message": str(exc), "type": "danger", "sticky": True},
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Success"), "message": _("Connected: %s") % shop_name, "type": "success"},
        }
