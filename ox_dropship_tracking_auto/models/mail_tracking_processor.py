# -*- coding: utf-8 -*-
import re
import logging
from odoo import api, fields, models, tools, _

_logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Regex patterns for Purchase Order and Tracking Number
# --------------------------------------------------------------
PO_REGEX = re.compile(r"\bPO\s*(?:No|#|Number)?[:\-]?\s*([A-Z]*\d+)", re.I)
TRACK_REGEX = re.compile(r"\bTracking\s*(?:No|#|Number)?[:\-]?\s*([A-Z0-9\-]{4,})", re.I)


class MailTrackingProcessor(models.Model):
    """Handle all supplier emails sent to purchase@..."""
    _name = "mail.tracking.processor"
    _description = "Incoming Tracking Email Processor"
    _inherit = ["mail.thread"]

    active = fields.Boolean(default=True)

    # --------------------------------------------------------------
    # Handle new incoming email
    # --------------------------------------------------------------
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Triggered when a supplier sends an email to purchase@"""
        plain = tools.html2plaintext(msg_dict.get("body", "")) or ""
        email_from = msg_dict.get("email_from")
        subject = msg_dict.get("subject")

        _logger.info("📧 Incoming tracking email from %s | Subject: %s", email_from, subject)

        po_name = self._extract_po_number(plain)
        tracking = self._extract_tracking(plain)

        if not po_name:
            _logger.info("📭 No PO number found in email from %s", email_from)
            return super().message_new(msg_dict, custom_values)

        po = self.env["purchase.order"].sudo().search([("name", "=", po_name)], limit=1)
        if not po:
            _logger.warning("❌ No Purchase Order found for %s (email from %s)", po_name, email_from)
            return super().message_new(msg_dict, custom_values)

        if tracking:
            po._apply_tracking(tracking, msg_dict)
            _logger.info("✅ Tracking %s applied to PO %s from %s", tracking, po_name, email_from)

            # Optional: Auto reply to confirm receipt
            self._send_acknowledgement(email_from, po_name, tracking)

        else:
            _logger.info("📨 PO %s found but no tracking detected from %s", po_name, email_from)
            po.message_post(
                body=_("📭 Supplier replied but no tracking number detected."),
                message_type="comment",
            )

        return po

    # --------------------------------------------------------------
    # Acknowledgement auto-reply (optional)
    # --------------------------------------------------------------
    def _send_acknowledgement(self, email_to, po_name, tracking):
        """Send polite confirmation back to supplier."""
        mail_values = {
            "subject": _("Tracking Received for %s") % po_name,
            "body_html": _(
                """
                <p>Dear Supplier,</p>
                <p>Thank you for sharing the tracking details.</p>
                <p><strong>PO:</strong> %s<br/>
                   <strong>Tracking Number:</strong> %s</p>
                <p>Your update has been recorded successfully in our system.</p>
                <p>Best regards,<br/>Purchasing Team</p>
                """
            ) % (po_name, tracking),
            "email_to": email_to,
            "email_from": self.env.user.company_id.email or self.env.user.email_formatted,
        }
        mail = self.env["mail.mail"].sudo().create(mail_values)
        mail.send()
        _logger.info("📤 Acknowledgement email sent to %s for PO %s", email_to, po_name)

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    @staticmethod
    def _extract_po_number(text):
        """Find PO number in plain email text"""
        match = PO_REGEX.search(text or "")
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_tracking(text):
        """Find tracking number in plain email text"""
        match = TRACK_REGEX.search(text or "")
        return match.group(1).strip() if match else None
