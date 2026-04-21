import logging
import re
import time

import requests

from odoo import _
from odoo.exceptions import UserError
from .constants import (
    HTTP_RATE_LIMITED,
    MAX_RATE_LIMIT_RETRIES,
    API_REQUEST_TIMEOUT,
)

_logger = logging.getLogger(__name__)


class ShopifyClient:
    """Handles all communication with Shopify API."""

    def __init__(self, config):
        self.config = config
        self._base_url = config._get_base_url()
        self._headers = config._get_headers()

    def request(
            self,
            endpoint_or_url,
            method="GET",
            params=None,
            payload=None,
            timeout=None,
            return_response=False,
    ):
        """Send a request to the Shopify API with automatic retry on rate limit."""
        if timeout is None:
            timeout = API_REQUEST_TIMEOUT

        url = (
            endpoint_or_url
            if endpoint_or_url.startswith("http")
            else f"{self._base_url}/{endpoint_or_url.lstrip('/')}"
        )

        attempt = 0
        while True:
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    params=params,
                    json=payload,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as exc:
                _logger.exception("Shopify request error: %s", exc)
                raise UserError(_("Shopify API error: %s") % exc) from exc

            if response.status_code != HTTP_RATE_LIMITED:
                try:
                    response.raise_for_status()
                except Exception as exc:
                    _logger.exception("Shopify API error: %s", exc)
                    raise UserError(_("Shopify API error: %s") % exc) from exc
                return response if return_response else response.json()

            attempt += 1
            if attempt > MAX_RATE_LIMIT_RETRIES:
                _logger.error("Shopify rate limit exceeded after %s retries.", MAX_RATE_LIMIT_RETRIES)
                raise UserError(_("Shopify rate limit exceeded after %s retries.") % MAX_RATE_LIMIT_RETRIES)

            retry_after = float(response.headers.get("Retry-After", 1))
            _logger.warning(
                "Shopify rate limited (attempt %s/%s). Sleeping %.1f s.",
                attempt,
                MAX_RATE_LIMIT_RETRIES,
                retry_after,
            )
            time.sleep(retry_after)

    def get(self, endpoint, params=None):
        return self.request(endpoint, method="GET", params=params)

    def post(self, endpoint, payload=None):
        return self.request(endpoint, method="POST", payload=payload)

    def put(self, endpoint, payload=None):
        return self.request(endpoint, method="PUT", payload=payload)

    def delete(self, endpoint):
        return self.request(endpoint, method="DELETE")

    @staticmethod
    def _extract_next_url(link_header):
        """Parse the Link header and return the URL for rel="next", or False."""
        if not link_header:
            return False
        matches = re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', link_header)
        for url, rel in matches:
            if rel == "next":
                return url
        return False

    def get_all(self, endpoint, params=None, key=None):
        """Fetch all pages from a paginated Shopify endpoint."""
        results = []
        next_url = f"{self._base_url}/{endpoint.lstrip('/')}"
        current_params = params or {}

        while next_url:
            response = self.request(
                next_url,
                method="GET",
                params=current_params,
                return_response=True,
            )
            payload = response.json()
            if key:
                results.extend(payload.get(key, []))
            else:
                results.append(payload)

            next_url = self._extract_next_url(response.headers.get("Link"))
            current_params = None

        return results

    def test_connection(self):
        """Test the connection to the Shopify store."""
        data = self.get("shop.json")
        return data.get("shop", {}).get("name") or self.config.shop_url
