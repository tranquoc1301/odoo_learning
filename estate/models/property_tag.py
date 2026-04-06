from odoo import models, fields

class EstatePropertyTag(models.Model):
    _name = "estate.property.tag"
    _description = "Property Tag for Real Estate"
    _unique_name = models.Constraint(
        'UNIQUE(name)',
        'A property tag name must be unique.',
    )

    name = fields.Char(required=True)