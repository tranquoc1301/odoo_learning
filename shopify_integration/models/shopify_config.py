import logging
import re
import time
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from ..constants import HTTP_RATE_LIMITED, SHOPIFY_API_VERSION, MAX_RATE_LIMIT_RETRIES

_logger = logging.getLogger(__name__)


class ShopifyConfig(models.Model):
    """
    Core configuration model for a Shopify store connection.
    Responsibilities:
      - Store credentials and warehouse mapping
      - Provide shared HTTP request helpers (_make_api_request, _get_all_pages)
      - Write sync logs (_create_sync_log)
      - Expose cron entry points and sync_all orchestrator
    """

    _name = "shopify.config"
    _description = "Shopify Configuration"
    _rec_name = "name"

    # ── Fields ───────────────────────────────────────────────────────────────

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

    # ── Constraints & URL helpers ─────────────────────────────────────────────

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

    # ── Sync log ──────────────────────────────────────────────────────────────

    def _create_sync_log(
            self,
            sync_type,
            status,
            message,
            shopify_id=None,
            external_ref=None,
    ):
        self.ensure_one()
        return self.env["sync.log"].sudo().create({
            "config_id": self.id,
            "sync_type": sync_type,
            "status": status,
            "message": message,
            "shopify_id": shopify_id,
            "external_ref": external_ref,
        })

    def _make_api_request(
            self,
            endpoint_or_url,
            method="GET",
            params=None,
            payload=None,
            sync_type=None,
            timeout=30,
            return_response=False,
    ):
        """
        Send a request to the Shopify API.
        - Retries automatically on HTTP 429 (rate limit) up to MAX_RATE_LIMIT_RETRIES times.
        - Raises UserError and writes a failed log on any unrecoverable error.
        - Returns the raw Response object when return_response=True,
          otherwise returns the parsed JSON dict.
        """
        self.ensure_one()

        url = (
            endpoint_or_url
            if endpoint_or_url.startswith("http")
            else f"{self._get_base_url()}/{endpoint_or_url.lstrip('/')}"
        )

        try:
            for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    params=params,
                    json=payload,
                    timeout=timeout,
                )

                if response.status_code == HTTP_RATE_LIMITED:
                    if attempt > MAX_RATE_LIMIT_RETRIES:
                        response.raise_for_status()

                    retry_after = float(response.headers.get("Retry-After", 1))
                    _logger.warning(
                        "Shopify rate limited (attempt %s/%s). Sleeping %.1f s.",
                        attempt, MAX_RATE_LIMIT_RETRIES, retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response if return_response else response.json()

        except Exception as exc:
            message = _("Shopify API error: %s") % exc
            _logger.exception(message)
            self._create_sync_log(sync_type=sync_type, status="failed", message=message)
            raise UserError(message) from exc

    def _extract_next_url(self, link_header):
        """Parse the Link header and return the URL for rel="next", or False."""
        if not link_header:
            return False
        matches = re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', link_header)
        for url, rel in matches:
            if rel == "next":
                return url
        return False

    def _get_all_pages(self, endpoint, params=None, key=None, sync_type="product"):
        """
        Fetch all pages from a paginated Shopify endpoint.

        Shopify uses cursor-based pagination via the Link response header:
          Link: <https://...?page_info=XYZ>; rel="next"

        Query params are sent only on the first request; subsequent page URLs
        already contain the cursor so current_params is set to None after page 1.
        """
        self.ensure_one()
        results = []
        next_url = f"{self._get_base_url()}/{endpoint.lstrip('/')}"
        current_params = params or {}

        while next_url:
            response = self._make_api_request(
                next_url,
                method="GET",
                params=current_params,
                sync_type=sync_type,
                return_response=True,
            )
            payload = response.json()
            if key:
                results.extend(payload.get(key, []))
            else:
                results.append(payload)

            next_url = self._extract_next_url(response.headers.get("Link"))
            current_params = None  # cursor is embedded in next_url from page 2 onward

        return results

    # ── Action: test connection ───────────────────────────────────────────────

    def action_test_connection(self):
        self.ensure_one()
        data = self._make_api_request("shop.json", sync_type="product")
        shop_name = data.get("shop", {}).get("name") or self.shop_url

        self._create_sync_log(
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

    # ── Orchestrator ──────────────────────────────────────────────────────────

    def sync_all(self):
        """
        Run all three sync operations in sequence: products -> orders -> inventory.
        A failure in one step does not prevent the others from running.
        """
        self.ensure_one()
        result = {"products": {}, "orders": {}, "inventory": {}}

        for key, method in (
                ("products", self.sync_products),
                ("orders", self.sync_orders),
                ("inventory", self.sync_inventory),
        ):
            try:
                result[key] = method()
            except (UserError, ValidationError) as exc:
                result[key] = {
                    "created": 0,
                    "updated": 0,
                    "errors": 1,
                    "message": str(exc),
                }

        return result

    # ── Cron helpers ──────────────────────────────────────────────────────────

    def _run_cron_sync(self, method_name):
        """
        Execute method_name on every active config record.
        Exceptions are caught per record so one failure does not block others.
        """
        for config in self.search([("active", "=", True)]):
            try:
                getattr(config, method_name)()
            except Exception:
                _logger.exception(
                    "Cron %s failed for config %s", method_name, config.display_name
                )
        return True

    def cron_sync_products(self):
        return self._run_cron_sync("sync_products")

    def cron_sync_orders(self):
        return self._run_cron_sync("sync_orders")

    def cron_sync_inventory(self):
        return self._run_cron_sync("sync_inventory")
