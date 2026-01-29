
# -*- coding: utf-8 -*-
{
    'name': 'Remove Powered by Odoo',
    'version': '18.0.1.0.0',
    'summary': """Remove Powered by Odoo from Login, Portal and Brand Promotion from website footer. 
    Remove Odoo branding from the footer of portal pages.
    """,
    'description': """ Remove Powered by Odoo from Portal
        Removing the 'Powered by' block entirely 
        Remove from the portal sidebar.
        Remove from the login page.
        Remove from the brand promotion.
        Remove Odoo branding from the footer of portal pages.
    """,
    'company': 'OutsetX',
    'website': 'https://outsetx.com',
    'license': 'LGPL-3',
    'sequence': 10,
    'category': 'Tools',
    'depends': ['portal', 'website'],
    'data': [
        'views/login_layout.xml',
        'views/portal_record_sidebar.xml',
        'views/brand_promotion.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
