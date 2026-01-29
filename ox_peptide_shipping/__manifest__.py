{
    'name': 'Peptide Shipping & Discount Rules (Configurable)',
    'version': '18.0.1.1.0',
    'summary': 'Automate shipping & discounts for Peptide category with configurable category in Settings',
    'author': 'OutsetX',
    'website': 'https://www.outsetx.com',
    'category': 'Sales',
    'depends': ['sale_management', 'stock', 'website_sale', 'delivery'],
    'data': [
        'views/res_config_settings_views.xml',
        'data/delivery_carriers.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
