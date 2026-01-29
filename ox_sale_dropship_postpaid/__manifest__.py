# -*- coding: utf-8 -*-
{
    'name': "Dropship PO After Payment",
    'summary': "Create dropship Purchase Orders only after customer payment or paid invoice.",
    'version': '18.0.1.0.0',
    'author': "OutsetX",
    'license': 'LGPL-3',
    'category': 'Sales',
    'depends': [
        'sale_stock',   # sale + stock + routes + _action_launch_stock_rule
        'payment',      # payment.transaction
        'account',      # account.move payment_state
        'delivery',     # delivery.carrier for shipping method
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
