# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import fields, models, _

class MailMessage(models.Model):
    _inherit = "mail.message"

    account_id = fields.Many2one(
        "mailbox.account",
        string="Mail Account",
        index=True,
    )

    recipient_cc_ids = fields.Many2many(
        "res.partner",
        "mail_message_res_partner_cc_rel",
        "mail_message_id",
        "parent_id",
        string="Cc (Partners)",
        context={"active_test": False},
    )

    recipient_bcc_ids = fields.Many2many(
        "res.partner",
        "mail_message_res_partner_bcc_rel",
        "mail_message_id",
        "parent_id",
        string="Bcc (Partners)",
        context={"active_test": False},
    )
