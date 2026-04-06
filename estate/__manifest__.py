{
    'name': 'Estate',
    'version': '1.0',
    'author': 'Tran Quoc',
    'license': 'LGPL-3',
    'depends': ['base'],
    'application': True,
    'installable': True,
    'auto_install': True,
    'data': [
        'security/ir.model.access.csv',
        'views/estate_property_views.xml',
        'views/estate_property_offer_views.xml',
        'report/estate_property_reports.xml',
        'report/estate_property_templates.xml',
    ]
}
