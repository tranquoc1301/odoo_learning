from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    shopify_product_id = fields.Char(
        string="Shopify Product ID",
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
    shopify_product_type = fields.Char(
        string="Shopify Product Type",
        copy=False,
    )

    _sql_constraints = [
        (
            "shopify_product_unique_per_store",
            "unique(shopify_product_id, shopify_config_id)",
            "The Shopify product must be unique per store.",
        ),
    ]
