# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import models, fields
from odoo.tools.mail import email_split_and_format_normalize
from odoo.addons.base.models.ir_mail_server import extract_rfc2822_addresses

import logging
_logger = logging.getLogger(__name__)

def format_emails(partners):
    if not partners:
        return False
    emails = [p.email.strip() for p in partners if p.email]
    normalized = email_split_and_format_normalize(", ".join(emails))
    return ", ".join(normalized) if normalized else False

class MailMail(models.Model):
    _inherit = "mail.mail"

    email_bcc = fields.Char("Bcc", help="Blind copy recipients")

    account_id = fields.Many2one(
        "mailbox.account",
        related="mail_message_id.account_id",
        store=True,
        readonly=True,
    )

    recipient_cc_ids = fields.Many2many(
        related="mail_message_id.recipient_cc_ids",
        string="Cc (Partners)",
    )

    recipient_bcc_ids = fields.Many2many(
        related="mail_message_id.recipient_bcc_ids",
        string="Bcc (Partners)",
    )

    def _prepare_outgoing_list(self, mail_server=False, recipients_follower_status=None):
        res = super()._prepare_outgoing_list(
            mail_server=mail_server, recipients_follower_status=recipients_follower_status
        )

        if len(self.ids) > 1 or not self.env.context.get("is_from_composer"):
            return res

        self.recipient_ids -= (self.recipient_cc_ids + self.recipient_bcc_ids)

        email_bcc_str = format_emails(self.recipient_bcc_ids)
        email_bcc_list = {r.email.lower() for r in self.recipient_bcc_ids if r.email}

        for m in res:
            rcpt_to = None
            if m.get("email_to"):
                rcpt_to = extract_rfc2822_addresses(m["email_to"][0])[0]
            elif m.get("email_cc"):
                rcpt_to = extract_rfc2822_addresses(m["email_cc"][0])[0]

            if rcpt_to and rcpt_to.lower() in email_bcc_list:
                m.setdefault("headers", {}).update({"X-Odoo-Bcc": email_bcc_str or ""})

            if email_bcc_str:
                m["email_bcc"] = [email_bcc_str]

        return res

    def _postprocess_sent_message(self, success_pids, failure_reason=False, failure_type=None):
        self._maildesk_append_to_imap_sent()
        return super()._postprocess_sent_message(success_pids, failure_reason=failure_reason, failure_type=failure_type)

    def _maildesk_append_to_imap_sent(self):
        MailboxSync = self.env["mailbox.sync"].sudo()
        IrMailServer = self.env["ir.mail_server"].sudo()
        Account = self.env["mailbox.account"].sudo()

        for mail in self:
            if mail.state != "sent":
                continue

            account = mail.account_id
            if not account:
                email_from = (mail.email_from or "").strip()
                addr = extract_rfc2822_addresses(email_from) if email_from else []
                if addr:
                    account = Account.search([("email", "=ilike", addr[0])], limit=1)

            if not account:
                continue

            try:
                if not MailboxSync._need_manual_sent_append(account):
                    continue
            except Exception:
                _logger.exception("[MailDesk] _need_manual_sent_append failed for mail %s", mail.id)
                continue

            try:
                email_list = mail._prepare_outgoing_list(mail_server=mail.mail_server_id)
            except Exception:
                _logger.exception("[MailDesk] _prepare_outgoing_list failed for mail %s", mail.id)
                continue

            if not email_list:
                continue

            email = email_list[0]

            try:
                msg = IrMailServer._build_email__(
                    email_from=mail.email_from,
                    email_to=email["email_to"],
                    subject=email["subject"],
                    body=email["body"],
                    body_alternative=email["body_alternative"],
                    email_cc=email["email_cc"],
                    email_bcc=email.get("email_bcc"),
                    reply_to=email["reply_to"],
                    attachments=email["attachments"],
                    message_id=email["message_id"],
                    references=email["references"],
                    object_id=email["object_id"],
                    subtype="html",
                    subtype_alternative="plain",
                    headers=email["headers"],
                )
            except Exception:
                _logger.exception("[MailDesk] _build_email__ failed for %s", mail.id)
                continue

            try:
                MailboxSync._imap_append_to_sent(account, msg)
            except Exception:
                _logger.exception("[MailDesk] Failed append mail %s to Sent", mail.id)


