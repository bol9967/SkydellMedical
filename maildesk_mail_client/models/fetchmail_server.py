# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import api, models

class FetchmailServer(models.Model):
    _inherit = "fetchmail.server"

    def _maildesk_used_server_ids(self):
        Account = self.env["mailbox.account"].with_context(active_test=False).sudo()
        return Account.search([]).mapped("mail_server_id").ids

    def fetch_mail(self):
        used_ids = set(self._maildesk_used_server_ids())
        servers = self.filtered(lambda s: s.id not in used_ids)
        if not servers:
            return True
        return super(FetchmailServer, servers).fetch_mail()

    @api.model
    def _fetch_mails(self, **kw):
        assert self.env.context.get('cron_id') == self.env.ref('mail.ir_cron_mail_gateway_action').id
        base_domain = [('state', '=', 'done'), ('server_type', '!=', 'local')]
        used_ids = set(self._maildesk_used_server_ids())
        to_fetch = self.search(base_domain).filtered(lambda s: s.id not in used_ids)
        to_fetch.fetch_mail(**kw)
        if not self.search_count(base_domain):
            self.env['ir.cron']._commit_progress(deactivate=True)

