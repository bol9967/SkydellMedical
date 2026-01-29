# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import fields, models, _

class MaildeskDraft(models.Model):
    _name = "maildesk.draft"
    _description = "MailDesk Draft"
    _order = "write_date desc, id desc"
    _rec_name = "subject"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        required=True,
        index=True,
    )

    account_id = fields.Many2one(
        "mailbox.account",
        string="Mailbox Account",
        required=True,
        ondelete="cascade",
        index=True,
    )

    subject = fields.Char(string="Subject")
    body_html = fields.Html(string="Body", sanitize=False)

    to_emails = fields.Text(string="To")
    cc_emails = fields.Text(string="Cc")
    bcc_emails = fields.Text(string="Bcc")

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "maildesk_draft_attachment_rel",
        "draft_id",
        "attachment_id",
        string="Attachments",
    )

    reply_to_message_id = fields.Char(
        string="Reply-to Message-ID",
        index=True,
        help="Original Message-ID header of the email being replied to.",
    )

    reply_to_cache_uid = fields.Char(
        string="Reply-to UID",
        help="Maildesk cache UID / external UID of original message.",
    )

    model = fields.Char(string="Related Document Model")
    res_id = fields.Integer(string="Related Document ID")
    sender_display_name = fields.Char(string="From Display Name")

    request_read_receipt = fields.Boolean(string="Request Read Receipt")
    request_delivery_receipt = fields.Boolean(string="Request Delivery Receipt")

    message_id = fields.Char(string="Message-ID", index=True)
