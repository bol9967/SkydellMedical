# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import api, fields, models
from dateutil.relativedelta import relativedelta

class MaildeskEmailState(models.Model):
    _name = "maildesk.email_state"
    _description = "MailDesk Email State"
    _order = "write_date desc"

    account_id = fields.Many2one("mailbox.account", required=True, index=True, ondelete="cascade")
    folder = fields.Char(required=True, index=True)
    uid = fields.Char(required=True, index=True)

    seen = fields.Boolean()
    has_seen = fields.Boolean(default=False, index=True)

    starred = fields.Boolean()
    has_starred = fields.Boolean(default=False, index=True)

    target_folder = fields.Char(index=True)
    has_move = fields.Boolean(default=False, index=True)

    dirty_flags = fields.Boolean(default=False, index=True)
    dirty_move = fields.Boolean(default=False, index=True)

    is_delete = fields.Boolean(default=False, index=True)
    has_delete = fields.Boolean(default=False, index=True)

    expire_at = fields.Datetime(index=True)

    @api.model
    def _feature_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param("maildesk.email_state.enabled", "1") == "1"

    @api.model
    def record_flags(self, account_id, folder, uid, seen=None, starred=None, source="ui"):
        dom = [
            ('account_id', '=', account_id),
            ('folder', '=', folder),
            ('uid', '=', str(uid)),
        ]
        rec = self.search(dom, limit=1)
        vals = {}
        if seen is not None:
            vals['seen'] = bool(seen)
            vals['has_seen'] = True
        if starred is not None:
            vals['starred'] = bool(starred)
            vals['has_starred'] = True
        if not vals:
            return True
        if rec:
            rec.write(vals)
        else:
            vals.update({'account_id': account_id, 'folder': folder, 'uid': str(uid)})
            self.create(vals)
        return True

    @api.model
    def record_delete(self, account_id, folder, uid, source="ui"):
        if not self._feature_enabled():
            return True

        domain = [
            ("account_id", "=", account_id),
            ("folder", "=", folder),
            ("uid", "=", str(uid)),
        ]

        vals = {
            "is_delete": True,
            "has_delete": True,
            "expire_at": fields.Datetime.now() + relativedelta(months=3),
        }

        rec = self.search(domain, limit=1)
        if rec:
            rec.write(vals)
        else:
            vals.update({
                "account_id": account_id,
                "folder": folder,
                "uid": str(uid),
            })
            self.create(vals)

        return True

    @api.model
    def record_move(self, account_id, uid, from_folder, to_folder, source=None):
        if not self._feature_enabled():
            return True

        vals = {
            "target_folder": to_folder,
            "has_move": True,
            "dirty_move": True,
            "expire_at": fields.Datetime.now() + relativedelta(months=3),
        }

        domain = [
            ("account_id", "=", account_id),
            ("folder", "=", from_folder),
            ("uid", "=", str(uid)),
        ]
        rec = self.search(domain, limit=1)
        if rec:
            rec.write(vals)
        else:
            vals.update({"account_id": account_id, "folder": from_folder, "uid": str(uid)})
            self.create(vals)
        return True

    @api.model
    def apply_overrides_to_records(self, account_id, folder, records):
        if not records or not self._feature_enabled():
            return records or []
        folder = folder or "INBOX"
        uids = [str(r.get("uid") if r.get("uid") is not None else r.get("id")) for r in records]
        rows = self.search([
            ("account_id", "=", account_id),
            ("uid", "in", uids),
        ])
        by_uid = {r.uid: r for r in rows}
        for r in records:
            k = str(r.get("uid") if r.get("uid") is not None else r.get("id"))
            st = by_uid.get(k)
            if not st:
                continue
            if st.has_seen:
                r["is_read"] = bool(st.seen)
            if st.has_starred:
                r["is_starred"] = bool(st.starred)
            if st.has_move and st.target_folder:
                r["pending_move_to"] = st.target_folder
            if st.has_delete and st.is_delete:
                r["pending_delete"] = True
        return records

    @api.model
    def cron_gc_states(self, batch=2000):
        now = fields.Datetime.now()
        stale = self.search([("expire_at", "!=", False), ("expire_at", "<", now)], limit=batch)
        if stale:
            stale.unlink()
        return True
    