# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import api, fields, models
from .mailbox_sync import get_pool, memcache_del_keys
from dateutil.relativedelta import relativedelta
import re
import base64
from odoo.exceptions import UserError
from email import message_from_bytes, policy
from psycopg2 import errors as pg_errors
from psycopg2.errors import SerializationFailure, UniqueViolation, LockNotAvailable
import time

import logging
_logger = logging.getLogger(__name__)

LOCK_KEY = 'maildesk_cache_lock'

class MaildeskMessageCache(models.Model):
    _name = "maildesk.message_cache"
    _inherit = ['mail.thread']
    _description = "MailDesk: Message Metadata Cache"
    _rec_name = "subject"
    _order = "date desc, id desc"

    account_id = fields.Many2one("mailbox.account", required=True, index=True, ondelete="cascade")
    folder = fields.Char(required=True, index=True)
    uid = fields.Char(required=True, index=True)

    message_id = fields.Char(index=True)
    subject = fields.Char(index=True)
    from_addr = fields.Char(index=True)
    to_addrs = fields.Text()
    cc_addrs = fields.Text()
    bcc_addrs = fields.Text()
    date = fields.Datetime(index=True)
    flags = fields.Char()
    has_attachments = fields.Boolean(default=False)
    size = fields.Integer()
    preview = fields.Text()
    sender_display_name = fields.Char(index=True)
    avatar_html = fields.Html()

    in_reply_to = fields.Char()
    references_hdr = fields.Text()
    thread_id = fields.Char(index=True)

    thread_root_id = fields.Char(index=True)
    parent_uid = fields.Integer()
    parent_folder = fields.Char()
    thread_complete = fields.Boolean(default=False)

    cache_until = fields.Datetime(index=True, default=lambda self: fields.Datetime.now() + relativedelta(hours=1))

    body_cached = fields.Boolean(default=False)
    body_html = fields.Text()
    body_text = fields.Text()
    body_cache_until = fields.Datetime(index=True)

    process_state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], default='pending', index=True)

    process_error = fields.Text()
    processed_at = fields.Datetime(index=True)
    processed_model = fields.Char()
    processed_res_id = fields.Integer()
    retry_count = fields.Integer(default=0, index=True)
    next_try_at = fields.Datetime(index=True)

    raw_attachment_id = fields.Many2one('ir.attachment', readonly=True)

    def to_record_dict(self):
        self.ensure_one()

        email_from = (self.from_addr or "").lower()
        partner = False
        if email_from:
            partner = self.env["res.partner"].search([("email", "=ilike", email_from)], limit=1)

        sender_display = (
            self.sender_display_name
            or (partner.name if partner else False)
            or email_from
        )

        formatted_date = ""
        if self.date:
            try:
                dt_ctx = fields.Datetime.context_timestamp(self, self.date)
                formatted_date = dt_ctx.strftime("%d %b %Y %H:%M")
            except Exception:
                formatted_date = ""

        to_display = self.to_addrs or ""
        cc_display = self.cc_addrs or ""

        f = self.flags or ""
        is_read = ("\\seen" in f.lower())
        is_starred = ("\\flagged" in f.lower())
        is_draft = ("\\draft" in f.lower())

        preview = self.preview or (self.subject or "")[:120]

        avatar_html = (
            self.avatar_html
            or self.env["mailbox.sync"]._avatar_html(email_from, partner)
        )

        record = {
            "id": str(self.uid or "0"),
            "uid": str(self.uid or ""),

            "account_id": [self.account_id.id, self.account_id.name],
            "folder_id": False,
            "folder": self.folder,
            "folder_name": self.folder,

            "subject": self.subject or "(no subject)",
            "email_from": email_from,
            "sender_display_name": sender_display,

            "date": self.date or False,
            "formatted_date": formatted_date,

            "is_read": is_read,
            "is_starred": is_starred,
            "is_draft": is_draft,
            "has_attachments": bool(self.has_attachments),

            "preview_text": preview,

            "to_display": to_display,
            "cc_display": cc_display,

            "avatar_html": avatar_html,
            "avatar_partner_id": partner.id if partner else False,

            "tag_ids": [],

            "message_id_norm": self.message_id or "",
        }

        parent_key = self.in_reply_to or ""
        if not parent_key and self.references_hdr:
            refs = self.references_hdr.split()
            if refs:
                parent_key = refs[0]

        if parent_key:
            record["parent_id"] = False

        return record

    def _lock_acquire(self):
        try:
            self.env.cr.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        except Exception:
            self.env.cr.rollback()
            self.env.cr.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        return bool(self.env.cr.fetchone()[0])

    def _lock_release(self):
        try:
            self.env.cr.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
        except Exception:
            self.env.cr.rollback()
            self.env.cr.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))

    def _retry_serialized(self, fn, tries=3, pause=0.2):
        for _ in range(int(tries)):
            try:
                with self.env.cr.savepoint():
                    return fn()
            except pg_errors.SerializationFailure:
                time.sleep(pause)
        return None
    
    def touch_cache_ttl(self, minutes=60):
        self._safe_write({"cache_until": fields.Datetime.now() + relativedelta(minutes=minutes)})

    def set_body_cache(self, html=None, text=None, minutes=15):
        vals = {
            "body_cached": True,
            "body_cache_until": fields.Datetime.now() + relativedelta(minutes=minutes),
        }
        if html is not None:
            vals["body_html"] = html
        if text is not None:
            vals["body_text"] = text
        self._safe_write(vals)

    @api.model
    def upsert_meta(self, account_id, folder, uid, vals, ttl_minutes=60):
        self = self.sudo()

        vals = dict(vals or {})
        vals.update({
            "account_id": account_id,
            "folder": folder,
            "uid": str(uid),
            "cache_until": fields.Datetime.now() + relativedelta(
                minutes=int(ttl_minutes or 60)
            ),
        })

        domain = [
            ("account_id", "=", account_id),
            ("folder", "=", folder),
            ("uid", "=", str(uid)),
        ]

        try:
            rec = self.search(domain, limit=1)
            if rec and rec.exists():
                try:
                    rec._safe_write(vals)
                    return rec
                except (SerializationFailure, LockNotAvailable) as e:
                    _logger.debug(
                        "upsert_meta: skip write due to concurrency (account=%s folder=%s uid=%s id=%s): %s",
                        account_id, folder, uid, rec.id, e,
                    )
                    self.env.cr.rollback()
                    return rec
                except Exception as e:
                    _logger.warning(
                        "upsert_meta: write failed (account=%s folder=%s uid=%s id=%s): %s",
                        account_id, folder, uid, rec.id, e,
                    )
                    self.env.cr.rollback()
                    return rec

            try:
                return self.create(vals)
            except UniqueViolation:
                self.env.cr.rollback()
                rec2 = self.search(domain, limit=1)
                if rec2 and rec2.exists():
                    return rec2
                return self.create(vals)
            except (SerializationFailure, LockNotAvailable) as e:
                _logger.debug(
                    "upsert_meta: create concurrency issue (account=%s folder=%s uid=%s): %s",
                    account_id, folder, uid, e,
                )
                self.env.cr.rollback()
                return self.search(domain, limit=1)
            except Exception as e:
                _logger.warning(
                    "upsert_meta: create failed (account=%s folder=%s uid=%s): %s",
                    account_id, folder, uid, e,
                )
                self.env.cr.rollback()
                return self.search(domain, limit=1)

        except Exception as e:
            _logger.warning(
                "upsert_meta: unexpected error (account=%s folder=%s uid=%s): %s",
                account_id, folder, uid, e,
            )
            self.env.cr.rollback()
            return self.search(domain, limit=1)

    @api.model
    def get_cache_map(self, account_id, folder, uids):
        if not uids:
            return {}
        rows = self.search([
            ('account_id', '=', account_id),
            ('folder', '=', folder),
            ('uid', 'in', list({str(u) for u in uids})),
            ('cache_until', '>', fields.Datetime.now()),
        ])
        return {str(r.uid): r for r in rows}

    @api.model
    def cron_warmup(self, per_folder=15):
        per_folder = 15
        if not self._lock_acquire():
            return 0
        try:
            Account = self.env["mailbox.account"].sudo()
            Sync = self.env['mailbox.sync']

            accounts = Account.search([("folder_ids", "!=", False)])
            for acc in accounts:
                folders = acc.folder_ids[:5]
                if not folders:
                    continue

                for f in folders:
                    try:
                        Sync.message_search_load(
                            account_id=acc.id,
                            folder_id=f.id,
                            limit=per_folder,
                        )
                        _logger.debug(
                            "Warmup OK: account %s folder %s (%s)",
                            acc.id, f.id, f.name,
                        )
                        time.sleep(0.1)
                    except Exception as e:
                        _logger.warning(
                            "Failed to warmup account %s folder %s (%s): %s",
                            acc.id, f.id, f.name, e,
                        )
                        continue

            return 1
        finally:
            self._lock_release()

    @api.model
    def cron_gc(self, hard=False, batch=1000):
        if not self._lock_acquire():
            return 0
        try:
            now = fields.Datetime.now()

            def _clear_expired_body():
                expired_body = self.search([
                    ('body_cached', '=', True),
                    ('body_cache_until', '!=', False),
                    ('body_cache_until', '<', now),
                ], limit=int(batch))
                if expired_body:
                    expired_body._safe_write({
                        'body_cached': False,
                        'body_html': False,
                        'body_text': False,
                        'body_cache_until': False,
                    })
                return len(expired_body)

            self._retry_serialized(_clear_expired_body)

            def _delete_stale():
                domain = [('cache_until', '<', now)]
                if not hard:
                    domain.append(('body_cached', '=', False))
                stale = self.search(domain, limit=int(batch))
                if stale:
                    stale.unlink()
                return len(stale)

            self._retry_serialized(_delete_stale)
            return 1
        finally:
            self._lock_release()

    def _prepare_attachments(self):
        self.ensure_one()

        Attachment = self.env["ir.attachment"].sudo()
        atts = Attachment.search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])

        result = []
        for att in atts:
            info = self.env["mailbox.sync"]._attachment_common_info(att.name or "", att.mimetype or "")
            is_viewable = info.get("isViewable")

            item = dict(info)
            item.update({
                "type": "binary",
                "urlRoute": "/web/content",
                "urlQueryParams": {"id": att.id, "download": "false"},
                "defaultSource": f"/web/content/{att.id}" if is_viewable else None,
                "downloadUrl": f"/web/content/{att.id}?download=true",
                "size": att.file_size or 0,
                "id": att.id,
                "content_id": "",
            })
            result.append(item)

        return result
 
    @api.model
    def update_flags_bulk(self, account_id, folder, flags_map):
        if not flags_map:
            return 0
        uids = [str(u) for u in flags_map.keys()]
        rows = self.search([
            ('account_id', '=', account_id),
            ('folder', '=', folder),
            ('uid', 'in', uids),
        ])

        for r in rows:
            cur = r.flags or ""
            cur = re.sub(r'(?<!\S)\\Seen(?!\S)',    '', cur)
            cur = re.sub(r'(?<!\S)\\Flagged(?!\S)', '', cur)
            cur = " ".join(cur.split())
            m = flags_map.get(r.uid) or {}
            if m.get('seen'):
                cur = (cur + " \\Seen").strip()
            if m.get('starred'):
                cur = (cur + " \\Flagged").strip()
            r._safe_write({'flags': cur})

        keys = [f"{account_id}:{folder}:{uid}" for uid in uids]
        memcache_del_keys(keys)
        return len(rows)

    @api.model
    def remove_uids(self, account_id, folder, uids):
        if not uids:
            return 0
        rows = self.search([
            ('account_id', '=', account_id),
            ('folder', '=', folder),
            ('uid', 'in', [str(u) for u in uids]),
        ])
        keys = [f"{account_id}:{folder}:{str(u)}" for u in uids]
        memcache_del_keys(keys)
        rows.unlink()
        return len(rows)

    @api.model
    def upsert_min(self, account_id, folder, uid, vals):
        vals = dict(vals or {})
        vals.update({'account_id': account_id, 'folder': folder, 'uid': str(uid)})
        rec = self.search([
            ('account_id', '=', account_id),
            ('folder', '=', folder),
            ('uid', '=', str(uid)),
        ], limit=1)
        if rec:
            rec._safe_write(vals)
            return rec.id
        return self.create(vals).id
    
    def _process_via_mailthread(self, server, raw_bytes):
        if not raw_bytes:
            return False

        MailThread = self.env["mail.thread"]

        ctx = {"fetchmail_cron_running": True}
        save_original = False
        strip_attachments = True

        if server:
            ctx["default_fetchmail_server_id"] = server.id
            save_original = bool(server.original)
            strip_attachments = not bool(server.attach)

        res_id = (
            MailThread
            .with_context(**ctx)
            .message_process(
                server.object_id.model,
                raw_bytes,
                save_original=save_original,
                strip_attachments=strip_attachments,
            )
        )
        return res_id

    def _fetch_raw_bytes(self):
        self.ensure_one()
        Account = self.account_id
        Sync = self.env["mailbox.sync"]

        if Sync._is_outlook_account(Account):
            try:
                sess, base_url = Sync._outlook_build_graph(Account)
                if not sess or not base_url:
                    return None, "outlook_no_session"

                url = f"{base_url}/me/messages/{self.uid}/$value"
                r = sess.get(url, timeout=60)
                r.raise_for_status()
                return r.content, "outlook_graph"
            except Exception as e:
                return None, f"outlook_error:{e}"

        if Sync._is_gmail_account(Account):
            try:
                service = Sync._gmail_build_service(Account)
                gmsg = service.users().messages().get(
                    userId="me", id=str(self.uid), format="raw"
                ).execute()
                raw_b64 = gmsg.get("raw") or ""
                return base64.urlsafe_b64decode(raw_b64.encode()), "gmail"
            except Exception as e:
                return None, f"gmail_error:{e}"

        server = Account.mail_server_id
        if not server:
            return None, "no_server"

        try:
            pool = get_pool(Account)
            with pool.session(ensure_selected=self.folder, readonly=True) as c:
                data = c.fetch([int(self.uid)], ["BODY.PEEK[]"]) or {}
                blob = data.get(int(self.uid), {}).get(b"BODY[]", b"")
                return (blob or None), "imap"
        except Exception as e:
            return None, f"imap_error:{e}"
    
    def _process_one(self, mark_seen=False):
        self.ensure_one()

        if self.process_state in ("done", "skipped"):
            return False

        now = fields.Datetime.now()
        if self.next_try_at and self.next_try_at > now:
            return False

        if not self._grab_in_progress():
            _logger.info("skip already taken id=%s", self.id)
            return False

        raw, hint = self._fetch_raw_bytes()
        if not raw:
            self._safe_write({
                "process_state": "failed",
                "process_error": f"raw_missing:{hint}",
                "retry_count": self.retry_count + 1,
                "next_try_at": now + relativedelta(
                    minutes=min(30 * (self.retry_count + 1), 180)
                ),
            })
            return False

        server = self.account_id.mail_server_id or False

        try:
            res_id = self._process_via_mailthread(server, raw)

            vals = {
                "process_state": "done",
                "processed_at": fields.Datetime.now(),
                "processed_model": (
                    server.object_id.model if (server and server.object_id) else "mail.thread"
                ),
                "processed_res_id": int(res_id or 0),
                "process_error": False,
            }

            if not self.raw_attachment_id:
                att = self.env["ir.attachment"].sudo().create({
                    "name": f"raw-{self.uid}.eml",
                    "datas": base64.b64encode(raw),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "message/rfc822",
                })
                vals["raw_attachment_id"] = att.id

            self._safe_write(vals)

            if mark_seen:
                Sync = self.env["mailbox.sync"]
                try:
                    if Sync._is_gmail_account(self.account_id):
                        service = Sync._gmail_build_service(self.account_id)
                        service.users().messages().modify(
                            userId="me",
                            id=str(self.uid),
                            body={"removeLabelIds": ["UNREAD"]},
                        ).execute()
                        self._safe_write({
                            "flags": ((self.flags or "") + " \\Seen").strip()
                        })

                    elif Sync._is_outlook_account(self.account_id):
                        sess, base_url = Sync._outlook_build_graph(self.account_id)
                        if sess and base_url:
                            url = f"{base_url}/me/messages/{self.uid}"
                            sess.patch(url, json={"isRead": True}, timeout=30)
                        self._safe_write({
                            "flags": ((self.flags or "") + " \\Seen").strip()
                        })

                    else:
                        try:
                            p = get_pool(self.account_id)
                            with p.session(ensure_selected=self.folder, readonly=False) as c:
                                c.add_flags([int(self.uid)], [b"\\Seen"])
                            self._safe_write({
                                "flags": ((self.flags or "") + " \\Seen").strip()
                            })
                        except Exception:
                            pass
                except Exception:
                    pass

            return True

        except Exception as e:
            try:
                self._safe_write({
                    "process_state": "failed",
                    "process_error": str(e),
                    "retry_count": self.retry_count + 1,
                    "next_try_at": fields.Datetime.now()
                    + relativedelta(
                        minutes=min(30 * (self.retry_count + 1), 180)
                    ),
                })
            except Exception:
                pass
            return False

    @api.model
    def cron_import_to_odoo(self, batch=40, max_attempts=5, mark_seen=False):
        if not self._lock_acquire():
            return 0

        try:
            now = fields.Datetime.now()
            Alias = self.env['mail.alias'].sudo()
            aliases = Alias.search([
                ('alias_name', '!=', False),
                ('alias_model_id', '!=', False),
                ('alias_domain_id', '!=', False),
            ])

            pattern_openerp = '%openerp-%'

            if not aliases:
                openerp_condition = """
                    COALESCE(message_id, '') ILIKE %s
                    OR COALESCE(in_reply_to, '') ILIKE %s
                    OR COALESCE(references_hdr, '') ILIKE %s
                """
                params = (
                    int(max_attempts),
                    now,
                    pattern_openerp,
                    pattern_openerp,
                    pattern_openerp,
                    int(batch),
                )
            else:
                full_emails = []
                localparts = []
                for alias in aliases:
                    alias_name = (alias.alias_name or '').lower()
                    domain = (alias.alias_domain_id.name or '').lower()
                    if not alias_name or not domain:
                        continue
                    full_emails.append(f"%{alias_name}@{domain}%")
                    localparts.append(f"%{alias_name}@")

                if not full_emails or not localparts:
                    openerp_condition = """
                        COALESCE(message_id, '') ILIKE %s
                        OR COALESCE(in_reply_to, '') ILIKE %s
                        OR COALESCE(references_hdr, '') ILIKE %s
                    """
                    params = (
                        int(max_attempts),
                        now,
                        pattern_openerp,
                        pattern_openerp,
                        pattern_openerp,
                        int(batch),
                    )
                else:
                    full_pattern = '|'.join(full_emails)
                    localpart_pattern = '|'.join(localparts)

                    openerp_condition = """
                        COALESCE(message_id, '') ILIKE %s
                        OR COALESCE(in_reply_to, '') ILIKE %s
                        OR COALESCE(references_hdr, '') ILIKE %s
                        OR LOWER(to_addrs || ',' || COALESCE(cc_addrs, '')) SIMILAR TO %s
                        OR (
                            (to_addrs ILIKE '%%@%%' OR COALESCE(cc_addrs, '') ILIKE '%%@%%')
                            AND (
                                LOWER(to_addrs) SIMILAR TO %s
                                OR LOWER(COALESCE(cc_addrs, '')) SIMILAR TO %s
                            )
                        )
                    """

                    full_pattern_sql = f"%({full_pattern})%"
                    localpart_pattern_sql = f"%({localpart_pattern})%"

                    params = (
                        int(max_attempts),
                        now,
                        pattern_openerp,
                        pattern_openerp,
                        pattern_openerp,
                        full_pattern_sql,
                        localpart_pattern_sql,
                        localpart_pattern_sql,
                        int(batch),
                    )

            self.env.cr.execute(f"""
                SELECT id
                FROM maildesk_message_cache
                WHERE process_state IN ('pending', 'failed')
                  AND retry_count < %s
                  AND (next_try_at IS NULL OR next_try_at <= %s)
                  AND ({openerp_condition})
                ORDER BY process_state ASC, date DESC, id DESC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            """, params)

            ids = [r[0] for r in self.env.cr.fetchall()]
            if not ids:
                return 0

            done = 0
            for rec in self.browse(ids):
                try:
                    if rec._process_one(mark_seen=mark_seen):
                        done += 1
                except Exception:
                    _logger.exception("MailDesk import failed id=%s uid=%s", rec.id, rec.uid)
                    backoff = min(30 * (rec.retry_count + 2), 180)
                    rec._safe_write({
                        'process_state': 'failed',
                        'process_error': 'exception_during_process',
                        'retry_count': rec.retry_count + 1,
                        'next_try_at': now + relativedelta(minutes=backoff),
                    })

            return done

        finally:
            self._lock_release()

    def _safe_write(self, vals, tries=2, pause=0.05):
        for rec in self:
            ok = False
            for i in range(int(tries)):
                try:
                    with rec.env.cr.savepoint():
                        super(MaildeskMessageCache, rec).write(vals)
                    ok = True
                    break
                except (SerializationFailure, LockNotAvailable) as e:
                    rec.env.cr.rollback()
                    _logger.debug(
                        "safe_write: concurrency issue on id=%s (try %s/%s): %s",
                        rec.id, i + 1, tries, e,
                    )
                    continue
                except Exception as e:
                    rec.env.cr.rollback()
                    _logger.warning(
                        "safe_write: unexpected error on id=%s: %s",
                        rec.id, e,
                    )
                    break

            if not ok:
                try:
                    with rec.env.cr.savepoint():
                        super(MaildeskMessageCache, rec).write(vals)
                except Exception as e:
                    rec.env.cr.rollback()
                    _logger.debug(
                        "safe_write: final fallback failed for id=%s: %s",
                        rec.id, e,
                    )
        return True

    def _grab_in_progress(self):
        self.env.cr.execute("""
            UPDATE maildesk_message_cache
            SET process_state='in_progress', process_error=NULL
            WHERE id=%s AND process_state IN ('pending','failed')
        RETURNING id
        """, (self.id,))
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    def _resolve_folder_id(self):
        self.ensure_one()
        Folder = self.env['mailbox.folder']
        fld = Folder.search([
            ('account_id', '=', self.account_id.id),
            '|', ('imap_name', '=', self.folder), ('name', '=', self.folder)
        ], limit=1)
        return fld.id or False

    def _ensure_body_loaded(self):
        self.ensure_one()
        if self.body_html or self.body_text:
            return
        Sync = self.env['mailbox.sync']
        folder_id = self._resolve_folder_id()
        params = {
            "uid": str(self.uid),
            "folder_id": folder_id,
            "account_id": self.account_id.id if self.account_id else False,
        }

        data = Sync.get_message_with_attachments(params) or {}
        html = data.get('body_html') or ''
        text = data.get('body_text') or ''
        if html or text:
            self._safe_write({
                'body_cached': True,
                'body_html': html,
                'body_text': text,
                'body_cache_until': fields.Datetime.now() + relativedelta(minutes=15),
            })

    def _load_attachments_if_needed(self):
        self.ensure_one()
        if not self.has_attachments:
            return []
        atts = self._prepare_attachments()
        if atts:
            return atts
        return self.env['mailbox.sync'].get_message_attachments(
            account_id=self.account_id.id,
            folder=self.folder,
            uid=self.uid,
        ) or []

    @api.model
    def _resolve_cache(self, cache_id):
        s = str(cache_id or "").strip()
        rec = None
        if s.isdigit():
            rec = self.browse(int(s))
        if not rec or not rec.exists():
            rec = self.search([("uid", "=", s)], limit=1)
        if rec and rec.exists():
            return rec

        _logger.warning(f"[MAILSYNC] Message {s} not found in cache — attempting remote fetch")
        acc = self.env["mailbox.account"].search([], limit=1)
        if not acc:
            raise UserError("No account configured to fetch message from server.")

        fetched = None
        try:
            if hasattr(acc, "_imap_fetch_by_uid"):
                fetched = acc._imap_fetch_by_uid(s)
            else:
                fetched = self.env["mailbox.sync"]._fetch_single_from_server(acc.id, s)
        except Exception as e:
            _logger.error(f"[MAILSYNC] Remote fetch failed for {s}: {e}", exc_info=True)
            raise UserError(f"Message not found on server or in cache: {s}")

        if not fetched:
            raise UserError(f"Message not found on server: {s}")

        rec = self.create({
            "uid": s,
            "account_id": acc.id,
            "subject": fetched.get("subject"),
            "from_addr": fetched.get("from"),
            "to_addrs": fetched.get("to"),
            "date": fetched.get("date"),
            "body_html": fetched.get("body_html"),
            "body_text": fetched.get("body_text"),
            "has_attachments": bool(fetched.get("attachments")),
        })
        _logger.info(f"[MAILSYNC] Message {s} fetched remotely and cached as id={rec.id}")
        return rec

    @api.model
    def get_folder(self, account_id, mid):
        rec = self.search([
            ('account_id', '=', int(account_id)),
            ('uid', '=', str(mid)),
        ], limit=1)
        return rec.parent_folder or None

    @api.model
    def set_folder(self, account_id, mid, fid, ttl_minutes=60):
        if not fid:
            return False
        rec = self.search([
            ('account_id', '=', int(account_id)),
            ('uid', '=', str(mid)),
        ], limit=1)
        if rec:
            rec._safe_write({
                'parent_folder': str(fid),
                'cache_until': fields.Datetime.now() + relativedelta(minutes=int(ttl_minutes or 60)),
            })
            return True
        return False
    
    @api.model
    def prepare_draft(self, cache_id):
        rec = self._resolve_cache(cache_id)
        rec._ensure_body_loaded()
        def _split(s): return [e.strip() for e in (s or "").split(",") if e.strip()]
        return {
            "subject": rec.subject or "",
            "body_html": (rec.body_html or rec.body_text or ""),
            "to": _split(rec.to_addrs),
            "cc": _split(rec.cc_addrs),
            "bcc": _split(rec.bcc_addrs),
            "attachments": rec._load_attachments_if_needed(),
            "has_attachments": bool(rec.has_attachments),
            "account_id": rec.account_id.id,
            "folder": rec.folder,
            "uid": rec.uid,
        }

    @api.model
    def prepare_reply(self, cache_id, reply_all=False):
        rec = self._resolve_cache(cache_id)
        rec._ensure_body_loaded()
        def _split(s): return [e.strip() for e in (s or "").split(",") if e.strip()]
        subject = rec.subject or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        body = rec.body_html or rec.body_text or ""
        reply_body = f"<p/><br/><blockquote>{body}</blockquote><br/>"
        from_addr = _split(rec.from_addr)[:1]
        if reply_all:
            others = _split(rec.to_addrs) + _split(rec.cc_addrs) + _split(rec.bcc_addrs)
            self_emails = set((self.env["mailbox.account"].search([]).mapped("email") or []))
            norm_self = {(e or "").lower() for e in self_emails}
            pool = []
            for e in others:
                el = e.lower()
                if e not in from_addr and el not in norm_self and e not in pool:
                    pool.append(e)
            cc_set = set(_split(rec.cc_addrs))
            cc = [e for e in pool if e in cc_set]
            to = from_addr + [e for e in pool if e not in cc]
        else:
            to, cc = from_addr, []
        return {
            "subject": subject,
            "body_html": reply_body,
            "to": to,
            "cc": cc,
            "bcc": [],
            "attachments": [],
            "has_attachments": bool(rec.has_attachments),
            "account_id": rec.account_id.id,
            "folder": rec.folder,
            "uid": rec.uid,
        }

    @api.model
    def prepare_forward(self, cache_id):
        rec = self._resolve_cache(cache_id)
        rec._ensure_body_loaded()
        body = rec.body_html or rec.body_text or ""
        fwd_body = f"""
<p/><br/>
<blockquote>
<p>--- Forwarded message ---<br/>
From: {rec.from_addr or ""}<br/>
Subject: {rec.subject or ""}<br/>
Date: {rec.date or ""}<br/>
To: {rec.to_addrs or ""}</p>
<p/><br/>{body}
</blockquote>
""".strip()
        return {
            "subject": f"Fwd: {rec.subject or ''}",
            "body_html": fwd_body,
            "to": [], "cc": [], "bcc": [],
            "attachments": rec._load_attachments_if_needed(),
            "has_attachments": bool(rec.has_attachments),
            "account_id": rec.account_id.id,
            "folder": rec.folder,
            "uid": rec.uid,
        }