import logging
from odoo import models

_logger = logging.getLogger(__name__)

class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        res = super().action_post()

        for payment in self:
            payment.flush_recordset()
            if payment.state in ("posted", "paid"):
                try:
                    mail_values = {
                        "subject": f"New Payment Registered: {payment.name or ''}",
                        "body_html": f"""
                            <p>Hello,</p>
                            <p>A new payment has been registered in Odoo.</p>
                            <ul>
                                <li><b>Payment Number:</b> {payment.name or ''}</li>
                                <li><b>Partner:</b> {payment.partner_id.name or ''}</li>
                                <li><b>Journal:</b> {payment.journal_id.name or ''}</li>
                                <li><b>Payment Method:</b> {payment.payment_method_line_id.name or ''}</li>
                                <li><b>Amount:</b> {payment.amount} {payment.currency_id.symbol or ''}</li>
                                <li><b>Payment Date:</b> {payment.date or ''}</li>
                                <li><b>Memo:</b> {payment.memo or ''}</li>
                                <li><b>Registered By:</b> {payment.create_uid.name or ''}</li>
                            </ul>
                            <p>Regards,<br/>Your Odoo System</p>
                        """,
                        "email_to": "info@skydellmedical.com",
                        "email_from": self.env.user.company_id.email
                            or self.env.user.email
                            or "noreply@example.com",
                        "auto_delete": True,
                    }

                    mail = self.env["mail.mail"].create(mail_values)
                    mail.send()

                    _logger.info(">>> Payment Notify: Email sent for %s", payment.name)

                except Exception as e:
                    _logger.warning(">>> Payment Notify WARNING for %s: %s", payment.name, str(e))
            else:
                _logger.info(">>> Payment Notify: Skipped for %s (state=%s)", payment.name, payment.state)

        return res
