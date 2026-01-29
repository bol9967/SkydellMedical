# -*- coding: utf-8 -*-
{
    'name': 'Sales Team Hierarchy Access',
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Allow sales team leaders to view records of their team members',
    'description': """
        This module extends the access rules for sales orders and CRM leads
        to allow sales team leaders to view records belonging to their team members.
        
        Features:
        - Team leaders can see all sales orders of their team members
        - Team leaders can see all CRM leads/opportunities of their team members
        - Maintains existing personal record access for regular salespersons
    """,
    'author': 'OutsetX',
    'website': 'https://www.outsetx.com',
    'depends': [
        'base',
        'sales_team',
        'sale',
        'crm',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'views/res_users_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
