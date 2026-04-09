import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..constants import HTTP_RATE_LIMITED, SHOPIFY_API_VERSION

_logger = logging.getLogger(__name__)


class ShopifyConfig(models.Model):
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
            sync_type="product",
            timeout=30,
            return_response=False,
    ):
        self.ensure_one()

        if endpoint_or_url.startswith("http"):
            url = endpoint_or_url
        else:
            url = f"{self._get_base_url()}/{endpoint_or_url.lstrip('/')}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                params=params,
                json=payload,
                timeout=timeout,
            )

            if response.status_code == HTTP_RATE_LIMITED:
                retry_after = float(response.headers.get("Retry-After", 1))
                _logger.warning("Shopify rate limited. Sleeping %s seconds", retry_after)
                time.sleep(retry_after)
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    params=params,
                    json=payload,
                    timeout=timeout,
                )

            response.raise_for_status()
            return response if return_response else response.json()

        except Exception as exc:
            message = _("Shopify API error: %s") % exc
            _logger.exception(message)
            self._create_sync_log(
                sync_type=sync_type,
                status="failed",
                message=message,
            )
            raise UserError(message) from exc

    def _extract_next_url(self, link_header):
        if not link_header:
            return False
        matches = re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', link_header)
        for url, rel in matches:
            if rel == "next":
                return url
        return False

    def _get_all_pages(self, endpoint, params=None, key=None, sync_type="product"):
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
            current_params = None

        return results

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

    def _get_or_create_category(self, product_type):
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
            message=_("Products synced. Created: %(created)s, Updated: %(updated)s") % {
                "created": created,
                "updated": updated,
            },
        )
        return {"created": created, "updated": updated, "errors": 0}

    def _sync_single_product(self, shopify_product):
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
            "description_sale": shopify_product.get("body_html") or "",
            "categ_id": category.id,
            "shopify_product_id": shopify_product_id,
            "shopify_config_id": self.id,
            "shopify_product_type": product_type,
        }

        if template:
            template.write(vals)
            action = "updated"
        else:
            template = ProductTemplate.create(vals)
            action = "created"

        for variant in shopify_product.get("variants", []):
            self._sync_single_variant(template, variant)

        return action

    def _sync_single_variant(self, template, variant):
        self.ensure_one()
        ProductVariant = self.env["product.product"]

        shopify_variant_id = str(variant["id"])
        sku = variant.get("sku") or ""
        price = float(variant.get("price") or 0.0)
        barcode = variant.get("barcode") or ""
        inventory_item_id = variant.get("inventory_item_id")

        product = ProductVariant.search(
            [
                ("shopify_config_id", "=", self.id),
                "|",
                ("shopify_variant_id", "=", shopify_variant_id),
                ("default_code", "=", sku),
            ],
            limit=1,
        )

        if not product:
            product = template.product_variant_id

        vals = {
            "default_code": sku,
            "barcode": barcode,
            "lst_price": price,
            "shopify_variant_id": shopify_variant_id,
            "shopify_inventory_item_id": str(inventory_item_id or ""),
            "shopify_config_id": self.id,
            "active": True,
        }

        product.write(vals)

    def sync_orders(self, date_from=None, date_to=None):
        self.ensure_one()

        params = {
            "limit": 50,
            "status": "any",
        }

        if date_from:
            params["created_at_min"] = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif self.last_sync:
            params["created_at_min"] = self.last_sync.strftime("%Y-%m-%dT%H:%M:%SZ")

        if date_to:
            params["created_at_max"] = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")

        orders = self._get_all_pages(
            "orders.json",
            params=params,
            key="orders",
            sync_type="order",
        )

        created = 0
        skipped = 0
        partial = 0

        for shopify_order in orders:
            result = self._sync_single_order(shopify_order)
            if result == "created":
                created += 1
            elif result == "skipped":
                skipped += 1
            else:
                partial += 1

        self.last_sync = fields.Datetime.now()
        self._create_sync_log(
            sync_type="order",
            status="success" if not partial else "partial",
            message=_(
                "Orders synced. Created: %(created)s, Skipped: %(skipped)s, Partial: %(partial)s"
            ) % {
                        "created": created,
                        "skipped": skipped,
                        "partial": partial,
                    },
        )
        return {"created": created, "updated": 0, "errors": partial}

    def _sync_single_order(self, shopify_order):
        self.ensure_one()
        SaleOrder = self.env["sale.order"]

        shopify_order_id = str(shopify_order["id"])
        existing_order = SaleOrder.search(
            [
                ("shopify_order_id", "=", shopify_order_id),
                ("shopify_config_id", "=", self.id),
            ],
            limit=1,
        )
        if existing_order:
            return "skipped"

        partner = self._get_or_create_customer(shopify_order)
        shipping_partner = self._get_or_create_delivery_partner(partner, shopify_order)

        lines = []
        for item in shopify_order.get("line_items", []):
            sku = item.get("sku") or ""
            variant_id = str(item.get("variant_id") or "")

            product = self.env["product.product"].search(
                [
                    ("shopify_config_id", "=", self.id),
                    "|",
                    ("shopify_variant_id", "=", variant_id),
                    ("default_code", "=", sku),
                ],
                limit=1,
            )

            if not product:
                self._create_sync_log(
                    sync_type="order",
                    status="partial",
                    message=_("Missing SKU while importing order: %s") % (sku or "-"),
                    shopify_id=str(item.get("id") or ""),
                    external_ref=shopify_order.get("name"),
                )
                continue

            lines.append((0, 0, {
                "product_id": product.id,
                "name": item.get("title") or product.display_name,
                "product_uom_qty": item.get("quantity", 1),
                "price_unit": float(item.get("price") or 0.0),
            }))

        if not lines:
            self._create_sync_log(
                sync_type="order",
                status="failed",
                message=_("Order %s skipped because no valid order lines were found.")
                        % (shopify_order.get("name") or shopify_order_id),
                shopify_id=shopify_order_id,
            )
            return "partial"

        order = SaleOrder.create({
            "partner_id": partner.id,
            "partner_invoice_id": partner.id,
            "partner_shipping_id": shipping_partner.id,
            "warehouse_id": self.warehouse_id.id,
            "shopify_order_id": shopify_order_id,
            "shopify_config_id": self.id,
            "client_order_ref": shopify_order.get("name") or f"shopify_{shopify_order_id}",
            "date_order": self._parse_shopify_datetime(shopify_order.get("created_at")),
            "order_line": lines,
        })
        order.action_confirm()
        return "created"

    def _parse_shopify_datetime(self, value):
        if not value:
            return fields.Datetime.now()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return fields.Datetime.now()

    def _get_or_create_customer(self, shopify_order):
        self.ensure_one()
        Partner = self.env["res.partner"]

        customer_data = shopify_order.get("customer") or {}
        email = customer_data.get("email") or shopify_order.get("email") or ""
        if not email:
            return self.env.ref("base.public_partner")

        partner = Partner.search(
            [("email", "=", email), ("type", "=", "contact")],
            limit=1,
        )
        if partner:
            return partner

        full_name = " ".join(
            filter(
                None,
                [
                    customer_data.get("first_name"),
                    customer_data.get("last_name"),
                ],
            )
        ) or email

        return Partner.create({
            "name": full_name,
            "email": email,
            "type": "contact",
        })

    def _get_or_create_delivery_partner(self, partner, shopify_order):
        self.ensure_one()
        Partner = self.env["res.partner"]
        shipping = shopify_order.get("shipping_address") or {}

        if not shipping:
            return partner

        vals = {
            "parent_id": partner.id,
            "type": "delivery",
            "name": shipping.get("name") or partner.name,
            "street": shipping.get("address1") or "",
            "street2": shipping.get("address2") or "",
            "city": shipping.get("city") or "",
            "zip": shipping.get("zip") or "",
            "phone": shipping.get("phone") or "",
            "country_id": self._get_country_id(shipping.get("country")),
        }

        delivery = Partner.search(
            [
                ("parent_id", "=", partner.id),
                ("type", "=", "delivery"),
                ("street", "=", vals["street"]),
                ("zip", "=", vals["zip"]),
            ],
            limit=1,
        )
        if delivery:
            delivery.write(vals)
            return delivery

        return Partner.create(vals)

    def _get_country_id(self, country_name):
        if not country_name:
            return False
        country = self.env["res.country"].search([("name", "=", country_name)], limit=1)
        return country.id or False

    def sync_inventory(self):
        self.ensure_one()
        self._create_sync_log(
            sync_type="inventory",
            status="partial",
            message=_(
                "Inventory sync requires product.shopify_inventory_item_id and a location mapping strategy before applying quantities through Odoo ORM."
            ),
        )
        return {"created": 0, "updated": 0, "errors": 1}

    def sync_all(self):
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

    def _run_cron_sync(self, method_name):
        for config in self.search([("active", "=", True)]):
            try:
                getattr(config, method_name)()
            except Exception:
                _logger.exception("Cron %s failed for config %s", method_name, config.display_name)
        return True

    def cron_sync_products(self):
        return self._run_cron_sync("sync_products")

    def cron_sync_orders(self):
        return self._run_cron_sync("sync_orders")

    def cron_sync_inventory(self):
        return self._run_cron_sync("sync_inventory")
