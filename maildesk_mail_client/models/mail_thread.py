# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import models
from .mail_mail import format_emails

import logging
_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _get_message_create_valid_field_names(self):
        field_names = super()._get_message_create_valid_field_names()
        field_names.update(
            {
                "body_original",
                "account_id",
                "recipient_cc_ids",
                "recipient_bcc_ids",
                "folder_ids",
            }
        )
        return field_names

    def _notify_by_email_get_base_mail_values(self, message, additional_values=None):
        res = super()._notify_by_email_get_base_mail_values(
            message, additional_values=additional_values
        )
        context = self.env.context

        if not context.get("skip_cc_bcc"):
            res["email_cc"] = format_emails(context.get("partner_cc_ids", []))
            res["email_bcc"] = format_emails(context.get("partner_bcc_ids", []))

        return res

    def _notify_get_recipients(self, message, msg_vals, **kwargs):
        rdata = super()._notify_get_recipients(message, msg_vals, **kwargs)
        context = self.env.context
        if not context.get("is_from_composer") or context.get("skip_cc_bcc"):
            return rdata

        partners_cc_bcc = [
            p.id
            for p in (
                context.get("partner_cc_ids", []) + context.get("partner_bcc_ids", [])
            )
        ]

        recipients_cc_bcc = self.env["mail.followers"]._get_recipient_data(
            None,
            message.message_type,
            msg_vals.get("subtype_id", message.subtype_id.id),
            partners_cc_bcc,
        )

        partners_already_marked_as_recipient = {r.get("id", False) for r in rdata}

        for value in recipients_cc_bcc.values():
            for data in value.values():
                if data.get("id") not in partners_already_marked_as_recipient:
                    partner = self.env["res.partner"].browse(data.get("id"))
                    pdata = {
                        "id": partner.id,
                        "name": partner.name,
                        "email": partner.email,
                        "email_normalized": partner.email_normalized,
                        "active": partner.active,
                        'share': partner.partner_share,
                        "notif": data.get("notif", "email"),
                        "type": "customer",
                        "is_follower": data.get("is_follower"),
                        "uid": partner.user_ids[:1].id or False,
                        "lang": partner.lang,
                    }
                    rdata.append(pdata)

        return rdata

    def _notify_get_recipients_classify(
        self, message, recipients_data, model_description, msg_vals=None
    ):
        res = super()._notify_get_recipients_classify(
            message, recipients_data, model_description, msg_vals=msg_vals
        )
        context = self.env.context
        if not context.get("is_from_composer") or context.get("skip_cc_bcc"):
            return res

        # Only apply Maildesk-specific recipient grouping when actually sending from Maildesk composer
        # Do NOT interfere with business documents (Sale Orders, Invoices, etc.) that need portal access
        # Check if this is from a business document model that requires portal access
        if self._name in ('sale.order', 'account.move', 'purchase.order', 'project.task', 'helpdesk.ticket'):
            # Preserve original recipient classification with portal access for business documents
            return res

        ids = []
        customer_data = None

        for rcpt_data in res:
            if rcpt_data["notification_group_name"] == "customer":
                customer_data = rcpt_data
            else:
                ids += rcpt_data.get("recipients", [])

        if customer_data:
            customer_data["recipients"].extend(ids)
        else:
            customer_data = {
                "notification_group_name": "customer",
                "active": True,
                "has_button_access": False,
                "button_access": {},
                "recipients": ids,
            }

        return [customer_data]

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        allowed_keys = {"scheduled_date"}
        safe_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}

        if message.message_type == "notification":
            self = self.with_context(skip_cc_bcc=True)

        if self.env.context.get('maildesk_synced_message'):
            recipients = self._notify_get_recipients(message, msg_vals, **safe_kwargs)
            if not recipients:
                return recipients
            self._notify_thread_by_inbox(message, recipients, msg_vals=msg_vals, **safe_kwargs)
            self._notify_thread_by_web_push(message, recipients, msg_vals, **safe_kwargs)
            return recipients

        return super()._notify_thread(message, msg_vals=msg_vals, **safe_kwargs)

    def _notify_thread_by_email(self, message, recipients_data, msg_vals=False, **kwargs):
        if self.env.context.get("maildesk_skip_email_send"):
            _logger.info("Skipping mail.mail creation for message %s", message.id)
            return True

        skip_existing = bool(self.env.context.get('maildesk_skip_existing', False)) or bool(kwargs.get('skip_existing'))
        if skip_existing and recipients_data:
            email_partner_ids = [r['id'] for r in recipients_data if r.get('notif') == 'email']
            if email_partner_ids:
                existing = self.env['mail.notification'].sudo().search([
                    ('mail_message_id', '=', message.id),
                    ('notification_type', '=', 'email'),
                    ('res_partner_id', 'in', email_partner_ids),
                ])
                already = set(existing.mapped('res_partner_id').ids)
                recipients_data = [r for r in recipients_data if not (r.get('notif') == 'email' and r['id'] in already)]

        return super()._notify_thread_by_email(message, recipients_data, msg_vals=msg_vals, **kwargs)
