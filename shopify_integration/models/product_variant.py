from odoo import fields, models


class ProductVariant(models.Model):
    _inherit = "product.product"

    shopify_variant_id = fields.Char(
        string="Shopify Variant ID",
        index=True,
        copy=False,
        readonly=True,
    )
    shopify_inventory_item_id = fields.Char(
        string="Shopify Inventory Item ID",
        index=True,
        copy=False,
        readonly=True,
    )
    shopify_config_id = fields.Many2one(
        "shopify.config",
        string="Shopify Store",
        copy=False,
        index=True,
        readonly=True,
        ondelete="set null",
    )
    _shopify_variant_unique_per_store = models.Constraint(
        "unique(shopify_variant_id, shopify_config_id)",
        "The Shopify variant must be unique per store.",
    )