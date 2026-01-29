# -*- coding: utf-8 -*-
{
    'name': 'Sales Team Hierarchy',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Allow team leaders to view records of their team members',
    'description': """
        Sales Team Hierarchy
        ====================
        
        This module extends Odoo's native access control to add a 4th tier:
        
        1. Administrator - Sees everything (bypasses all rules)
        2. All Documents - Sees everything (permissive rule)
        3. Team Leader Access - Sees own records + team member records (NEW)
        4. Own Documents Only - Sees only own records (restrictive rule)
        
        Team leaders can view sales orders and CRM leads of users who are
        members of teams they lead. If a team leader has no team members,
        they fall back to "Own Documents Only" behavior.
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
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
