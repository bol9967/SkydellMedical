# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import _, api, fields, models

class ResPartner(models.Model):
    _inherit = "res.partner"

    trusted_partner = fields.Boolean(default=False)
    trusted_by_user_id = fields.Many2one("res.users")
    
    @api.model
    def count_partners_with_email_activity(self, domain=None):
        return self.search_count(
            [("email", "!=", False)] + (domain or [])
        )
    
    @api.model
    def get_partners_with_email_activity(self, domain=None, offset=0, limit=20):
        partners = self.search(
            [("email", "!=", False)] + (domain or []),
            offset=offset,
            limit=limit,
        )
        return partners.read(
            ["id", "name", "email", "company_name", "category_id"]
        )

    def email_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "maildesk_mail_client.maildesk",
            "name": _("Sent Emails"),
            "params": {
                "email_from": (self.email or "").lower(),
                "partner_id": self.id,
                "partner_name": self.name,
            },
        }