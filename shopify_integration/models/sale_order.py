from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    shopify_order_id = fields.Char(
        string="Shopify Order ID",
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

    _shopify_order_unique_per_store = models.Constraint(
        "unique(shopify_order_id, shopify_config_id)",
        "The Shopify order must be unique per store.",
    )