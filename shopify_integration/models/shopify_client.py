import logging
import re
import time

import requests

from odoo import _, models
from odoo.exceptions import UserError

from ..constants import (
    HTTP_RATE_LIMITED,
    HTTP_OK,
    HTTP_CREATED,
    HTTP_BAD_REQUEST,
    HTTP_UNAUTHORIZED,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_INTERNAL_SERVER_ERROR,
    MAX_RATE_LIMIT_RETRIES,
    API_REQUEST_TIMEOUT,
    DEFAULT_API_VERSION,
)

_logger = logging.getLogger(__name__)

_HTTP_ERRORS = {
    HTTP_BAD_REQUEST: "Bad request",
    HTTP_UNAUTHORIZED: "Invalid or expired access token",
    HTTP_FORBIDDEN: "Access forbidden",
    HTTP_NOT_FOUND: "Resource not found",
    HTTP_INTERNAL_SERVER_ERROR: "Shopify server error",
}


class ShopifyClient(models.AbstractModel):
    """Shopify HTTP Client — all API logic in one place."""

    _name = "shopify.client"
    _description = "Shopify HTTP Client"

    # ── API Version ───────────────────────────────────────────────────────────────

    def _get_api_version(self):
        """Get latest API version from Shopify, cached in api_version field."""
        self.ensure_one()

        # Return cached version if already fetched
        if self.api_version:
            return self.api_version

        # Fetch latest version from Shopify
        hostname = self._normalize_shop_url(self.shop_url)
        url = f"https://{hostname}/admin/api/{DEFAULT_API_VERSION}/api_versions.json"

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=API_REQUEST_TIMEOUT)
            if response.status_code == 200:
                versions = response.json().get("api_versions", [])
                version = versions[0] if versions else DEFAULT_API_VERSION
            else:
                version = DEFAULT_API_VERSION
        except Exception:
            version = DEFAULT_API_VERSION

        # Cache in DB for future calls
        self.write({"api_version": version})
        return version

    def _normalize_shop_url(self, value):
        """Extract hostname from URL or bare domain."""
        value = (value or "").strip().lower()
        if not value:
            return ""
        for prefix in ("https://", "http://"):
            if value.startswith(prefix):
                value = value[len(prefix):]
                break
        return value.rstrip("/")

    def _get_base_url(self):
        """Build API base URL with dynamic version."""
        self.ensure_one()
        return f"https://{self._normalize_shop_url(self.shop_url)}/admin/api/{self._get_api_version()}"

    def _get_headers(self):
        """Build auth headers."""
        self.ensure_one()
        return {
            "X-Shopify-Access-Token": self.api_access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _find_by_shopify_id(self, model_name, field_name, value):
        """Find record by Shopify ID in same config."""
        self.ensure_one()
        return self.env[model_name].search([
            (field_name, "=", value),
            ("shopify_config_id", "=", self.id),
        ], limit=1)

    # ── HTTP Methods ───────────────────────────────────────────────────────

    def _get(self, endpoint, params=None):
        return self._request(endpoint, params=params)

    def _get_all(self, endpoint, params=None, key=None):
        """Fetch all pages from paginated endpoint."""
        self.ensure_one()
        results = []
        url = f"{self._get_base_url()}/{endpoint.lstrip('/')}"
        current_params = params or {}

        while url:
            response = self._request(url, params=current_params, raw=True)
            data = response.json()
            results.extend(data.get(key, []) if key else [data])
            url = self._next_page_url(response.headers.get("Link"))
            current_params = None

        return results

    def _test_connection(self):
        """Test connection, return shop name."""
        data = self._get("shop.json")
        return data.get("shop", {}).get("name", "")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _request(self, endpoint_or_url, method="GET", params=None, payload=None, raw=False):
        self.ensure_one()

        url = (
            endpoint_or_url
            if endpoint_or_url.startswith("http")
            else f"{self._get_base_url()}/{endpoint_or_url.lstrip('/')}"
        )

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    params=params,
                    json=payload,
                    timeout=API_REQUEST_TIMEOUT,
                )
            except requests.exceptions.RequestException as exc:
                raise UserError(_("Shopify connection error: %s") % exc) from exc

            if response.status_code not in (HTTP_RATE_LIMITED,):
                break

            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise UserError(_("Shopify rate limit exceeded after %s retries.") % MAX_RATE_LIMIT_RETRIES)

            wait = float(response.headers.get("Retry-After", 1))
            _logger.warning("Rate limited — retry %s/%s in %.1fs.", attempt + 1, MAX_RATE_LIMIT_RETRIES, wait)
            time.sleep(wait)

        if response.status_code in (HTTP_OK, HTTP_CREATED):
            return response if raw else response.json()

        error = _HTTP_ERRORS.get(response.status_code, "Unknown error")
        raise UserError(_("Shopify API error (%s): %s") % (response.status_code, error))

    @staticmethod
    def _next_page_url(link_header):
        """Parse Link header, return next page URL or None."""
        if not link_header:
            return None
        for url, rel in re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', link_header):
            if rel == "next":
                return url
        return None

    # ── Cron Entry Points ────────────────────────────────────────────────

    def _cron_for_all_active(self, method_name):
        """Run method on all active configs."""
        for config in self.search([("active", "=", True)]):
            try:
                getattr(config, method_name)()
            except Exception:
                _logger.exception("Cron %s failed for %s", method_name, config.display_name)
        return True

    def cron_sync_products(self):
        return self._cron_for_all_active("sync_products")

    def cron_sync_orders(self):
        return self._cron_for_all_active("sync_orders")

    def cron_sync_inventory(self):
        return self._cron_for_all_active("sync_inventory")
