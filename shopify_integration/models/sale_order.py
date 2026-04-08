from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    shopify_order_id = fields.Char(index=True, copy=False, readonly=True)
    shopify_config_id = fields.Many2one(
        "shopify.config",
        copy=False,
        index=True,
        readonly=True,
    )

    _sql_constraints = [
        (
            "shopify_order_unique_per_store",
            "unique(shopify_order_id, shopify_config_id)",
            "The Shopify order must be unique per store.",
        ),
    ]

