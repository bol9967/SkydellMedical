{
    'name': 'Sale Negative Stock Control',
    'version': '18.0.1.0.0',
    'summary': 'Prevent negative stock sales and control product visibility in sale orders',
    'description': """
Sale Negative Stock Control
===========================
This module prevents products with zero on-hand quantity from being added to sale orders 
(Sale app only, not website/e-commerce).

Features:
---------
* Prevents adding products with zero stock to sale order lines
* Configurable stock filtering in product search
* Display on-hand quantity column in sale order lines
* Only applies to Sale app - website/e-commerce orders are not affected
    """,
    'category': 'Sales',
    'author': 'Custom Development',
    'website': '',
    'depends': [
        'sale',
        'stock',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
