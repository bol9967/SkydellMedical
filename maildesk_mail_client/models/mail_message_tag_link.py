# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import models, fields

class MailMessageTagLink(models.Model):
    _name = "mail.message.tag.link"
    _description = "Message Tag link"

    account_id = fields.Many2one("mailbox.account", required=True, index=True, ondelete="cascade")
    message_id = fields.Char(required=True, index=True)
    tag_id = fields.Many2one("mail.message.tag", required=True, ondelete="cascade")
    color = fields.Char(
        related='tag_id.color',
    )