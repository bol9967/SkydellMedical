# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Website Sale Payment Processing Fee',
    'version': '18.0.1.0.0',
    'category': 'Website/eCommerce',
    'sequence': 350,
    'summary': 'Add 4% card processing fee for online payments on website orders',
    'description': """
        Website Sale Payment Processing Fee
        ===================================
        
        This module adds a 4% card processing fee for online payments on website orders.
        
        Features:
        * Automatic 4% processing fee for online card payments
        * Configurable fee percentage
        * Fee is added as a separate line item on the order
        * Only applies to website orders with online payments
        * Fee is calculated on order total (excluding delivery)
    """,
    'depends': ['website_sale', 'payment', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/product_data.xml',
        'views/payment_provider_views.xml',
        'views/payment_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ox_website_sale_payment_fee/static/src/js/payment_fee.js',
            'ox_website_sale_payment_fee/static/src/js/payment_portal_fee.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

