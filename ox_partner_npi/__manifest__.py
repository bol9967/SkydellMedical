# -*- coding: utf-8 -*-
{
    "name": "Partner NPI Number",
    "summary": "Adds NPI# to partners and displays it across Sales, Purchases, and Accounting documents.",
    "version": "18.0.1.0.0",
    "category": "Contacts",
    "author": "OutsetX",
    "website": "https://www.outsetx.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "sale",
        "account",
        "purchase",
        "auth_signup",
        "web",
        "portal",
    ],
    "data": [
        # Security
        "security/ir.model.access.csv",
        
        # Views
        "views/res_partner_view.xml",
        "views/sale_order_view.xml",
        "views/purchase_order_view.xml",
        "views/account_move_view.xml",
        "views/auth_signup_templates.xml",
        "views/signup_terms_templates.xml",
        "views/signup_2fa_templates.xml",
        "views/terms_conditions_views.xml",
        "views/res_config_settings_views.xml",

        # Reports
        "reports/report_saleorder_nip.xml",
        "reports/report_invoice_nip.xml",
        "reports/report_purchaseorder_nip.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "ox_partner_npi/static/src/js/npi_validation.js",
            "ox_partner_npi/static/src/js/terms_acceptance.js",
            "ox_partner_npi/static/src/js/2fa_otp.js",
            ("include", "web/static/lib/signature_pad/signature_pad.umd.js"),
        ],
    },
    "application": False,
    "installable": True,
}
