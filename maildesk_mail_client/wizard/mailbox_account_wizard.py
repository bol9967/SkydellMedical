# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import _, fields, models
from odoo.exceptions import UserError

class MailboxAccountWizard(models.TransientModel):
    _name = "mailbox.account.wizard"
    _description = "Connect to Existing Mailbox Wizard"

    email = fields.Char("Email Address", required=True)
    password = fields.Char("Password", required=True)

    def action_connect_mailbox(self):
        account = (
            self.env["mailbox.account"]
            .sudo()
            .search(
                [
                    ("email", "=", self.email.strip()),
                    ("is_shared", "=", True),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )
        if not account:
            raise UserError(_("No shared mailbox found with this email."))
        if (
            self.env.user in account.access_user_ids
        ):
            raise UserError(_("You already have access to this mailbox."))

        if account.password != self.password:
            raise UserError(_("Incorrect password."))

        account.sudo().write(
            {
                "access_user_ids": [(4, self.env.user.id)],
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
