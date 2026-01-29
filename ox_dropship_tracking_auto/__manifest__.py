# -*- coding: utf-8 -*-
{
    "name": "Dropship: Auto-capture Tracking from Supplier Replies (Require Tracking Flag)",
    "version": "18.0.2.0.0",
    "summary": "Adds 'Require Tracking' checkbox on PO; auto-extracts tracking from supplier replies and reminds only flagged POs.",
    "author": "OutsetX",
    "license": "LGPL-3",
    "depends": ["purchase", "stock", "mail", "delivery", "sale"],
    "data": [
        "data/mail_template.xml",
        "data/mail_template_fedex_delivery.xml",
        "data/mail_template_shipped.xml",
        "data/mail_template_delivery_validated.xml",
        "data/mail_template_order_confirmation.xml",
        #"data/mail_template_review_request.xml",
        "data/ir_cron.xml",
        "security/ir.model.access.csv",
        "views/purchase_order_view.xml",
        "views/res_config_settings_view.xml",
        "views/stock_picking_fedex_view.xml",
    ],
    "installable": True,
    "application": False,
}
