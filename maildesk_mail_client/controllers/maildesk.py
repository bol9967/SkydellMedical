# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import http
from odoo.http import request
from werkzeug.wrappers import Response
from io import BytesIO
import base64
import logging
from email import message_from_bytes, policy
import werkzeug
from ..models.mailbox_sync import memcache_set, memcache_get, get_pool

_logger = logging.getLogger(__name__)
ATT_CACHE_TTL = 600

def _stream(data, chunk=8192):
    buf = BytesIO(data)
    while True:
        chunk_data = buf.read(chunk)
        if not chunk_data:
            break
        yield chunk_data

class MaildeskController(http.Controller):

    @http.route("/maildesk", type="http", auth="user", website=True)
    def open_maildesk(self, **kwargs):
        if not request.env.user.has_group("maildesk_mail_client.group_mailbox_user"):
            return request.redirect("/web")
        return request.redirect("/web#action=maildesk_mail_client.maildesk")
    
    def _get_gmail_service(self, account):
        Sync = request.env["mailbox.sync"].sudo()
        return Sync._gmail_build_service(account)

    def _get_raw_from_gmail(self, account, mid, aid):
        service = self._get_gmail_service(account)
        if not service:
            _logger.warning("[GMAIL att][CTRL] no service for account_id=%s", account.id)
            return b""
        fetched = service.users().messages().attachments().get(
            userId="me", messageId=mid, id=aid
        ).execute()
        raw_b64 = fetched.get("data") or ""
        try:
            return base64.urlsafe_b64decode(raw_b64.encode("utf-8")) if raw_b64 else b""
        except Exception:
            _logger.exception(
                "[GMAIL att][CTRL] base64 decode failed mid=%s aid=%s", mid, aid
            )
            return b""

    def _get_outlook_session_and_base(self, account):
        Sync = request.env["mailbox.sync"].sudo()
        sess, base_url = Sync._outlook_build_graph(account)
        return sess, base_url

    def _get_raw_from_outlook(self, account, mid, aid):
        try:
            sess, base_url = self._get_outlook_session_and_base(account)
        except Exception:
            _logger.exception("[OUTLOOK att][CTRL] cannot build session for account %s", account.id)
            return b""

        url = f"{base_url}/me/messages/{mid}/attachments/{aid}/$value"
        try:
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            return r.content or b""
        except Exception:
            _logger.exception(
                "[OUTLOOK att][CTRL] fetch error mid=%s aid=%s", mid, aid
            )
            return b""

    def _get_raw_from_cache_or_remote(self, account, mid, aid):
        provider_raw = (account.server_kind or "").lower()

        if provider_raw == "gmail":
            provider = "gmail"
        elif provider_raw == "outlook":
            provider = "outlook"
        else:
            _logger.warning(
                "[ATT][CTRL] unsupported server_kind '%s' for account_id=%s "
                "→ attachments via this endpoint are only for Gmail/Outlook",
                provider_raw, account.id,
            )
            return b""

        cache_key = f"maildesk:att:{provider}:{mid}:{aid}"
        raw = memcache_get(cache_key)
        if raw:
            _logger.info(
                "[%s att][CTRL] cache HIT mid=%s aid=%s len=%d",
                provider.upper(), mid, aid, len(raw)
            )
            return raw if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")

        _logger.info("[%s att][CTRL] cache MISS mid=%s aid=%s", provider.upper(), mid, aid)

        if provider == "gmail":
            blob = self._get_raw_from_gmail(account, mid, aid)
        else:  # outlook
            blob = self._get_raw_from_outlook(account, mid, aid)

        if blob:
            memcache_set(cache_key, blob, ttl=ATT_CACHE_TTL)
        return blob

    def _get_imap_attachment_blob(self, account, folder, uid, part_index):
        cache_key = f"maildesk:att:imap:{account.id}:{folder}:{uid}:{part_index}"
        cached = memcache_get(cache_key)
        if cached:
            try:
                blob, mimetype, filename = cached
                if isinstance(blob, (bytes, bytearray)):
                    return blob, mimetype, filename
            except Exception:
                pass

        pool = get_pool(account)
        with pool.session() as client:
            try:
                client.select_folder(folder, readonly=True)
            except Exception:
                client.select_folder("INBOX", readonly=True)

            fetched = client.fetch([int(uid)], ["BODY.PEEK[]"]) or {}
            data = fetched.get(int(uid), {}) or {}
            raw = data.get(b"BODY[]", b"")
            if not raw:
                return b"", "application/octet-stream", "attachment"

            try:
                msg = message_from_bytes(raw, policy=policy.default)
            except Exception:
                _logger.exception(
                    "[IMAP att][CTRL] message_from_bytes failed account_id=%s uid=%s",
                    account.id, uid,
                )
                return b"", "application/octet-stream", "attachment"

            current_idx = 0
            for part in msg.iter_attachments():
                current_idx += 1
                if current_idx != part_index:
                    continue

                filename = part.get_filename() or "attachment"
                mimetype = part.get_content_type() or "application/octet-stream"
                payload = part.get_payload(decode=True) or b""

                memcache_set(
                    cache_key,
                    (payload, mimetype, filename),
                    ttl=ATT_CACHE_TTL,
                )
                return payload, mimetype, filename

        return b"", "application/octet-stream", "attachment"

    @http.route("/maildesk/attachment/download", type="http", auth="user", csrf=False)
    def download_attachment(
        self, mid=None, aid=None, name=None, mimetype=None, account_id=None, **kwargs
    ):
        if not (mid and aid and account_id):
            return request.not_found()

        account = request.env["mailbox.account"].sudo().browse(int(account_id))
        if not account or not account.exists():
            return request.not_found()

        blob = self._get_raw_from_cache_or_remote(account, mid, aid)
        if not blob:
            return request.not_found()

        headers = [
            ("Content-Type", mimetype or "application/octet-stream"),
            ("Content-Disposition", f'attachment; filename="{name or "file"}"'),
            ("Cache-Control", "no-store, no-cache, must-revalidate"),
        ]
        return Response(_stream(blob), headers=headers, direct_passthrough=True)

    @http.route("/maildesk/attachment/show", type="http", auth="user", csrf=False)
    def maildesk_attachment_show(
        self, mid=None, aid=None, mimetype="application/octet-stream", account_id=None, **kwargs
    ):
        if not (mid and aid and account_id):
            return request.not_found()

        account = request.env["mailbox.account"].sudo().browse(int(account_id))
        if not account or not account.exists():
            return request.not_found()

        blob = self._get_raw_from_cache_or_remote(account, mid, aid)
        if not blob:
            return request.not_found()

        headers = [
            ("Content-Type", mimetype or "application/octet-stream"),
            ("Cache-Control", "no-store, no-cache, must-revalidate"),
        ]
        return request.make_response(blob, headers)

    @http.route(
        "/maildesk/imap_attachment/<int:account_id>/<path:folder>/<int:uid>/<int:part_index>",
        type="http",
        auth="user",
        csrf=False,
    )
    def maildesk_imap_attachment(
        self,
        account_id,
        folder,
        uid,
        part_index,
        download=False,
        **kwargs,
    ):
        account = request.env["mailbox.account"].sudo().browse(account_id)
        if not account or not account.exists():
            return request.not_found()

        blob, mimetype, filename = self._get_imap_attachment_blob(
            account, folder, uid, part_index
        )
        if not blob:
            return request.not_found()

        if str(download) in ("1", "true", "True", "yes"):
            headers = [
                ("Content-Type", mimetype or "application/octet-stream"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
                ("Cache-Control", "no-store, no-cache, must-revalidate"),
            ]
            return Response(_stream(blob), headers=headers, direct_passthrough=True)

        headers = [
            ("Content-Type", mimetype or "application/octet-stream"),
            ("Cache-Control", "no-store, no-cache, must-revalidate"),
        ]
        return request.make_response(blob, headers)

    @http.route("/maildesk/inline/<int:att_id>", type="http", auth="user")
    def inline(self, att_id, **kw):
        Att = request.env["maildesk.inline.attachment"].sudo()
        att = Att.browse(att_id)
        if not att.exists():
            return werkzeug.exceptions.NotFound()

        data = att.data
        if not data:
            return werkzeug.exceptions.NotFound()

        headers = [
            ('Content-Type', att.mimetype or "application/octet-stream"),
            ('Cache-Control', 'max-age=86400'),
        ]

        return request.make_response(data, headers)