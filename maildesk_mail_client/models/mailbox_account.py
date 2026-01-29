# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

class MailboxAccount(models.Model):
    _name = "mailbox.account"
    _description = "Mailbox Account"
    _rec_name = "name"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(string="Account Name", required=True, translate=True)
    sender_name = fields.Char(
        string="Sender Name",
        help="Name that will appear as sender when sending emails."
    )
    email = fields.Char(string="Email Address", required=True, index=True)
    password = fields.Char(string="Share Password")
    block_tracking_urls = fields.Boolean("Block Tracking URLs", default=False)

    mail_server_id = fields.Many2one("fetchmail.server", string="Incoming Mail Server",
    copy=False)
    mail_send_server_id = fields.Many2one(
        "ir.mail_server", string="Outgoing SMTP Server",
    copy=False
    )
    last_smtp_check = fields.Datetime(string="Last SMTP Capability Check")
    outlook_delta_link = fields.Char(string="Outlook DeltaLink")

    max_email_size = fields.Float(
        string="Max Email Size (MB)",
        related="mail_send_server_id.max_email_size",
        readonly=False, 
    )

    imap_caps = fields.Json(string="IMAP caps cache", default=dict)
    server_kind = fields.Selection([
        ("gmail", "Gmail / Google Workspace"),
        ("outlook", "Outlook / Microsoft 365"),
        ("dovecot", "Dovecot/Mailcow-like"),
        ("other", "Other/Unknown"),
    ], default="other")
    gmail_last_history_id = fields.Char(index=True, help="Gmail History API anchor (startHistoryId)")
    outlook_delta_tokens = fields.Json(string="Outlook Delta Tokens", default=dict)

    signature = fields.Html(sanitize=False)
    folder_ids = fields.One2many("mailbox.folder", "account_id", string="Folders")

    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        required=True,
        default=lambda self: self.env.user,
    )
    is_shared = fields.Boolean(string="Shared Mailbox", default=False)
    access_user_ids = fields.Many2many(
        "res.users",
        "mailbox_account_user_rel",
        "account_id",
        "user_id",
        string="Users with Access",
    )
    attach_mail_server_id = fields.Boolean(
        related="mail_server_id.attach",
        string="Keep Attachments",
        help="If enabled, attachments will be downloaded and stored in Odoo. "
        "If disabled, attachments will remain on the mail server and will be fetched "
        "on demand when the email is viewed.",
        default=True,
        readonly=False,
    )
    show_recommendation = fields.Boolean(
        string="Show Email Hosting Recommendation",
        default=True,
        help="Whether to show the Metzler IT email hosting recommendation block.",
    )

    @api.constrains("mail_server_id", "mail_send_server_id")
    def _check_unique_servers(self):
        for rec in self:
            if rec.mail_server_id:
                others = self.search([
                    ("id", "!=", rec.id),
                    ("mail_server_id", "=", rec.mail_server_id.id)
                ])
                if others:
                    raise ValidationError(
                        _("Incoming mail server %s is already linked to another mailbox account.") % rec.mail_server_id.display_name
                    )
            if rec.mail_send_server_id:
                others = self.search([
                    ("id", "!=", rec.id),
                    ("mail_send_server_id", "=", rec.mail_send_server_id.id)
                ])
                if others:
                    raise ValidationError(
                        _("Outgoing mail server %s is already linked to another mailbox account.") % rec.mail_send_server_id.display_name
                    )
    
    def button_test_incoming(self):
        if not self.mail_server_id:
            raise ValidationError(
                _(
                    "No incoming mail server configured. Please configure it in the server settings."
                )
            )
        self.mail_server_id.button_confirm_login()
        self.refresh_imap_caps(force=True, update_kind=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Connection Test Successful!"),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def button_test_outgoing(self):
        if not self.mail_send_server_id:
            raise ValidationError(
                _("No outgoing SMTP server configured. Please configure it in the server settings.")
            )
        self.mail_send_server_id.test_smtp_connection()
        self.refresh_imap_caps(force=False, update_kind=False)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Connection Test Successful!"),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.constrains("email")
    def _check_email_format(self):
        for record in self:
            if record.email and "@" not in record.email:
                raise ValidationError(_("Invalid email address format."))

    def get_smtp_server(self):
        self.ensure_one()
        return self.mail_send_server_id

    def get_imap_server(self):
        self.ensure_one()
        return self.mail_server_id

    def sync_imap_folders(self):
        Folder = self.env["mailbox.folder"]
        for account in self:
            Folder.sync_folders_for_account(account)

    def _caps_normalize(self, caps):
        if not caps:
            return []
        return sorted({(c.decode() if isinstance(c, bytes) else c).upper() for c in caps})

    def _guess_kind(self, host, email, tokens):
        h = (host or "").lower()
        d = (email.split("@")[1].lower() if email and "@" in email else "")
        t = set((c.decode() if isinstance(c, bytes) else c).upper() for c in (tokens or []))

        if "X-GM-EXT-1" in t or "google" in h or d in ("gmail.com", "googlemail.com"):
            return "gmail"

        if (
            any(x in h for x in ("outlook", "office365", "hotmail", "live", "prod.outlook.com")) or
            d.endswith((".onmicrosoft.com", ".office365.com", ".outlook.com")) or
            "MICROSOFT" in t
        ):
            return "outlook"

        if any(x in t for x in ("SPECIAL-USE", "UIDPLUS", "IDLE", "DOVECOT", "MAILCOW")):
            return "dovecot"

        return "other"

    def refresh_imap_caps(self, force=False, update_kind=True, ttl_hours=24):
        for acc in self:
            data = acc.imap_caps or {}
            checked = data.get("checked")
            fresh = False
            if checked:
                try:
                    fresh = fields.Datetime.from_string(checked) > fields.Datetime.now() - relativedelta(hours=ttl_hours)
                except Exception:
                    pass
            if fresh and not force:
                continue
            cli = acc._get_imap_client()
            tokens = []
            try:
                tokens = acc._caps_normalize(cli.capabilities())
            finally:
                try:
                    cli.logout()
                except Exception:
                    pass
            acc.sudo().write({
                "imap_caps": {"checked": fields.Datetime.now().isoformat(), "tokens": tokens},
            })
            if update_kind and (force or acc.server_kind == "other"):
                host = acc.mail_server_id.server if acc.mail_server_id else ""
                kind = acc._guess_kind(host, acc.email, tokens)
                if kind and kind != acc.server_kind:
                    acc.sudo().write({"server_kind": kind})

    def get_imap_caps(self, ttl_hours=24):
        self.ensure_one()
        data = self.imap_caps or {}
        checked = data.get("checked")
        fresh = False
        if checked:
            try:
                fresh = fields.Datetime.from_string(checked) > fields.Datetime.now() - relativedelta(hours=ttl_hours)
            except Exception:
                pass
        if not fresh:
            self.refresh_imap_caps(force=True, update_kind=False)
            data = self.imap_caps or {}
        return set(self._caps_normalize(data.get("tokens")))

    @api.onchange("mail_server_id", "email")
    def _onchange_guess_server_kind(self):
        for rec in self:
            if rec.server_kind != "other":
                continue

            if rec.mail_server_id and rec.mail_server_id.server_type == "outlook":
                rec.server_kind = "outlook"
                continue

            host = rec.mail_server_id.server if rec.mail_server_id else ""
            kind = rec._guess_kind(host, rec.email, [])
            if kind != "other":
                rec.server_kind = kind

    def _get_imap_client(self):
        return self.env["mailbox.sync"]._get_imap_client(self)
    
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records_with_server = records.filtered("mail_server_id")
        for record in records_with_server:
            record.refresh_imap_caps(force=True, update_kind=True)
        return records
    