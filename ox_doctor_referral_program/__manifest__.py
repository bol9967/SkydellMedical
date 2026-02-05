# -*- coding: utf-8 -*-
{
    'name': 'OX Doctor Referral Program',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Salesperson and Doctor Referral Program with Commission and Promo Rewards',
    'description': """
        Doctor Referral Program
        =======================

        Features:
        - Salesperson onboarding links for doctors
        - Doctor-to-doctor referral chain
        - Automatic salesperson assignment based on referral chain
        - Commission tracking via ox_sales_commission module
        - Promo reward system (free vials) for Doctor 1 referrals
        - Multi-level referral tracking
        - Portal QR code for referral links

        Python Dependencies:
        - qrcode[pil] (for QR code generation)
    """,
    'author': 'OutsetX',
    'website': 'https://www.outsetx.com',
    'depends': [
        'base',
        'contacts',
        'sales_team',
        'sale_management',
        'website_sale',
        'auth_signup',
        'portal',  # For portal templates
        'ox_sales_commission',  # For commission tracking
        # Note: ox_own_contacts_visibility is optional but compatible
        # If installed, it will auto-assign creator as salesperson,
        # which this module will override if referral chain exists
        # Note: ox_partner_npi is optional but fully integrated
        # If installed, referral processing works seamlessly with NPI signup flow
    ],
    'external_dependencies': {
        'python': ['qrcode'],
    },
    'data': [
        'security/ir.model.access.csv',
        'security/referral_security.xml',
        'data/referral_data.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/referral_reward_views.xml',
        'views/referral_reward_rule_views.xml',
        'views/referral_tracking_views.xml',
        'views/portal_templates.xml',
        'views/res_users_views.xml',
        # Analytics views removed
        # Dashboard views removed - will be configured in next phase
        # 'views/referral_dashboard_views.xml',
        # 'views/referral_dashboard_kanban.xml',
        'views/menu_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ox_doctor_referral_program/static/src/js/referral_signup.js',
            'ox_doctor_referral_program/static/src/js/referral_portal.js',
        ],
        'web.assets_backend': [
            'ox_doctor_referral_program/static/src/js/referral_qr_widget.js',
            'ox_doctor_referral_program/static/src/xml/referral_qr_widget.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
