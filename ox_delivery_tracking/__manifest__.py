# -*- coding: utf-8 -*-
{
    'name': "Website Order Delivery Tracking",
    'version': '18.0.1.0.0',
    'category': 'Website',
    'summary': """Track order delivery status
    the status.""",
    'description': """This module allows us to track delivery status of Sales Orders 
    from the website using tracking numbers provided by various delivery carriers.""",
    'website': "https://www.outsetx.com",
    'depends': ['base', 'website', 'stock', 'sale_stock', 'sale_management', 'stock_delivery', 'ox_dropship_tracking_auto'],
    'data': [
        'views/tracking_menu.xml',
        'views/tracking_templates.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ox_delivery_tracking/static/src/css/delivery_tracking.css',
            'ox_delivery_tracking/static/src/js/delivery_tracking.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
