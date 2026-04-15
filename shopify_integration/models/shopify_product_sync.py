import base64
import logging
import re

import requests

from odoo import _, models

_logger = logging.getLogger(__name__)


def _fetch_image_b64(url, timeout=15):
    """Download an image from *url* and return its base64-encoded bytes as a string.

    Returns False when the URL is empty, the content is not an image.
    """
    if not url:
        return False
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


def _strip_html(html_str):
    """Convert an HTML string to plain text by removing all tags."""
    text = re.sub(r"<[^>]+>", " ", html_str or "")
    return re.sub(r"\s+", " ", text).strip()


class ShopifyConfigProduct(models.Model):
    """Product sync logic for shopify.config."""

    _inherit = "shopify.config"

    def sync_products(self):
        self.ensure_one()

        products = self._get_all_pages(
            "products.json",
            params={"limit": 50},
            key="products",
            sync_type="product",
        )

        created = 0
        updated = 0

        for shopify_product in products:
            result = self._sync_single_product(shopify_product)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1

        self._create_sync_log(
            sync_type="product",
            status="success",
            message=_(
                "Products synced. Created: %(created)s, Updated: %(updated)s"
            ) % {"created": created, "updated": updated},
        )
        return {"created": created, "updated": updated, "errors": 0}

    # ── Product upsert ────────────────────────────────────────────────────────

    def _sync_single_product(self, shopify_product):
        """Create or update a product.template from a Shopify product dict.

        Returns 'created', 'updated', or 'skipped'.
        """
        self.ensure_one()
        ProductTemplate = self.env["product.template"]

        shopify_product_id = str(shopify_product["id"])
        product_type = shopify_product.get("product_type") or ""
        category = self._get_or_create_category(product_type)

        template = ProductTemplate.search(
            [
                ("shopify_product_id", "=", shopify_product_id),
                ("shopify_config_id", "=", self.id),
            ],
            limit=1,
        )

        vals = {
            "name": shopify_product.get("title") or "",
            "description": shopify_product.get("body_html") or "",
            "categ_id": category.id,
            "shopify_product_id": shopify_product_id,
            "shopify_config_id": self.id,
            "shopify_product_type": product_type,
        }

        if template:
            current = {
                "name": template.name or "",
                "description": template.description or "",
                "categ_id": template.categ_id.id,
                "shopify_product_id": template.shopify_product_id or "",
                "shopify_config_id": template.shopify_config_id.id,
                "shopify_product_type": template.shopify_product_type or "",
            }
            changed_vals = {k: v for k, v in vals.items() if current[k] != v}
            if changed_vals:
                template.write(changed_vals)
                action = "updated"
            else:
                action = "skipped"
        else:
            template = ProductTemplate.create(vals)
            action = "created"

        self._sync_product_images(template, shopify_product.get("images") or [])

        for variant in shopify_product.get("variants", []):
            self._sync_single_variant(template, variant)

        return action

    # ── Variant upsert ────────────────────────────────────────────────────────

    def _sync_single_variant(self, template, variant):
        """Create or update a product.product (variant) from a Shopify variant dict."""
        self.ensure_one()
        ProductVariant = self.env["product.product"]

        shopify_variant_id = str(variant["id"])
        sku = variant.get("sku") or False
        barcode = variant.get("barcode") or False
        price = float(variant.get("price") or 0.0)
        weight = variant.get("weight") or False
        inventory_item_id = str(variant.get("inventory_item_id") or "")

        # 1. Match by Shopify Variant ID
        product = ProductVariant.search(
            [
                ("shopify_variant_id", "=", shopify_variant_id),
                ("shopify_config_id", "=", self.id),
            ],
            limit=1,
        )

        # 2. Match by SKU within the same store
        if not product and sku:
            product = ProductVariant.search(
                [
                    ("shopify_config_id", "=", self.id),
                    ("default_code", "=", sku),
                ],
                limit=1,
            )

        # 3. Reuse the default variant if it is the only one and not yet mapped
        if not product:
            default_variant = template.product_variant_id
            if (
                    len(template.product_variant_ids) == 1
                    and not default_variant.shopify_variant_id
            ):
                product = default_variant

        # 4. Create a new variant record
        if not product:
            product = ProductVariant.create({
                "product_tmpl_id": template.id,
                "shopify_variant_id": shopify_variant_id,
                "shopify_config_id": self.id,
            })

        variant_vals = {
            "default_code": sku or False,
            "barcode": barcode,
            "lst_price": price,
            "weight": weight,
            "shopify_variant_id": shopify_variant_id,
            "shopify_inventory_item_id": inventory_item_id,
            "shopify_config_id": self.id,
            "active": True,
        }

        # Build current values dùng .id cho Many2one (shopify_config_id)
        # để so sánh đúng kiểu — tránh recordset != int luôn True
        current = {
            "default_code": product.default_code or False,
            "barcode": product.barcode or False,
            "lst_price": product.lst_price,
            "weight": product.weight or False,
            "shopify_variant_id": product.shopify_variant_id or "",
            "shopify_inventory_item_id": product.shopify_inventory_item_id or "",
            "shopify_config_id": product.shopify_config_id.id,
            "active": product.active,
        }
        changed_vals = {k: v for k, v in variant_vals.items() if current[k] != v}
        if changed_vals:
            product.write(changed_vals)

    # ── Image sync ────────────────────────────────────────────────────────────

    def _sync_product_images(self, template, images):
        """Assign Shopify images to the corresponding Odoo records."""
        self.ensure_one()
        if not images:
            return

        # Sort by position so the primary image (position=1) comes first
        sorted_images = sorted(images, key=lambda i: i.get("position", 999))

        # Build shopify_variant_id -> product.product map for O(1) lookup
        variant_map = {
            v.shopify_variant_id: v
            for v in template.product_variant_ids
            if v.shopify_variant_id
        }

        main_image_set = False

        for img in sorted_images:
            url = img.get("src")
            if not url:
                continue

            variant_ids = img.get("variant_ids") or []

            if not variant_ids:
                # Unassigned image → use as the main template image (first occurrence only)
                if not main_image_set:
                    image_b64 = _fetch_image_b64(url)
                    if image_b64:
                        template.write({"image_1920": image_b64})
                        main_image_set = True
            else:
                # Variant-specific image → assign to each matching variant
                for shopify_vid in variant_ids:
                    product = variant_map.get(str(shopify_vid))
                    if not product:
                        continue
                    # Only set if the variant does not already have its own image
                    if not product.image_1920:
                        image_b64 = _fetch_image_b64(url)
                        if image_b64:
                            product.write({"image_1920": image_b64})

        # Fallback: every image was variant-specific → use the first one as the main image
        if not main_image_set and sorted_images:
            url = sorted_images[0].get("src")
            if url:
                image_b64 = _fetch_image_b64(url)
                if image_b64:
                    template.write({"image_1920": image_b64})

    # ── Category helper ───────────────────────────────────────────────────────

    def _get_or_create_category(self, product_type):
        """Return a product.category matching *product_type*, creating one if needed."""
        self.ensure_one()
        ProductCategory = self.env["product.category"]

        if product_type:
            category = ProductCategory.search([("name", "=", product_type)], limit=1)
            if category:
                return category
            return ProductCategory.create({"name": product_type})

        category = self.env.ref("product.product_category_all", raise_if_not_found=False)
        if category:
            return category

        category = ProductCategory.search([], limit=1)
        if category:
            return category

        return ProductCategory.create({"name": "All"})
