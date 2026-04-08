{
    'name': 'Shopify Integration',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Sync products, inventory, and orders from Shopify',
    'description': """
        Shopify Integration Module - Automatically syncs products, inventory, and orders from Shopify to Odoo.
        Features:
        - Product sync with variants (SKU, price, barcode)
        - Order import with customer matching
        - Inventory level updates
        - Manual sync wizard
        - Comprehensive sync logging
    """,
    'author': 'Tran Quoc',
    'depends': ['sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/shopify_config_views.xml',
        'views/sync_log_views.xml',
        'views/product_mapping_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3'
}
