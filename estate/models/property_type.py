from odoo import fields, models


class EstatePropertyType(models.Model):
    _name = "estate.property.type"
    _description = "Property Type for Real Estate"
    _unique_name = models.Constraint(
        'UNIQUE(name)',
        'A property type name must be unique.',
    )

    name = fields.Char(required=True)