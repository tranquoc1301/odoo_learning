from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    shopify_product_id = fields.Char(index=True, copy=False, readonly=True)
    shopify_config_id = fields.Many2one(
        "shopify.config",
        copy=False,
        index=True,
        readonly=True,
    )
    shopify_product_type = fields.Char(copy=False)

    _sql_constraints = [
        (
            "shopify_product_unique_per_store",
            "unique(shopify_product_id, shopify_config_id)",
            "The Shopify product must be unique per store.",
        ),
    ]