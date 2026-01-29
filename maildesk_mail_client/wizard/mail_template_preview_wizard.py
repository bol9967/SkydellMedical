# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import fields, models
from odoo.addons.mail.wizard.mail_template_preview import MailTemplatePreview

class MailTemplatePreview(models.TransientModel):
    _inherit = "mail.template.preview"

    _MAIL_TEMPLATE_FIELDS = MailTemplatePreview._MAIL_TEMPLATE_FIELDS + ["email_bcc"]

    email_bcc = fields.Char(
        "Bcc",
        compute="_compute_mail_template_fields",
    )
