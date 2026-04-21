import logging
import re
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from ..shopify_client import ShopifyClient
from ..constants import SHOPIFY_API_VERSION

_logger = logging.getLogger(__name__)


class ShopifyConfig(models.Model):
    """Shopify store configuration."""

    _name = "shopify.config"
    _description = "Shopify Configuration"
    _rec_name = "name"

    name = fields.Char(string="Name", required=True)
    shop_url = fields.Char(
        string="Shop URL",
        required=True,
        help="Example: your-store.myshopify.com",
    )
    api_access_token = fields.Char(string="Access Token", required=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
    )
    last_sync = fields.Datetime(
        string="Last Successful Sync",
        copy=False,
        readonly=True,
    )
    active = fields.Boolean(default=True)
    sync_log_ids = fields.One2many(
        "sync.log",
        "config_id",
        string="Sync Logs",
    )

    @api.constrains("shop_url")
    def _check_shop_url(self):
        for record in self:
            hostname = record._normalize_shop_url(record.shop_url)
            if not hostname or "." not in hostname:
                raise ValidationError(_("Shop URL is not valid."))

    def _normalize_shop_url(self, value):
        """Return a clean hostname string from a raw URL or bare domain input."""
        value = (value or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"
        parsed = urlparse(value)
        return (parsed.netloc or parsed.path or "").strip().strip("/")

    def _get_base_url(self):
        self.ensure_one()
        hostname = self._normalize_shop_url(self.shop_url)
        return f"https://{hostname}/admin/api/{SHOPIFY_API_VERSION}"

    def _get_headers(self):
        self.ensure_one()
        return {
            "X-Shopify-Access-Token": self.api_access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def action_test_connection(self):
        """Test connection to Shopify store."""
        self.ensure_one()
        client = ShopifyClient(self)
        try:
            shop_name = client.test_connection()
            self.env["sync.log"].create_from_config(
                self,
                sync_type="product",
                status="success",
                message=_("Connection successful: %s") % shop_name,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success"),
                    "message": _("Connected: %s") % shop_name,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as exc:
            self.env["sync.log"].create_from_config(
                self,
                sync_type="product",
                status="failed",
                message=_("Connection failed: %s") % exc,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": str(exc),
                    "type": "danger",
                    "sticky": True,
                },
            }
