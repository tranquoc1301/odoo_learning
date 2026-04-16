import base64
import logging

import requests

from odoo import _, models

_logger = logging.getLogger(__name__)


def _fetch_image_b64(url, timeout=15):
    """Download *url* and return its content as a base64 string.

    Returns False if the URL is empty, times out, or is not an image.
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


class ShopifyConfigProduct(models.Model):
    """Product sync logic mixed into shopify.config."""

    _inherit = "shopify.config"

    # ── Entry point ───────────────────────────────────────────────────────────

    def sync_products(self):
        """Fetch all Shopify products and upsert them into Odoo.

        Returns a summary dict: {created, updated, errors}.
        """
        self.ensure_one()

        products = self._get_all_pages(
            "products.json",
            params={"limit": 50},
            key="products",
            sync_type="product",
        )

        created = updated = 0

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

        # Only sync fields that Shopify owns at the template level.
        # type/is_storable are controlled by variant tracking, not here.
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
            changed_vals = {k: v for k, v in vals.items() if current.get(k) != v}
            if changed_vals:
                template.write(changed_vals)
                action = "updated"
            else:
                action = "skipped"
        else:
            template = ProductTemplate.create(vals)
            action = "created"

        self._sync_product_images(template, shopify_product.get("images") or [])

        # Promote action to "updated" if any variant field (including price) changed.
        for variant in shopify_product.get("variants", []):
            variant_changed = self._sync_single_variant(template, variant)
            if variant_changed and action == "skipped":
                action = "updated"

        return action

    # ── Variant upsert ────────────────────────────────────────────────────────

    def _sync_single_variant(self, template, variant):
        """Create or update a product.product from a Shopify variant dict.

        Returns True if any field (including price) actually changed.
        """
        self.ensure_one()
        ProductVariant = self.env["product.product"]

        shopify_variant_id = str(variant["id"])
        sku = variant.get("sku") or False
        barcode = variant.get("barcode") or False
        price = float(variant.get("price") or 0.0)
        weight = variant.get("weight") or False
        inventory_item_id = str(variant.get("inventory_item_id") or "")
        inventory_management = variant.get("inventory_management")
        tracking = "lot" if inventory_management == "shopify" else "none"

        # Upgrade template to storable product when lot tracking is required.
        if tracking != "none" and not template.is_storable:
            template.write({"type": "consu", "is_storable": True})

        # --- Variant matching (in priority order) ---

        # 1. Exact match by Shopify variant ID (no config filter — IDs are globally unique).
        product = ProductVariant.search(
            [("shopify_variant_id", "=", shopify_variant_id)],
            limit=1,
        )

        # 2. Match by SKU within the same store.
        if not product and sku:
            product = ProductVariant.search(
                [
                    ("shopify_config_id", "=", self.id),
                    ("default_code", "=", sku),
                ],
                limit=1,
            )

        # 3. Reuse the sole variant on this template regardless of prior mapping.
        if not product and len(template.product_variant_ids) == 1:
            product = template.product_variant_id

        # 4. Fallback: find any variant with an empty combination_indices to prevent
        #    the unique-constraint violation on (product_tmpl_id, combination_indices).
        if not product:
            product = ProductVariant.search(
                [
                    ("product_tmpl_id", "=", template.id),
                    ("combination_indices", "=", ""),
                ],
                limit=1,
            )

        # 5. Nothing found — create a new variant record.
        if not product:
            product = ProductVariant.create({
                "product_tmpl_id": template.id,
                "shopify_variant_id": shopify_variant_id,
                "shopify_config_id": self.id,
            })

        # Price is intentionally excluded here; it is handled by _sync_variant_price()
        # because lst_price behaves differently for single- vs. multi-variant products.
        variant_vals = {
            "default_code": sku or False,
            "barcode": barcode,
            "weight": weight,
            "shopify_variant_id": shopify_variant_id,
            "shopify_inventory_item_id": inventory_item_id,
            # Use .id for Many2one so the comparison is int vs int, not recordset vs int.
            "shopify_config_id": self.id,
            "active": True,
            "tracking": tracking,
        }

        current = {
            "default_code": product.default_code or False,
            "barcode": product.barcode or False,
            "weight": product.weight or False,
            "shopify_variant_id": product.shopify_variant_id or "",
            "shopify_inventory_item_id": product.shopify_inventory_item_id or "",
            "shopify_config_id": product.shopify_config_id.id or False,
            "active": product.active,
            "tracking": product.tracking,
        }

        changed = False

        changed_vals = {k: v for k, v in variant_vals.items() if current.get(k) != v}
        if changed_vals:
            product.write(changed_vals)
            changed = True

        if self._sync_variant_price(template, product, price):
            changed = True

        return changed

    def _sync_variant_price(self, template, product, price):
        """Write the Shopify price to the correct Odoo field.

        - Single-variant product → list_price on product.template
        - Multi-variant product  → lst_price on product.product

        Returns True if the price was actually changed.
        """
        self.ensure_one()
        if len(template.product_variant_ids) == 1:
            if template.list_price != price:
                template.write({"list_price": price})
                return True
        else:
            if product.lst_price != price:
                product.write({"lst_price": price})
                return True
        return False

    # ── Image sync ────────────────────────────────────────────────────────────

    def _sync_product_images(self, template, images):
        """Assign Shopify images to the matching Odoo template or variant records."""
        self.ensure_one()
        if not images:
            return

        # Process images in Shopify's display order (position=1 is the primary image).
        sorted_images = sorted(images, key=lambda i: i.get("position", 999))

        # Build a shopify_variant_id → product.product map for O(1) lookup.
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
                # Unassigned image → set as the template's main image (first one only).
                if not main_image_set:
                    image_b64 = _fetch_image_b64(url)
                    if image_b64:
                        template.write({"image_1920": image_b64})
                        main_image_set = True
            else:
                # Variant-specific image → assign to each matching variant.
                for shopify_vid in variant_ids:
                    product = variant_map.get(str(shopify_vid))
                    if not product:
                        continue
                    # Skip variants that already have their own image.
                    if not product.image_1920:
                        image_b64 = _fetch_image_b64(url)
                        if image_b64:
                            product.write({"image_1920": image_b64})

        # Fallback: all images were variant-specific → use the first as the template image.
        if not main_image_set and sorted_images:
            url = sorted_images[0].get("src")
            if url:
                image_b64 = _fetch_image_b64(url)
                if image_b64:
                    template.write({"image_1920": image_b64})

    # ── Category helper ───────────────────────────────────────────────────────

    def _get_or_create_category(self, product_type):
        """Return a product.category for *product_type*, creating one if needed.

        Falls back to the default 'All' category when product_type is empty.
        """
        self.ensure_one()
        ProductCategory = self.env["product.category"]

        if product_type:
            category = ProductCategory.search([("name", "=", product_type)], limit=1)
            if category:
                return category
            return ProductCategory.create({"name": product_type})

        # No product type — use the built-in "All" category as the default.
        category = self.env.ref("product.product_category_all", raise_if_not_found=False)
        if category:
            return category

        category = ProductCategory.search([], limit=1)
        if category:
            return category

        return ProductCategory.create({"name": "All"})
