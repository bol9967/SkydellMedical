# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


{
    "name": "Email Client & Unified Inbox for Odoo – Maildesk Basic",
    "version": "18.0.2.0.6",
    "summary": "Odoo unified inbox & email client for Gmail/Google Workspace, Outlook/Microsoft 365 (Exchange Online), and IMAP (OAuth2, IMAP IDLE real-time sync). Tags, threading, shared inbox, partner linking – full email management in Odoo.",
    "description": """
        Maildesk Basic – Unified Email Client for Odoo

        Maildesk Basic is a fast and reliable email client fully integrated into Odoo.
        It supports Gmail, Outlook, Mailcow and nearly all modern IMAP servers, with real-time one-way synchronization of incoming messages.

        Key Features:
        - Unified inbox for multiple mail accounts (Gmail, Outlook, IMAP)
        - Real-time one-way sync (IMAP IDLE): all emails from server appear in Odoo
        - Full HTML email composer with drag, resize, and attachments
        - Threaded message view (conversation mode)
        - Draft autosave and restore
        - Folder management (Inbox, Sent, Archive, Trash)
        - Actions: reply, forward, archive, delete (local)
        - Manual tagging system for organizing messages
        - Partner (contact) detection and linking
        - Clean OWL-based user interface

        Designed to centralize communication and replace external email clients – fully inside Odoo.

        Compatible with:
        - Gmail (OAuth2)
        - Microsoft Outlook / Office365 (OAuth2)
        - Mailcow, Zimbra, Dovecot, cPanel and most modern IMAP servers

        Developed and supported by Metzler IT GmbH – Odoo Experts from Germany.
    """,
    "live_test_url": "https://mit-odoo.com/module/maildesk",
    "author": "Metzler IT GmbH",
    "website": "https://mit-odoo.com/module/maildesk",
    "license": "OPL-1",
    "category": "Productivity",
    "depends": ["web", "contacts", "mail", "microsoft_outlook", "google_gmail"],
    "external_dependencies": {
        "python": [
            "imapclient",
            "aioimaplib",
            "google-api-python-client",
            "google-auth",
            "google-auth-httplib2",
            "msal",
        ],
    },
    'images': [
        'static/description/banner.gif',
    ],
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "wizard/mailbox_account_wizard.xml",
        "wizard/mail_compose_message_wizard.xml",
        "wizard/mail_template_preview_wizard.xml",
        "views/mail_mail_views.xml",
        "views/mail_message_tag.xml",
        "views/mail_message_views.xml",
        "views/mailbox_account_views.xml",
        "views/message_cache_views.xml",
        "views/res_partner_views.xml",
        "views/menus_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "web/static/lib/jquery/jquery.js",
            "maildesk_mail_client/static/src/scss/*.scss",
            "maildesk_mail_client/static/src/js/maildesk.esm.js",
            "maildesk_mail_client/static/src/js/compose_mail.esm.js",
            "maildesk_mail_client/static/src/js/compose_systray.esm.js",
            "maildesk_mail_client/static/src/js/assign_tags_dialog.esm.js",
            "maildesk_mail_client/static/src/js/contact_picker_dialog.esm.js",
            "maildesk_mail_client/static/src/js/move_to_folder_dialog.esm.js",
            "maildesk_mail_client/static/src/js/email_input_field.esm.js",
            "maildesk_mail_client/static/src/js/partner_card_popover.esm.js",
            "maildesk_mail_client/static/src/js/maildesk_notifications.esm.js",
            "maildesk_mail_client/static/src/xml/maildesk.xml",
            "maildesk_mail_client/static/src/xml/compose_mail.xml",
            "maildesk_mail_client/static/src/xml/compose_systray.xml",
            "maildesk_mail_client/static/src/xml/assign_tags_dialog.xml",
            "maildesk_mail_client/static/src/xml/contact_picker_dialog.xml",
            "maildesk_mail_client/static/src/xml/move_to_folder_dialog.xml",
            "maildesk_mail_client/static/src/xml/email_input_field.xml",
            "maildesk_mail_client/static/src/xml/partner_card_popover.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "price": 249.00,
    "currency": "EUR",
    "sequence": 1,
}
