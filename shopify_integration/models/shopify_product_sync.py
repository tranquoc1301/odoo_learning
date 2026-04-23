import base64
import logging

import requests

from odoo import _, models
from ..constants import (
    PRODUCT_PAGE_LIMIT,
    IMAGE_DOWNLOAD_TIMEOUT,
    DEFAULT_IMAGE_POSITION,
    DEFAULT_VARIANT_SEARCH_LIMIT,
    DEFAULT_CATEGORY_SEARCH_LIMIT,
    SYNC_TYPE_PRODUCT,
    STATUS_SUCCESS,
    STATUS_PARTIAL,
    STATUS_FAILED,
)

_logger = logging.getLogger(__name__)


def _compute_changed_vals(record, new_vals):
    current = {}
    for key in new_vals:
        value = getattr(record, key, False)
        # Handle Many2one relational fields (stored as recordset)
        if hasattr(value, 'id'):
            value = value.id or False
        current[key] = value

    return {k: v for k, v in new_vals.items() if current.get(k) != v}


def _fetch_image_b64(url, timeout=None):
    """Download *url* and return its content as a base64 string.

    Returns False if the URL is empty, times out, or is not an image.
    """
    if not url:
        return False
    if timeout is None:
        timeout = IMAGE_DOWNLOAD_TIMEOUT
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            _logger.warning("URL %s is not an image: %s", url, content_type)
            return False
        return base64.b64encode(response.content).decode("utf-8")
    except requests.exceptions.Timeout:
        _logger.warning("Timeout downloading image: %s", url)
        return False
    except requests.exceptions.RequestException as exc:
        _logger.warning("Failed to download image %s: %s", url, exc)
        return False


class ShopifyConfigProduct(models.Model):
    """Product sync logic mixed into shopify.config."""

    _inherit = "shopify.config"

    def sync_products(self):
        self.ensure_one()

        products = self._get_all(
            "products.json",
            params={"limit": PRODUCT_PAGE_LIMIT},
            key="products",
        )

        created = updated = errors = 0

        for shopify_product in products:
            try:
                with self.env.cr.savepoint():
                    result = self._sync_single_product(shopify_product)
                    if result == "created":
                        created += 1
                    elif result == "updated":
                        updated += 1
            except Exception as exc:
                errors += 1
                _logger.error(
                    "Failed to sync product %s: %s",
                    shopify_product.get("id"),
                    exc,
                    exc_info=True,
                )

        status = STATUS_SUCCESS if not errors else STATUS_PARTIAL
        self.env["sync.log"].create_from_config(
            self,
            sync_type=SYNC_TYPE_PRODUCT,
            status=status,
            message=_(
                "Products synced. Created: %(created)s, Updated: %(updated)s, Errors: %(errors)s"
            )
            % {"created": created, "updated": updated, "errors": errors},
        )
        return {"created": created, "updated": updated, "errors": errors}

    # ── Product upsert ────────────────────────────────────────────────────────

    def _sync_single_product(self, shopify_product):
        """Upsert a Shopify product into a product.template record."""

        self.ensure_one()
        ProductTemplate = self.env["product.template"]

        shopify_product_id = str(shopify_product["id"])
        product_type = shopify_product.get("product_type") or ""
        # Map Shopify product_type to an Odoo product.category
        category = self._get_or_create_category(product_type)

        # Check if this product was already imported from the same store
        template = self._find_by_shopify_id(
            "product.template", "shopify_product_id", shopify_product_id
        )

        # Fetched product data from Shopify API
        vals = {
            "name": shopify_product.get("title") or "",
            "description": shopify_product.get("body_html") or "",
            "categ_id": category.id,
            "shopify_product_id": shopify_product_id,
            "shopify_config_id": self.id,
            "shopify_product_type": product_type,
        }

        if template:
            changed_vals = _compute_changed_vals(template, vals)
            if changed_vals:
                template.write(changed_vals)
                action = "updated"
            else:
                action = "skipped"
        else:
            template = ProductTemplate.create(vals)
            action = "created"

        # image_cache is a dict {url: base64_string} shared across all variants of this product to avoid downloading the same image multiple times.
        image_cache = {}
        self._sync_product_images(
            template, shopify_product.get("images") or [], image_cache
        )

        # Sync each Shopify variant to a product.product record.
        # If any variant changes, upgrade "skipped" → "updated".
        for variant in shopify_product.get("variants", []):
            variant_changed = self._sync_single_variant(template, variant)
            if variant_changed and action == "skipped":
                action = "updated"

        return action

    # ── Variant upsert ────────────────────────────────────────────────────────

    def _sync_single_variant(self, template, variant):
        """Upsert a single Shopify variant into a product.product record."""
        self.ensure_one()
        ProductVariant = self.env["product.product"]

        shopify_variant_id = str(variant["id"])
        sku = variant.get("sku") or False
        barcode = variant.get("barcode") or False
        price = float(variant.get("price") or 0.0)
        inventory_item_id = str(variant.get("inventory_item_id") or "")
        # inventory_management="shopify" means Shopify tracks stock for this variant.
        # Map to Odoo's tracking field: "lot" enables stock moves, "none" disables.
        inventory_management = variant.get("inventory_management")
        tracking = "lot" if inventory_management == "shopify" else "none"

        # If Shopify tracks stock, ensure the product is storable in Odoo
        if tracking != "none" and not template.is_storable:
            template.write({"type": "consu", "is_storable": True})

        # 1. Exact Shopify variant ID match
        product = ProductVariant.search(
            [("shopify_variant_id", "=", shopify_variant_id)],
            limit=1,
        )
        # 2. SKU match within the same store
        if not product and sku:
            product = self._find_by_shopify_id(
                "product.product", "default_code", sku
            )
        # 3. Reuse the sole variant on this template
        if not product and len(template.product_variant_ids) == 1:
            product = template.product_variant_id
        # 4. Fallback: empty combination_indices variant
        if not product:
            product = ProductVariant.search(
                [
                    ("product_tmpl_id", "=", template.id),
                    ("combination_indices", "=", ""),
                ],
                limit=1,
            )
        # 5. Create new variant
        if not product:
            product = ProductVariant.create(
                {
                    "product_tmpl_id": template.id,
                    "shopify_variant_id": shopify_variant_id,
                    "shopify_config_id": self.id,
                }
            )

        variant_vals = {
            "default_code": sku or False,
            "barcode": barcode,
            "shopify_variant_id": shopify_variant_id,
            "shopify_inventory_item_id": inventory_item_id,
            "shopify_config_id": self.id,
            "active": True,
            "weight": float(variant.get("weight") or 0.0),
            "tracking": tracking,
        }

        changed_vals = _compute_changed_vals(product, variant_vals)
        changed = bool(changed_vals)
        if changed_vals:
            product.write(changed_vals)

        if self._sync_variant_price(template, product, price):
            changed = True

        return changed

    def _sync_variant_price(self, template, product, price):
        if len(template.product_variant_ids) == 1:
            if template.list_price != price:
                template.write({"list_price": price})
                return True
        elif product.lst_price != price:
            product.write({"lst_price": price})
            return True
        return False

    # ── Image sync ────────────────────────────────────────────────────────────

    def _sync_product_images(self, template, images, image_cache=None):
        if not images:
            return

        if image_cache is None:
            image_cache = {}

        def fetch_cached(url):
            if url not in image_cache:
                image_cache[url] = _fetch_image_b64(url)
            return image_cache[url]

        sorted_images = sorted(
            images, key=lambda i: i.get("position", DEFAULT_IMAGE_POSITION)
        )
        variant_map = {
            v.shopify_variant_id: v
            for v in template.product_variant_ids
            if v.shopify_variant_id
        }
        main_image_set = template.image_1920

        for img in sorted_images:
            url = img.get("src")
            if not url:
                continue
            variant_ids = img.get("variant_ids") or []
            if not variant_ids:
                if not main_image_set:
                    image_b64 = fetch_cached(url)
                    if image_b64:
                        template.write({"image_1920": image_b64})
                        main_image_set = True
            else:
                for shopify_vid in variant_ids:
                    product = variant_map.get(str(shopify_vid))
                    if not product or product.image_1920:
                        continue
                    image_b64 = fetch_cached(url)
                    if image_b64:
                        product.write({"image_1920": image_b64})

        if not main_image_set and sorted_images:
            url = sorted_images[0].get("src")
            if url:
                image_b64 = fetch_cached(url)
                if image_b64:
                    template.write({"image_1920": image_b64})

    # ── Category helper ───────────────────────────────────────────────────────

    def _get_or_create_category(self, product_type):
        ProductCategory = self.env["product.category"]
        if product_type:
            category = ProductCategory.search(
                [("name", "=", product_type)],
                limit=DEFAULT_CATEGORY_SEARCH_LIMIT,
            )
            return category or ProductCategory.create({"name": product_type})
        return (
                self.env.ref("product.product_category_all", raise_if_not_found=False)
                or ProductCategory.search([], limit=DEFAULT_CATEGORY_SEARCH_LIMIT)
                or ProductCategory.create({"name": "All"})
        )
