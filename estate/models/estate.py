from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

from odoo.orm.decorators import constrains


class EstateProperty(models.Model):
    _name = "estate.property"
    _description = "Real Estate Property"
    _check_expected_price = models.Constraint(
        'CHECK(expected_price > 0)',
        'The expected price must be strictly positive.',
    )
    _check_selling_price = models.Constraint(
        'CHECK(selling_price >= 0)',
        'The selling price must be positive.',
    )

    # ── Basic fields ──────────────────────────────────
    name = fields.Char(required=True)
    description = fields.Text()
    offer_ids = fields.One2many("estate.property.offer", "property_id", string="Offers")
    tag_ids = fields.Many2many("estate.property.tag", string="Tags")
    postcode = fields.Char()
    property_type_id = fields.Many2one("estate.property.type", string="Property Type")
    expected_price = fields.Float(required=True)
    bedrooms = fields.Integer(default=2)
    living_area = fields.Integer()
    facades = fields.Integer()
    garage = fields.Boolean()
    garden = fields.Boolean()
    garden_area = fields.Integer()  #
    garden_orientation = fields.Selection(
        string='Garden Orientation',
        selection=[
            ('north', 'North'),
            ('east', 'East'),
            ('south', 'South'),
            ('west', 'West'),
        ],
        help="Select the orientation of the garden"
    )
    total_area = fields.Float(compute='_compute_total_area', store=True)

    date_availability = fields.Date(
        copy=False,
        default=lambda self: fields.Date.today() + relativedelta(months=3)
    )
    selling_price = fields.Float(
        readonly=True,
        copy=False
    )

    buyer_id = fields.Many2one("res.partner", string="Buyer", readonly=True, copy=False)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('offer_received', 'Offer Received'),
            ('offer_accepted', 'Offer Accepted'),
            ('sold', 'Sold'),
            ('cancelled', 'Cancelled'),
        ],
        required=True,
        copy=False,
        default='new',
    )

    def action_cancel(self):
        for record in self:
            if record.state == 'sold':
                raise UserError("Cannot cancel a sold property.")
            record.state = 'cancelled'
        return True

    def action_sold(self):
        for record in self:
            if record.state == 'cancelled':
                raise UserError("Cannot sell a cancelled property.")
            record.state = 'sold'
        return True

    @api.depends('living_area', 'garden_area')
    def _compute_total_area(self):
        for record in self:
            record.total_area = record.living_area + record.garden_area
