# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import models, api, fields, SUPERUSER_ID, _
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from odoo.tools.mail import decode_message_header, email_split_tuples
from markupsafe import Markup
from html import unescape as html_unescape
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError
from imapclient import IMAPClient
import imapclient
from datetime import datetime, timezone
from psycopg2.errors import SerializationFailure, UniqueViolation, LockNotAvailable
from email.utils import make_msgid, formataddr, formatdate
from werkzeug.urls import url_quote
import quopri
from html import escape as html_escape

import re
import hashlib
import base64
import time
from bs4 import BeautifulSoup
from contextlib import suppress
from time import perf_counter

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import requests

import queue
from queue import Queue
from contextlib import contextmanager

from .idle_manager import get_idle_manager
from .utils_email_defaults import defaults_from_email

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

import msal

import logging
_logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "openid", "email",
]

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
]

FOLDER_PRIORITY = {
    "INBOX": 0,
    "Sent": 1, "Gesendet": 1, "Gesendete Objekte": 1,
    "Archive": 2, "Archives": 2,
    "Drafts": 3, "Entwürfe": 3,
    "Trash": 99, "Gelöscht": 99, "Papierkorb": 99,
}

SEEN = rb"\Seen"
SENT = rb"\Sent"

_MAILDESK_MEMCACHE = {}
_MAILDESK_MEMCACHE_LOCK = threading.RLock()

_POOLS = {}
_POOLS_LOCK = threading.RLock()

def get_pool(account):
    key = account.id
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if not pool:
            pool = MailDeskIMAPPool(account, size=4)
            _POOLS[key] = pool
        return pool
    
def memcache_get(key):
    with _MAILDESK_MEMCACHE_LOCK:
        item = _MAILDESK_MEMCACHE.get(key)
        if not item:
            return None
        expires, val = item
        if time.time() > expires:
            _MAILDESK_MEMCACHE.pop(key, None)
            return None
        return val

def memcache_del_keys(keys):
    with _MAILDESK_MEMCACHE_LOCK:
        for k in keys:
            _MAILDESK_MEMCACHE.pop(k, None)

def memcache_set(key, value, ttl=3600):
    with _MAILDESK_MEMCACHE_LOCK:
        _MAILDESK_MEMCACHE[key] = (time.time() + ttl, value)

def _hsl(seed):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 360
    return f"hsl({h}, 70%, 50%)"

def _safe_dt(rec):
    d = rec.get("date")
    if isinstance(d, datetime):
        return d
    try:
        return fields.Datetime.to_datetime(d)
    except Exception:
        return datetime(1970, 1, 1)
       
class IMAPClientWithAuth(IMAPClient):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ssl", True)
        kwargs.setdefault("use_uid", True)
        kwargs.setdefault("timeout", 30)
        super().__init__(*args, **kwargs)
        self._selected_folder = None

    @property
    def selected_folder(self):
        return self._selected_folder

    def select_folder(self, mailbox, readonly=False):
        res = super().select_folder(mailbox, readonly=readonly)
        self._selected_folder = mailbox
        return res

class MailDeskIMAPPool:
    def __init__(self, account, size=5):
        server = account.mail_server_id
        if not server:
            raise Exception("Incoming fetchmail.server is not configured")

        server_type = (getattr(server, "server_type", "") or "").lower()
        if server_type in ("gmail", "outlook", "ms365", "microsoft", "office365"):
            raise Exception("MailDeskIMAPPool must not be used for Gmail/Outlook OAuth accounts")

        self.account_id = account.id

        self.host = server.server
        self.port = int(server.port or 993)
        self.is_ssl = bool(server.is_ssl)

        self.username = (server.user or account.email or "").strip()
        self.password = getattr(server, "password", None) or ""

        if not self.host:
            raise Exception("IMAP host is not set on fetchmail.server")
        if not self.username or not self.password:
            raise Exception("IMAP username/password are not set on fetchmail.server")

        self.size = size
        self.pool = Queue(maxsize=size)
        for _ in range(size):
            self.pool.put(self._create_client())

    def _create_client(self):
        c = IMAPClientWithAuth(
            host=self.host,
            port=self.port,
            ssl=self.is_ssl,
            use_uid=True,
        )
        try:
            c.login(self.username, self.password)
        except Exception as e:
            with suppress(Exception):
                c.logout()
            raise Exception(f"IMAP password login failed: {e}")

        with suppress(Exception):
            caps = c.capabilities() or []
            if (b"UTF8=ACCEPT" in caps) or ("UTF8=ACCEPT" in caps):
                c.enable("UTF8=ACCEPT")
        return c

    @contextmanager
    def session(self, ensure_selected=None, readonly=True):
        c = self.pool.get()
        try:
            try:
                c.noop()
            except Exception:
                c = self._recreate(c)
            if ensure_selected and getattr(c, "selected_folder", None) != ensure_selected:
                c.select_folder(ensure_selected, readonly=readonly)
            yield c
        finally:
            try:
                self.pool.put(c)
            except Exception:
                with suppress(Exception):
                    c.logout()

    def _recreate(self, dead):
        with suppress(Exception):
            dead.logout()
        return self._create_client()

class MailboxSync(models.AbstractModel):
    _name = "mailbox.sync"
    _description = "Mailbox Sync Service"

    def _user_accounts(self):
        Account = self.env["mailbox.account"]
        accounts = Account.search([("access_user_ids", "in", [self.env.uid])])
        return accounts

    @api.model
    def idle_subscribe(self, account_id: int, session_id: str = None):
        try:
            account_id = int(account_id)
        except Exception:
            _logger.warning("idle_subscribe: invalid account_id=%r", account_id)
            return {"ok": False, "error": "invalid_account_id"}

        sid = session_id or getattr(self.env, "session_sid", None) or f"user-{self.env.uid}"

        Account = self.env["mailbox.account"]
        acc = Account.browse(account_id)
        if not acc.exists():
            _logger.warning("idle_subscribe: account %s not found (sid=%s, uid=%s)", account_id, sid, self.env.uid)
            return {"ok": False, "error": "account_not_found"}

        mgr = get_idle_manager(self.env)
        before = {}
        try:
            before = mgr.status()
        except Exception:
            before = {}

        try:
            mgr.subscribe(self.env, account_id, sid)
        except Exception as e:
            _logger.exception("idle_subscribe: subscribe failed acc=%s sid=%s: %s", account_id, sid, e)
            return {"ok": False, "error": "subscribe_failed", "detail": str(e)}

        after = {}
        try:
            after = mgr.status()
        except Exception:
            after = {}

        _logger.info(
            "idle_subscribe: ok acc=%s sid=%s uid=%s leader=%s watchers_before=%s watchers_after=%s subs_after=%s",
            account_id,
            sid,
            self.env.uid,
            after.get("is_leader"),
            (before.get("watchers") or []),
            (after.get("watchers") or []),
            (after.get("subs") or {}),
        )

        return {
            "ok": True,
            "leader": after.get("is_leader", False),
            "watching": account_id in (after.get("watchers") or []),
            "subs": (after.get("subs") or {}).get(account_id, 0),
        }

    @api.model
    def idle_unsubscribe(self, account_id: int, session_id: str = None):
        sid = session_id or getattr(self.env, "session_sid", None) or f"user-{self.env.uid}"
        mgr = get_idle_manager(self.env)
        mgr.unsubscribe(int(account_id), sid)
        return True

    @api.model
    def idle_touch(self, account_id: int, session_id: str = None):
        sid = session_id or getattr(self.env, "session_sid", None) or f"user-{self.env.uid}"
        mgr = get_idle_manager(self.env)
        mgr.touch(int(account_id), sid)
        return True
    
    def _get_imap_client(self, account):
        server = account.mail_server_id
        if not server:
            raise Exception("Incoming fetchmail.server is not configured")

        host = server.server
        port = int(server.port or 993)
        use_ssl = bool(server.is_ssl)

        if not host:
            raise Exception("IMAP host is not set on fetchmail.server")

        client = IMAPClientWithAuth(
            host=host,
            port=port,
            ssl=use_ssl,
            use_uid=True,
            timeout=120,
        )

        if getattr(server, "server_type", "") == "gmail" or self._is_gmail_account(account):
            try:
                self._gmail_build_service(account)
            except Exception as e:
                try:
                    if hasattr(server, "_generate_oauth2_string"):
                        server._generate_oauth2_string(server.user, server.google_gmail_refresh_token)
                except Exception:
                    pass

            access_token = getattr(server, "google_gmail_access_token", None)
            username = (server.user or account.email or "").strip()
            if not access_token or not username:
                raise Exception("Gmail OAuth2: missing access token or username (server.user).")

            try:
                client.oauth2_login(username, access_token)
            except Exception as e:
                client.logout()
                raise Exception(f"Gmail XOAUTH2 login failed: {e}")

            try:
                caps = client.capabilities() or []
                if (b"UTF8=ACCEPT" in caps) or ("UTF8=ACCEPT" in caps):
                    client.enable("UTF8=ACCEPT")
            except Exception:
                pass

            return client

        if str(getattr(server, "server_type", "")).lower() in ("outlook", "ms365", "microsoft", "office365") \
        or self._is_outlook_account(account):
            username = (server.user or account.email or "").strip()
            if not username:
                client.logout()
                raise Exception("Outlook OAuth2: missing username (fetchmail.server.user).")

            if not hasattr(server, "_generate_outlook_oauth2_string"):
                client.logout()
                raise Exception("Outlook OAuth2: server does not provide _generate_outlook_oauth2_string().")

            try:
                server._generate_outlook_oauth2_string(username)
            except Exception as e:
                client.logout()
                raise Exception(f"Outlook OAuth2: could not (re)fetch access token: {e}")

            access_token = getattr(server, "microsoft_outlook_access_token", None)
            if not access_token:
                client.logout()
                raise Exception("Outlook OAuth2: access token not available after refresh.")

            try:
                client.oauth2_login(username, access_token)
            except Exception as e:
                client.logout()
                raise Exception(f"Outlook XOAUTH2 login failed: {e}")

            try:
                caps = client.capabilities() or []
                if (b"UTF8=ACCEPT" in caps) or ("UTF8=ACCEPT" in caps):
                    client.enable("UTF8=ACCEPT")
            except Exception:
                pass

            return client

        user = (server.user or account.email or "").strip()
        pwd  = getattr(server, "password", None)
        if not user or not pwd:
            client.logout()
            raise Exception("IMAP username/password are not set on fetchmail.server")

        try:
            client.login(user, pwd)
        except Exception as e:
            client.logout()
            raise Exception(f"IMAP password login failed: {e}")

        try:
            caps = client.capabilities() or []
            if (b"UTF8=ACCEPT" in caps) or ("UTF8=ACCEPT" in caps):
                client.enable("UTF8=ACCEPT")
        except Exception:
            pass

        return client

    def _now(self):
        return fields.Datetime.now()

    @api.model
    def _cache_ttl_minutes(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return int(float(ICP.get_param("maildesk.cache.ttl.hours", "1")) * 60)

    @api.model
    def _body_ttl_minutes(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return int(ICP.get_param("maildesk.cache.body_ttl.minutes", "15"))

    @api.model
    def _warm_count(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return int(ICP.get_param("maildesk.cache.warm.count", "50"))

    def _has_non_ascii(self, s):
        return bool(s) and any(ord(ch) > 127 for ch in s)

    def _ensure_caps(self, account, client, folder_name):
        try:
            caps = client.capabilities() or set()
        except Exception:
            try:
                client.logout()
            except Exception:
                pass
            client = self._get_imap_client(account)
            client.select_folder(folder_name, readonly=True)
            caps = client.capabilities() or set()
        caps = {(c.decode() if isinstance(c, bytes) else c).upper() for c in caps}
        return client, caps

    @api.model
    def _to_datetime(self, value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", "ignore")
        if isinstance(value, str):
            try:
                dt = parsedate_to_datetime(value)
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except Exception:
                return fields.Datetime.now()
        return fields.Datetime.now()

    def _norm_msgid(self, val):
        if not val:
            return ""
        if isinstance(val, (list, tuple)):
            val = " ".join([str(v or "") for v in val])
        s = str(val).strip()
        m = re.search(r"<([^>]+)>", s)
        if m:
            s = m.group(1)
        return s.strip().lower()

    def _message_to_dict(self, rec):
        return {
            "id": rec.uid,
            "subject": rec.subject or "(no subject)",
            "email_from": rec.from_addr or "",
            "sender_display_name": rec.sender_display_name or "",
            "date": rec.date,
            "formatted_date": fields.Datetime.context_timestamp(self, rec.date).strftime("%d %b %Y %H:%M") if rec.date else "",
            "body_plain": rec.body_text or "",
            "body_original": rec.body_html or "",
            "folder": rec.folder,
            "to_display": rec.to_addrs or "",
            "cc_display": rec.cc_addrs or "",
            "bcc_display": rec.bcc_addrs or "",
            "has_attachments": rec.has_attachments,
            "attachments": rec._prepare_attachments(),
            "avatar_html": rec.avatar_html or self._avatar_html(rec.from_addr, None),
            "avatar_partner_id": False,
            "is_read": "\\Seen" in (rec.flags or ""),
            "is_starred": "\\Flagged" in (rec.flags or ""),
            "is_draft": "\\Draft" in (rec.flags or ""),
            "message_id": (rec.message_id or ""),
        }

    @api.model
    def _decode_header_value(self, value):
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray)):
            try:
                value = value.decode("utf-8", "ignore")
            except Exception:
                value = value.decode("latin-1", "ignore")
        try:
            return str(make_header(decode_header(value))) or ""
        except Exception:
            msg = EmailMessage()
            msg["X"] = value
            return decode_message_header(msg, "X") or value

    def _replace_cid_src(self, body_html, attachments):
        if not body_html or not attachments:
            return body_html

        def _norm_cid(val):
            if not val:
                return "", ""
            v = val.strip().strip("<>").strip()
            if "@" in v:
                base = v.split("@", 1)[0]
            else:
                base = v
            return v, base

        cid_map = {}
        for att in attachments:
            raw_cid = (
                att.get("content_id")
                or att.get("contentId")
                or att.get("cid")
                or ""
            )
            full, base = _norm_cid(raw_cid)
            if not full and not base:
                continue

            url = (
                att.get("preview_url")
                or att.get("previewUrl")
                or att.get("defaultSource")
                or att.get("download_url")
                or att.get("downloadUrl")
            )
            if not url:
                continue

            if full:
                cid_map[full] = url
            if base:
                cid_map[base] = url
            if full != f"<{full}>":
                cid_map[f"<{full}>"] = url
            if base and base != full:
                cid_map[f"<{base}>"] = url

        if not cid_map:
            return body_html

        try:
            soup = BeautifulSoup(body_html, "lxml")
        except Exception:
            soup = BeautifulSoup(body_html, "html.parser")

        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src.lower().startswith("cid:"):
                continue

            raw = src[4:].strip()
            full, base = _norm_cid(raw)

            url = (
                cid_map.get(raw)
                or cid_map.get(full)
                or cid_map.get(base)
            )
            if url:
                img["src"] = url

        return str(soup)

    @api.model
    def _strip_html_to_text(self, html):
        text = html_unescape(html or "")
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?is)<br\s*/?>", "\n", text)
        text = re.sub(r"(?is)</p\s*>", "\n", text)
        text = re.sub(r"(?is)<.*?>", " ", text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n+", " ", text)
        return text.strip()

    @api.model
    def _avatar_initials(self, display_name):
        name = (display_name or "").strip()
        if not name:
            return "?"

        parts = [p for p in re.split(r"\s+", name) if p]

        letters = []
        for part in parts:
            for ch in part:
                if ch.isalpha():
                    letters.append(ch.upper())
                    break
                if ch.isdigit() and not letters:
                    letters.append(ch)
                    break
            if len(letters) == 2:
                break

        if not letters:
            return "?"

        return "".join(letters)


    @api.model
    def _avatar_html(self, email_from, partner):
        if partner and partner.image_128:
            display_name = (partner.name or "").strip() or self._display_name_from_email(email_from)
            display_name = (display_name or "").strip()
            return Markup(
                f'<img src="/web/image/res.partner/{partner.id}/image_128" '
                f'class="rounded-circle sender-icon" width="42" height="42" '
                f'alt="{Markup.escape(display_name) or "Avatar"}"/>'
            )

        display_name = None
        if partner and partner.name:
            display_name = partner.name
        else:
            display_name = self._display_name_from_email(email_from)

        display_name = (display_name or "").strip()

        if not display_name or not re.search(r"\w", display_name):
            display_name = (email_from or "").strip()

        initials = self._avatar_initials(display_name)

        seed = None
        if partner:
            seed = (partner.name or "").strip() or f"partner:{partner.id}"
        if not seed:
            seed = display_name or (email_from or "x")

        bg = _hsl(seed.lower())

        return Markup(
            '<div class="rounded-circle d-flex align-items-center justify-content-center '
            'sender-icon" '
            f'style="background:{bg};color:#fff;width:42px;height:42px;'
            'font-weight:700;font-size:16px;">'
            f'{Markup.escape(initials)}'
            '</div>'
        )

    @api.model
    def _display_name_from_email(self, value):
        value = value or ""
        m = re.match(r"^(.*?)(<.*>)$", value)
        if m:
            return (m.group(1) or "").strip()
        if "@" in value:
            return value.split("@")[0].replace(".", " ").replace("_", " ").title()
        return value

    @api.model
    def _parse_sender_header(self, header_bytes):
        header_val = header_bytes.decode("utf-8", "ignore") if isinstance(header_bytes, (bytes, bytearray)) else (header_bytes or "")
        msg = EmailMessage()
        msg["From"] = header_val

        decoded = decode_message_header(msg, "From") or header_val
        pairs = email_split_tuples(decoded)

        if pairs:
            name, email = pairs[0]
            name = (name or "").strip()
            email = (email or "").lower()
            formatted = f"{name} <{email}>" if name else email
            return formatted, (name or email), email

        m = re.search(r"<([^>]+)>", decoded)
        if m:
            email = (m.group(1) or "").strip().lower()
            name = (decoded[:m.start()] or "").strip()
            formatted = f"{name} <{email}>" if name else email
            return formatted, (name or email), email

        email = decoded.strip().lower()
        return email, self._display_name_from_email(decoded), email

    @api.model
    def _addr_to_email(self, addr_obj):
        if not addr_obj or not getattr(addr_obj, "mailbox", None) or not getattr(addr_obj, "host", None):
            return ""
        mailbox = addr_obj.mailbox.decode() if isinstance(addr_obj.mailbox, (bytes, bytearray)) else addr_obj.mailbox
        host = addr_obj.host.decode() if isinstance(addr_obj.host, (bytes, bytearray)) else addr_obj.host
        return f"{mailbox}@{host}".lower()

    @api.model
    def _join_addresses(self, lst):
        out = []
        for p in lst or []:
            name = (p.name or "").decode() if isinstance(getattr(p, "name", None), (bytes, bytearray)) else (p.name or "")
            email = self._addr_to_email(p)
            if not email:
                continue
            out.append(f"{name} <{email}>" if name else email)
        return ", ".join(out)

    def _criteria_key(self, criteria):
        def flat(x):
            if isinstance(x, (list, tuple)):
                return "(" + " ".join(flat(i) for i in x) + ")"
            return str(x)
        return flat(criteria).upper()

    def _fast_search_uids(self, client, folder_name, criteria, offset, limit, is_all):
        res = client.select_folder(folder_name, readonly=True)
        uidnext = int(res.get(b"UIDNEXT") or res.get("UIDNEXT") or 1)

        key = f"uidlist:{self.env.cr.dbname}:{folder_name}:{uidnext}:{self._criteria_key(criteria)}"
        cached = memcache_get(key)
        if cached:
            u_sorted = cached
            return u_sorted[offset:offset+limit], len(u_sorted)

        base = offset + limit * 3
        window = 5000 if not is_all else max(400, base)
        start = max(1, uidnext - window)

        crit = [c for c in criteria if c != "ALL"] + ["UID", f"{start}:*"]

        def _needs_charset(cs):
            flat = " ".join(map(str, cs)).upper()
            return any(k in flat for k in ("TEXT ", " BODY ", " SUBJECT ", " FROM ", " TO ", " CC ", " BCC "))

        try:
            caps = client.capabilities() or []
            utf8_ok = (b"UTF8=ACCEPT" in caps) or ("UTF8=ACCEPT" in caps)
        except Exception:
            utf8_ok = False

        charset = ("UTF-8" if (utf8_ok and _needs_charset(crit)) else None)

        uids = client.search(crit, charset=charset) or []
        u_sorted = sorted([int(u) for u in uids], reverse=True)
        memcache_set(key, u_sorted, ttl=10)
        return u_sorted[offset:offset+limit], len(u_sorted)

    
    @api.model
    def _build_search_criteria(self, account=None, flt=None, text=None, partner_id=None, email_from=None):
        criteria = ["ALL"]
        sender = (account.email or "").lower() if account else ""
        if flt == "unread":
            criteria.append("UNSEEN")
        elif flt == "starred":
            criteria.append("FLAGGED")
        elif flt == "incoming":
            if sender:
                criteria.extend(["NOT", ["FROM", sender]])
        elif flt == "outgoing":
            if sender:
                criteria.extend(["FROM", sender])
        if partner_id and not email_from:
            partner = self.env["res.partner"].browse(partner_id)
            if partner and partner.email:
                email_from = partner.email
        if email_from:
            criteria.extend(["FROM", (email_from or "").lower()])
        if text:
            s = re.sub(r"\s+", " ", text.strip())
            if s:
                criteria.extend(["TEXT", s])
        return criteria

    @api.model
    def _has_attachments_from_bodystructure(self, node):
        def to_text(x, lower=True):
            if x is None:
                return ""
            if isinstance(x, (bytes, bytearray)):
                try:
                    s = x.decode("utf-8", "ignore")
                except Exception:
                    s = x.decode("latin-1", "ignore")
            else:
                s = str(x)
            return s.lower() if lower else s

        def params_pairs(p):
            if not p:
                return []
            if isinstance(p, dict):
                return list(p.items())
            if isinstance(p, (list, tuple)):
                if len(p) == 2 and not isinstance(p[0], (list, tuple)) and not isinstance(p[1], (list, tuple)):
                    return [p]
                pairs = []
                for it in p:
                    if isinstance(it, (list, tuple)) and len(it) == 2:
                        pairs.append(it)
                return pairs
            return []

        def part_ct(part):
            if hasattr(part, "content_type"):
                return to_text(part.content_type)
            if isinstance(part, (list, tuple)) and len(part) >= 2:
                return f"{to_text(part[0])}/{to_text(part[1])}"
            return ""

        def part_params(part):
            if hasattr(part, "params"):
                return params_pairs(part.params)
            if isinstance(part, (list, tuple)) and len(part) >= 3:
                return params_pairs(part[2])
            return []

        def part_disp(part):
            if hasattr(part, "disposition"):
                return part.disposition
            if isinstance(part, (list, tuple)) and len(part) >= 9:
                return part[8]
            return None

        def part_disp_params(disp):
            if not disp:
                return []
            if isinstance(disp, (list, tuple)) and len(disp) >= 2:
                return params_pairs(disp[1])
            return []

        def part_disp_token(disp):
            if not disp:
                return ""
            if isinstance(disp, (list, tuple)) and len(disp) >= 1:
                return to_text(disp[0])
            return to_text(disp)

        def part_cid(part):
            if hasattr(part, "id"):
                return to_text(part.id)
            if isinstance(part, (list, tuple)) and len(part) >= 4:
                return to_text(part[3])
            return ""

        def has_name(pairs):
            for k, v in pairs:
                if to_text(k) in ("name", "filename") and v:
                    return True
            return False

        def walk(n):
            if hasattr(n, "parts") and n.parts:
                for sp in n.parts:
                    yield from walk(sp)
            elif isinstance(n, (list, tuple)) and n and isinstance(n[0], list):
                for sp in n[0]:
                    yield from walk(sp)
            else:
                yield n

        for part in walk(node):
            ctype = part_ct(part)
            disp = part_disp(part)
            disp_tok = part_disp_token(disp)
            pparams = part_params(part)
            dparams = part_disp_params(disp)
            cid = part_cid(part)

            if disp_tok == "attachment":
                return True

            if has_name(pparams) or has_name(dparams):
                return True

            if ctype and not ctype.startswith("text/") and not ctype.startswith("multipart/"):
                return True

            if ctype.startswith("image/") and cid:
                return True

            if ctype.startswith("text/"):
                ext_like = any(
                    ctype.endswith(suf)
                    for suf in (
                        "/markdown", "/x-markdown", "/csv", "/tab-separated-values",
                        "/plain; charset=us-ascii"
                    )
                )
                if ext_like and (disp_tok in ("inline", "attachment") or has_name(pparams) or has_name(dparams)):
                    return True

        return False

    @api.model
    def message_meta_bulk(self, account_id, folder_id, uids):
        Account = self.env["mailbox.account"].browse(account_id)
        Folder  = self.env["mailbox.folder"].browse(folder_id)
        if not Account or not Folder or not uids:
            return []

        partner_cache = {}

        if self._is_gmail_account(Account):
            service = self._gmail_build_service(Account)
            return self._gmail_fetch_meta_batch(service, Account, Folder, [str(u) for u in uids], partner_cache)

        if self._is_outlook_account(Account):
            sess, base = self._outlook_build_graph(Account)
            if sess and base:
                return self._outlook_fetch_meta_batch(sess, base, Account, Folder, [str(u) for u in uids], partner_cache)

        return self._fetch_list_records_parallel(
            client=False,
            uids=[int(u) for u in uids],
            folder=Folder,
            account=Account,
            partner_cache=partner_cache,
        )
    
    def _apply_local_overrides(self, account, folder_name, records):
        Cache = self.env["maildesk.message_cache"].sudo()
        uids = [str(r.get("id")) for r in records if r.get("id")]
        cmap = Cache.get_cache_map(account.id, folder_name or "INBOX", uids)
        for r in records:
            c = cmap.get(str(r["id"]))
            if not c:
                continue
            if hasattr(c, "read_override") and c.read_override is not None:
                r["is_read"] = bool(c.read_override)
            if hasattr(c, "star_override") and c.star_override is not None:
                r["is_starred"] = bool(c.star_override)
            if hasattr(c, "tag_ids") and c.tag_ids:
                r["tag_ids"] = list(c.tag_ids.ids)
        return records

    def _filter_by_tags_local(self, account, folder_name, records, tag_ids):
        if not tag_ids:
            return records, len(records)
        Cache = self.env["maildesk.message_cache"].sudo()
        uids = [str(r.get("id")) for r in records if r.get("id")]
        if not uids:
            return [], 0
        recs = Cache.search([
            ("account_id", "=", account.id),
            ("folder", "=", (folder_name or "INBOX")),
            ("uid", "in", uids),
            ("tag_ids", "all", [(6, 0, tag_ids)]),
        ])
        keep = {c.uid for c in recs}
        out = [r for r in records if str(r["id"]) in keep]
        return out, len(out)

    def _apply_overrides_and_tags(self, account, folder, records, total, tag_ids):
        folder_name = (getattr(folder, "imap_name", None) or getattr(folder, "name", None) or "INBOX")
        records = self._apply_local_overrides(account, folder_name, records)
        if tag_ids:
            records, total = self._filter_by_tags_local(account, folder_name, records, tag_ids)
        return records, total

    def _apply_state_overlays(self, account, folder_name, records):
        folder_name = folder_name or "INBOX"
        State = self.env["maildesk.email_state"].sudo()

        uids = [
            str(r.get("uid") if r.get("uid") is not None else r.get("id"))
            for r in records
            if (r.get("uid") is not None or r.get("id"))
        ]

        st = State.search([
            ("account_id", "=", account.id),
            ("folder", "=", folder_name),
            ("uid", "in", uids),
        ])
        by_uid = {s.uid: s for s in st}

        moved_here_states = State.search([
            ("account_id", "=", account.id),
            ("has_move", "=", True),
            ("target_folder", "=", folder_name),
        ])

        out = []
        for r in records:
            key = str(r.get("uid") if r.get("uid") else r.get("id"))
            s = by_uid.get(key)

            if s:
                if s.has_delete and s.is_delete:
                    continue

                if s.has_move and s.target_folder and s.target_folder != folder_name:
                    continue

                if s.has_seen:
                    r["is_read"] = bool(s.seen)
                if s.has_starred:
                    r["is_starred"] = bool(s.starred)

            out.append(r)

        existing = {str(r.get("uid") or r.get("id")) for r in out}
        Cache = self.env["maildesk.message_cache"].sudo()

        for st in moved_here_states:
            if st.uid in existing:
                continue

            cached = Cache.search([
                ("account_id", "=", account.id),
                ("uid", "=", st.uid),
            ], order="id desc", limit=1)

            if not cached:
                continue

            rec = cached.to_record_dict() if hasattr(cached, "to_record_dict") else cached._to_record()
            rec["uid"] = st.uid
            rec["folder"] = folder_name
            rec["folder_name"] = folder_name

            if st.has_seen:
                rec["is_read"] = bool(st.seen)
            if st.has_starred:
                rec["is_starred"] = bool(st.starred)

            out.append(rec)

        return out

    def _extract_imap_preview(self, blob, subject, max_len=120, max_bytes=16384):
        subj = (subject or "")[:max_len]
        if not blob:
            return subj

        if len(blob) > max_bytes:
            blob = blob[:max_bytes]

        text = None
        for enc in ("utf-8", "latin-1"):
            try:
                text = blob.decode(enc, "ignore")
                break
            except Exception:
                text = None
        if not text:
            return subj

        def _extract_from_part(full_text, mime_subtype="plain"):
            pat = re.compile(
                r'(?is)(content-type:\s*text/%s[^\r\n]*\r?\n(?:[^\r\n]*\r?\n)*?)\r?\n'
                % mime_subtype
            )
            m = pat.search(full_text)
            if not m:
                return None, False

            header_block = m.group(1)
            body_start = m.end()

            m_boundary = re.search(r'\r?\n--[^\r\n]+\r?\n', full_text[body_start:])
            if m_boundary:
                body_raw = full_text[body_start : body_start + m_boundary.start()]
            else:
                body_raw = full_text[body_start:]

            hdr_lower = header_block.lower()
            body = body_raw

            if "quoted-printable" in hdr_lower:
                try:
                    body = quopri.decodestring(
                        body_raw.encode("utf-8", "ignore")
                    ).decode("utf-8", "ignore")
                except Exception:
                    body = body_raw
            elif "base64" in hdr_lower:
                try:
                    raw = "".join(re.findall(r"[A-Za-z0-9+/=]+", body_raw))
                    decoded = base64.b64decode(raw + "===")
                    body = decoded.decode("utf-8", "ignore")
                except Exception:
                    body = body_raw

            is_html = "text/html" in hdr_lower
            return body, is_html

        body, is_html = _extract_from_part(text, "plain")
        if not body:
            body, is_html = _extract_from_part(text, "html")

        if not body:
            body = text
            is_html = False

        if is_html or "<html" in body.lower() or "<body" in body.lower():
            try:
                body = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass

        lines = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith(">"):
                continue
            if re.match(r"(?i)^on .+wrote:", s) or re.match(r"(?i)^am .+schrieb", s):
                break
            lines.append(s)

        body_clean = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if not body_clean:
            return subj

        return body_clean[:max_len]

    def _find_linked_document(self, message_id, in_reply_to):
        MailMessage = self.env["mail.message"].sudo()

        token1 = (message_id or "").strip("<>")
        token2 = (in_reply_to or "").strip("<>")

        def find(token):
            if not token:
                return False
            return MailMessage.search(
                [("message_id", "ilike", token)],
                order="id desc",
                limit=1,
            )

        rec = False
        if token2:
            rec = find(token2)
        if not rec and token1:
            rec = find(token1)

        if not rec:
            return False, False

        return rec.model, rec.res_id
    
    @api.model
    def message_search_load(
        self,
        account_id=None,
        folder_id=None,
        filter=None,
        search=None,
        offset=0,
        limit=30,
        partner_id=None,
        email_from=None,
        tag_ids=None,
    ):
        if not self.env.registry.ready:
            return {"records": [], "totalMessagesCount": 0}
        
        Account = self.env["mailbox.account"]
        Folder = self.env["mailbox.folder"]
        partner_cache = {}

        def gmail_q(acc):
            return self._gmail_query_from_filters(
                account=acc, flt=filter, text=search, partner_id=partner_id, email_from=email_from
            )

        if folder_id:
            folder = Folder.browse(folder_id)
            if not folder:
                return {"records": [], "totalMessagesCount": 0}
            account = folder.account_id
            account_id = account.id

            records = []
            total = 0

            if self._is_gmail_account(account):
                service = self._gmail_build_service(account)
                q = gmail_q(account)
                ids_page, total = self._gmail_list_message_ids(
                    service, account, folder, q, offset, limit
                )
                records = self._gmail_fetch_meta_batch(
                    service, account, folder, ids_page, partner_cache
                )
                records, total = self._apply_overrides_and_tags(
                    account, folder, records, total, tag_ids
                )
                records = self._apply_state_overlays(
                    account, (folder.imap_name or folder.name or "ALL_MAIL"), records
                )
                records.sort(
                    key=lambda r: (_safe_dt(r), str(r.get("uid") or 0)),
                    reverse=True,
                )
                msg_ids = [r["message_id_norm"] for r in records if r.get("message_id_norm")]
                tmap = self._get_tags_for_message_ids(account.id, msg_ids)
                for r in records:
                    r["tag_ids"] = tmap.get(r["message_id_norm"], [])

            elif self._is_outlook_account(account):
                sess, base = self._outlook_build_graph(account)
                if sess and base:
                    q = self._outlook_query_from_filters(
                        account=account,
                        flt=filter,
                        text=search,
                        partner_id=partner_id,
                        email_from=email_from,
                    )
                    ids_page, total = self._outlook_list_message_ids(
                        sess, base, account, folder, q, offset, limit
                    )
                    records = self._outlook_fetch_meta_batch(
                        sess, base, account, folder, ids_page, partner_cache
                    )
                    records, total = self._apply_overrides_and_tags(
                        account, folder, records, total, tag_ids
                    )
                    records = self._apply_state_overlays(
                        account, (folder.imap_name or folder.name or "ALL_MAIL"), records
                    )
                    records.sort(
                        key=lambda r: (_safe_dt(r), str(r.get("uid") or 0)),
                        reverse=True,
                    )
                    msg_ids = [
                        r["message_id_norm"] for r in records if r.get("message_id_norm")
                    ]
                    tmap = self._get_tags_for_message_ids(account.id, msg_ids)
                    for r in records:
                        r["tag_ids"] = tmap.get(r["message_id_norm"], [])

            else:
                pool = get_pool(account)
                folder_name = folder.imap_name or folder.name or "INBOX"
                with pool.session() as client:
                    try:
                        caps = client.capabilities() or []
                        if b"UTF8=ACCEPT" in caps or "UTF8=ACCEPT" in caps:
                            client.enable("UTF8=ACCEPT")
                    except Exception:
                        pass
                    client.select_folder(folder_name, readonly=True)
                    criteria = self._build_search_criteria(
                        account=account,
                        flt=filter,
                        text=search,
                        partner_id=partner_id,
                        email_from=email_from,
                    )
                    page_uids, total = self._fast_search_uids(
                        client,
                        folder_name,
                        criteria,
                        offset,
                        limit,
                        is_all=(criteria == ["ALL"]),
                    )
                    records = self._fetch_list_records_parallel(
                        client=client,
                        uids=page_uids,
                        folder=folder,
                        account=account,
                        partner_cache=partner_cache,
                    )
                    self._cache_imap_records(account, folder_name, records)
                    records = self._apply_state_overlays(
                        account, folder_name, records
                    )
                records, total = self._apply_overrides_and_tags(
                    account, folder, records, total, tag_ids
                )
                records.sort(
                    key=lambda r: (_safe_dt(r), str(r.get("uid") or 0)),
                    reverse=True,
                )
                msg_ids = [r["message_id_norm"] for r in records if r.get("message_id_norm")]
                tmap = self._get_tags_for_message_ids(account.id, msg_ids)
                for r in records:
                    r["tag_ids"] = tmap.get(r["message_id_norm"], [])

            if folder.folder_type == "drafts":
                Draft = self.env["maildesk.draft"].sudo()
                domain = [
                    ("account_id", "=", account.id),
                    ("user_id", "=", self.env.user.id),
                ]
                if search:
                    s = search.strip()
                    if s:
                        domain += [
                            "|",
                            "|",
                            ("subject", "ilike", s),
                            ("to_emails", "ilike", s),
                            ("body_html", "ilike", s),
                        ]
                total_local = Draft.search_count(domain)
                drafts = Draft.search(
                    domain,
                    order="write_date desc, id desc",
                )

                for d in drafts:
                    dt = d.write_date or d.create_date
                    if dt:
                        dt_ctx = fields.Datetime.context_timestamp(self, dt)
                        formatted_date = dt_ctx.strftime("%d %b %Y %H:%M")
                    else:
                        formatted_date = ""
                    
                    preview_src = d.body_html or ""
                    preview = self._strip_html_to_text(preview_src)[:120]

                    email_from_val = (account.email or "").lower()

                    to_list = [
                        x.strip()
                        for x in (d.to_emails or "").split(",")
                        if x.strip()
                    ]
                    cc_list = [
                        x.strip()
                        for x in (d.cc_emails or "").split(",")
                        if x.strip()
                    ]
                    bcc_list = [
                        x.strip()
                        for x in (d.bcc_emails or "").split(",")
                        if x.strip()
                    ]

                    records.append(
                        {
                            "id": d.id,
                            "account_id": [account.id, account.name],
                            "folder_id": folder.id,
                            "subject": d.subject or "",
                            "email_from": email_from_val,
                            "sender_display_name": (
                                d.sender_display_name
                                or self._format_sender_display(account.sender_name or account.name, email_from_val)
                            ),
                            "date": dt,
                            "is_internal_draft": True,
                            "formatted_date": formatted_date,
                            "is_read": False,
                            "is_draft": True,
                            "is_starred": False,
                            "tag_ids": [],
                            "has_attachments": bool(d.attachment_ids),
                            "to_display": ", ".join(to_list),
                            "cc_display": ", ".join(cc_list),
                            "bcc_display": ", ".join(bcc_list),
                            "preview_text": preview,
                            "avatar_html": self._avatar_html(email_from_val, False),
                            "avatar_partner_id": False,
                            "message_id_norm": d.message_id or "",
                            "is_local_draft": True,
                        }
                    )

                total = int(total or 0) + int(total_local or 0)
                records.sort(
                    key=lambda r: (_safe_dt(r), int(r.get("uid") or 0) if r.get("uid") else 0),
                    reverse=True,
                )

            return {"records": records, "totalMessagesCount": total}

        if account_id:
            accounts = Account.browse([account_id])
        else:
            accounts = self._user_accounts()
        if not accounts:
            return {"records": [], "totalMessagesCount": 0}

        need = offset + limit
        collected = []
        total_count_approx = 0

        for acc in accounts:
            try:
                if self._is_gmail_account(acc):
                    service = self._gmail_build_service(acc)
                    base_q = gmail_q(acc)
                    q_all = (f"{base_q} -in:trash -in:spam").strip() if base_q else "-in:trash -in:spam"
                    ids_page, total = self._gmail_list_message_ids(service, acc, folder=None, q=q_all, offset=0, limit=need)
                    recs = self._gmail_fetch_meta_batch(service, acc, folder=False, ids=ids_page, partner_cache=partner_cache)
                    recs, total = self._apply_overrides_and_tags(acc, False, recs, total, tag_ids)
                    recs = self._apply_state_overlays(acc, None, recs)
                    collected.extend(recs)
                    total_count_approx += total

                elif self._is_outlook_account(acc):
                    sess, base = self._outlook_build_graph(acc)
                    if sess and base:
                        qd = self._outlook_query_from_filters(
                            account=acc, flt=filter, text=search, partner_id=partner_id, email_from=email_from
                        )
                        ids_page, total = self._outlook_list_message_ids(sess, base, acc, folder=None, qdict=qd, offset=0, limit=need)
                        recs = self._outlook_fetch_meta_batch(sess, base, acc, folder=False, ids=ids_page, partner_cache=partner_cache)
                        recs, total = self._apply_overrides_and_tags(acc, False, recs, total, tag_ids)
                        recs = self._apply_state_overlays(acc, None, recs)
                        collected.extend(recs)
                        total_count_approx += total
                else:
                    pool = get_pool(acc)
                    with pool.session() as client:
                        try:
                            caps = client.capabilities() or []
                            if b"UTF8=ACCEPT" in caps or "UTF8=ACCEPT" in caps:
                                client.enable("UTF8=ACCEPT")
                        except Exception:
                            pass
                        client.select_folder("INBOX", readonly=True)
                        criteria = self._build_search_criteria(
                            account=acc, flt=filter, text=search, partner_id=partner_id, email_from=email_from
                        )
                        page_uids, total = self._fast_search_uids(
                            client, "INBOX", criteria, offset=0, limit=need, is_all=(criteria == ["ALL"])
                        )
                        fld = Folder.search([("account_id", "=", acc.id), ("imap_name", "=", "INBOX")], limit=1) \
                            or Folder.search([("account_id", "=", acc.id), ("name", "=", "INBOX")], limit=1) \
                            or self.env["mailbox.folder"].browse(False)
                        recs = self._fetch_list_records_parallel(
                            client=client, uids=page_uids, folder=fld, account=acc, partner_cache=partner_cache
                        )
                        recs, total = self._apply_overrides_and_tags(acc, fld, recs, total, tag_ids)
                        recs = self._apply_state_overlays(acc, "INBOX", recs)
                        collected.extend(recs)
                        total_count_approx += total
            except Exception:
                continue

        collected.sort(
            key=lambda r: (_safe_dt(r), str(r.get("uid") or 0)),
            reverse=True
        )
        page = collected[offset : offset + limit]
        return {"records": page, "totalMessagesCount": total_count_approx}

    def _cache_imap_records(self, account, folder_name, records, ttl_minutes=60):
        Cache = self.env["maildesk.message_cache"].sudo()

        for r in records:
            uid = r.get("uid") or r.get("id")
            if not uid:
                continue

            flags = ""
            if r.get("is_read"):
                flags = (flags + " \\Seen").strip()
            if r.get("is_starred"):
                flags = (flags + " \\Flagged").strip()

            msg_id_norm = r.get("message_id_norm") or ""
            in_reply_to = r.get("in_reply_to") or ""
            references_hdr = r.get("references_hdr") or ""

            thread_id = r.get("thread_id") or msg_id_norm or ""
            thread_root_id = r.get("thread_root_id") or thread_id

            vals = {
                "subject": r.get("subject") or "",
                "from_addr": r.get("email_from") or "",
                "to_addrs": r.get("to_display") or "",
                "cc_addrs": r.get("cc_display") or "",
                "bcc_addrs": r.get("bcc_display") or "",
                "date": r.get("date") or False,
                "has_attachments": bool(r.get("has_attachments")),
                "preview": r.get("preview_text") or "",
                "sender_display_name": r.get("sender_display_name") or "",
                "flags": flags,

                "message_id": msg_id_norm,
                "in_reply_to": in_reply_to,
                "references_hdr": references_hdr,

                "thread_id": thread_id,
                "thread_root_id": thread_root_id,
            }

            Cache.upsert_meta(
                account_id=account.id,
                folder=folder_name,
                uid=str(uid),
                vals=vals,
                ttl_minutes=ttl_minutes,
            )

    def _format_sender_display(self, name, email):
        email = (email or "").strip().lower()
        name = (name or "").strip()
        if name and email:
            if email.lower() in name.lower():
                return name
            return f'"{name}" <{email}>'
        return email or name or ""

    def _fetch_list_records_parallel(self, client, uids, folder, account, partner_cache, batch_size=1, max_workers=1):
        if not uids:
            return []

        if self._is_gmail_account(account) or self._is_outlook_account(account):
            _logger.warning("_fetch_list_records_parallel called for non-IMAP account %s", account.id)
            return []

        folder_name = (folder.imap_name or folder.name)
        pool = get_pool(account)

        chunks = [uids[i:i + batch_size] for i in range(0, len(uids), batch_size)]
        _logger.info("Parallel fetch started → %d chunks (%d uids total)", len(chunks), len(uids))

        def _parse_header_block(hdr_text):
            headers = {}
            current = None
            for line in hdr_text.splitlines():
                if not line:
                    continue
                if line[0] in (" ", "\t") and current:
                    headers[current] += " " + line.strip()
                    continue
                m = re.match(r"^([^:]+):\s*(.*)$", line)
                if not m:
                    continue
                name = (m.group(1) or "").strip().lower()
                value = (m.group(2) or "").strip()
                headers[name] = value
                current = name
            return headers

        def imap_fetch_meta(chunk):
            to_fetch, metas = [], []
            cached_records = []

            for uid in chunk:
                k = f"{account.id}:{folder_name}:{uid}"
                rec = memcache_get(k)
                if rec:
                    cached_records.append(rec)
                else:
                    to_fetch.append(uid)

            if not to_fetch:
                return {"records": cached_records, "metas": metas}

            with pool.session() as c:
                c.select_folder(folder_name, readonly=True)
                try:
                    data = c.fetch(
                        to_fetch,
                        [
                            "ENVELOPE",
                            "FLAGS",
                            "UID",
                            "BODYSTRUCTURE",
                            "RFC822.SIZE",
                            "BODY.PEEK[TEXT]",
                            "BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO CC MESSAGE-ID IN-REPLY-TO REFERENCES)]",
                        ],
                    ) or {}
                except Exception as e:
                    _logger.warning("IMAP fetch failed: %s", e)
                    data = {}

            for uid in to_fetch:
                d = data.get(uid, {}) or {}
                env       = d.get(b"ENVELOPE")
                flags     = d.get(b"FLAGS", [])
                bs        = d.get(b"BODYSTRUCTURE")
                rfc_size  = int(d.get(b"RFC822.SIZE") or 0)
                hdr_bytes = d.get(
                    b"BODY[HEADER.FIELDS (SUBJECT FROM TO CC MESSAGE-ID IN-REPLY-TO REFERENCES)]",
                    b"",
                ) or b""
                hdr_text = hdr_bytes.decode("utf-8", "ignore")

                headers = _parse_header_block(hdr_text)

                raw_subject  = headers.get("subject", "") or ""
                raw_from     = headers.get("from", "") or ""
                raw_msgid    = headers.get("message-id", "") or ""
                raw_irt      = headers.get("in-reply-to", "") or ""
                raw_refs     = headers.get("references", "") or ""

                subject = self._decode_header_value(raw_subject.strip()) if raw_subject else ""
                if not subject:
                    env_subj = getattr(env, "subject", None) if env else ""
                    subject = self._decode_header_value(env_subj) or "(no subject)"

                sender_email = ""
                if raw_from:
                    _, _disp, sender_email = self._parse_sender_header(raw_from.strip())
                if not sender_email and env and getattr(env, "from_", None):
                    sender_email = self._addr_to_email(env.from_[0])

                msg_date = self._to_datetime(getattr(env, "date", None) if env else None)
                has_attachments = self._has_attachments_from_bodystructure(bs)
                to_display = self._join_addresses(getattr(env, "to", None) if env else None)
                cc_display = self._join_addresses(getattr(env, "cc", None) if env else None)

                body_bytes = d.get(b"BODY[TEXT]", b"")
                if not isinstance(body_bytes, (bytes, bytearray)):
                    body_bytes = b""

                blob = body_bytes
                preview_text = self._extract_imap_preview(blob, subject)

                message_id_norm = self._norm_msgid(raw_msgid)
                in_reply_to_norm = self._norm_msgid(raw_irt)

                references_norm = ""
                first_reference = ""
                if raw_refs:
                    ref_ids = re.findall(r"<([^>]+)>", raw_refs) or [raw_refs]
                    norm_refs = [self._norm_msgid(x) for x in ref_ids if x]
                    references_norm = " ".join([r for r in norm_refs if r])
                    first_reference = norm_refs[0] if norm_refs else ""

                thread_id = first_reference or in_reply_to_norm or message_id_norm

                metas.append(
                    (
                        uid,
                        {
                            "message_id": message_id_norm or "",
                            "subject": subject,
                            "from_addr": sender_email or "",
                            "to_addrs": to_display or "",
                            "cc_addrs": cc_display or "",
                            "date": msg_date,
                            "flags": " ".join(
                                sorted(
                                    f.decode("utf-8", "ignore")
                                    if isinstance(f, (bytes, bytearray))
                                    else str(f)
                                    for f in (flags or [])
                                )
                            ),
                            "has_attachments": bool(has_attachments),
                            "size": rfc_size,
                            "preview": preview_text or "",
                            "in_reply_to": raw_irt.strip() if raw_irt else "",
                            "references_hdr": raw_refs.strip() if raw_refs else "",
                            "in_reply_to_norm": in_reply_to_norm or "",
                            "references_norm": references_norm or "",
                            "thread_id": thread_id or "",
                        },
                    )
                )

            return {"records": cached_records, "metas": metas}

        metas, records = [], []
        uid_order = {u: i for i, u in enumerate(uids)}

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(imap_fetch_meta, ch) for ch in chunks]
            for f in as_completed(futs):
                r = f.result() or {}
                records.extend(r.get("records", []))
                metas.extend(r.get("metas", []))

        if metas:
            Cache = self.env["maildesk.message_cache"].sudo()
            msgid_map = {}

            cache_map = Cache.get_cache_map(account.id, folder_name, [uid for uid, _ in metas])

            for uid, meta in metas:
                c = cache_map.get(str(uid)) or cache_map.get(uid)
                if c and c.message_id:
                    msgid_map[self._norm_msgid(c.message_id)] = uid
                    continue
                if meta.get("message_id"):
                    msgid_map[meta["message_id"]] = uid

            for uid, meta in metas:
                email_from = (meta.get("from_addr") or "").lower()
                partner = partner_cache.get(email_from)
                if partner is None:
                    partner = self.env["res.partner"].search(
                        [("email", "=ilike", email_from)], limit=1
                    )
                    partner_cache[email_from] = partner

                flags = meta.get("flags") or ""
                is_read = bool(re.search(r"\\?Seen", flags, re.I))
                is_starred = bool(re.search(r"\\?Flagged", flags, re.I))
                is_draft = bool(re.search(r"\\?Draft", flags, re.I))

                sender_name = partner.name if partner else self._display_name_from_email(email_from)

                rec = {
                    "id": uid,
                    "account_id": [account.id, account.name],
                    "folder_id": folder.id if folder else False,
                    "subject": meta.get("subject") or "(no subject)",
                    "email_from": email_from,
                    "sender_display_name": self._format_sender_display(sender_name, email_from),
                    "date": meta.get("date"),
                    "formatted_date": (
                        fields.Datetime.context_timestamp(self, meta.get("date")).strftime("%d %b %Y %H:%M")
                        if meta.get("date")
                        else ""
                    ),
                    "is_read": is_read,
                    "tag_ids": [],
                    "has_attachments": bool(meta.get("has_attachments")),
                    "to_display": meta.get("to_addrs") or "",
                    "cc_display": meta.get("cc_addrs") or "",
                    "is_draft": is_draft,
                    "is_starred": is_starred,
                    "preview_text": meta.get("preview") or "",
                    "avatar_html": self._avatar_html(email_from, partner),
                    "avatar_partner_id": partner.id if partner else False,
                    "message_id_norm": meta.get("message_id") or "",
                    "in_reply_to": meta.get("in_reply_to") or "",
                    "references_hdr": meta.get("references_hdr") or "",
                    "thread_id": meta.get("thread_id") or "",
                }

                parent_key = self._norm_msgid(meta.get("in_reply_to_norm") or "")
                if not parent_key:
                    refs_norm = (meta.get("references_norm") or "").strip()
                    if refs_norm:
                        parent_key = refs_norm.split()[0]
                if parent_key:
                    p_uid = msgid_map.get(parent_key)
                    if p_uid and p_uid != uid:
                        rec["parent_id"] = p_uid

                records.append(rec)
                memcache_set(f"{account.id}:{folder_name}:{uid}", rec, ttl=3600)

        records.sort(key=lambda r: uid_order.get(r["id"], 999999))
        _logger.info("Parallel fetch done → %d records", len(records))
        return records

    def _sanitize_email_html(self, html):
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "iframe", "object", "embed"]):
            tag.decompose()
        for tag in soup.find_all(True):
            attrs = dict(tag.attrs)
            for attr_name in list(attrs.keys()):
                if attr_name.lower().startswith("on"):
                    tag.attrs.pop(attr_name, None)
            for key in ("href", "src"):
                if key in tag.attrs:
                    val = tag.attrs.get(key) or ""
                    if isinstance(val, str) and val.strip().lower().startswith("javascript:"):
                        tag.attrs[key] = "#"
            style_val = tag.attrs.get("style")
            if isinstance(style_val, str):
                low = style_val.lower()
                if "expression(" in low or "javascript:" in low:
                    tag.attrs.pop("style", None)
            if tag.name == "a":
                tag.attrs["target"] = "_blank"
                rel = tag.attrs.get("rel")
                if isinstance(rel, list):
                    rel_tokens = set(rel)
                elif isinstance(rel, str):
                    rel_tokens = set(rel.split())
                else:
                    rel_tokens = set()
                rel_tokens.update(["noopener", "noreferrer"])
                tag.attrs["rel"] = " ".join(sorted(rel_tokens))
        return str(soup)

    @api.model
    def get_message_with_attachments(self, params):
        if isinstance(params, list) and params:
            params = params[0]

        message_uid = params.get("uid")
        folder_id = params.get("folder_id")
        account_id = params.get("account_id")
        backend_type = params.get("backend")
        is_internal_draft = params.get("is_internal_draft")

        Folder = self.env["mailbox.folder"]
        Cache = self.env["maildesk.message_cache"].sudo()
        Draft = self.env["maildesk.draft"].sudo()

        folder = Folder.browse(folder_id) if folder_id else None

        # ---------- internal draft ----------
        if is_internal_draft:
            try:
                did = int(message_uid)
            except Exception:
                _logger.warning("Draft open: invalid draft id %s", message_uid)
                return {}

            draft = Draft.browse(did).exists()
            if not draft:
                _logger.warning("Draft open: draft not found id=%s", did)
                return {}

            account = draft.account_id
            self._check_account_access(account)

            dt = draft.write_date or draft.create_date
            if dt:
                dt_ctx = fields.Datetime.context_timestamp(self, dt)
                formatted_date = dt_ctx.strftime("%d %b %Y %H:%M")
            else:
                formatted_date = ""

            email_from_val = (account.email or "").lower()

            partner = self.env["res.partner"].search(
                [("email", "=ilike", email_from_val)], limit=1
            )
            partner_trusted = bool(partner.trusted_partner) if partner else False
            trusted_by_user_id = (
                partner.trusted_by_user_id.id
                if partner and partner.trusted_by_user_id
                else False
            )

            to_display = draft.to_emails or ""
            cc_display = draft.cc_emails or ""
            bcc_display = draft.bcc_emails or ""

            try:
                body_plain = ""
                if draft.body_html:
                    try:
                        body_plain = BeautifulSoup(draft.body_html or "", "lxml").get_text(
                            "\n", strip=True
                        )
                    except Exception:
                        body_plain = BeautifulSoup(
                            draft.body_html or "", "html.parser"
                        ).get_text("\n", strip=True)
            except Exception:
                body_plain = (draft.body_html or "")[:1024]

            attachments_json = []
            for a in draft.attachment_ids:
                attachments_json.append(
                    {
                        "type": "binary",
                        "id": a.id,
                        "name": a.name,
                        "mimetype": a.mimetype,
                        "urlRoute": "/web/content",
                        "urlQueryParams": {"id": a.id, "download": "false"},
                        "defaultSource": f"/web/content/{a.id}",
                        "downloadUrl": f"/web/content/{a.id}?download=true",
                    }
                )

            sender_name = (
                partner.name if partner else self._display_name_from_email(email_from_val)
            )
            
            message_vals = {
                "id": draft.id,
                "subject": draft.subject or "",
                "email_from": email_from_val,
                "date": dt,
                "formatted_date": formatted_date,
                "body_original": self._sanitize_email_html(draft.body_html or ""),
                "body_plain": body_plain or "",
                "is_read": False,
                "is_starred": False,
                "has_attachments": bool(attachments_json),
                "attachments": attachments_json,
                "account_display": (
                    f"{account.name} | {account.email}"
                    if account.name != account.email
                    else (account.email or "")
                ),
                "to_display": to_display,
                "cc_display": cc_display,
                "bcc_display": bcc_display,
                "account_id": [account.id, account.name],
                "model": draft.model or False,
                "res_id": draft.res_id or False,
                "is_draft": True,
                "is_local_draft": True,
                "avatar_html": self._avatar_html(email_from_val, partner),
                "avatar_partner_id": partner.id if partner else False,
                "tag_ids": [],
                "sender_display_name": (
                    draft.sender_display_name
                    or self._format_sender_display(
                        account.sender_name or account.name, email_from_val
                    )
                ),
                "partner_trusted": partner_trusted,
                "trusted_by_user_id": trusted_by_user_id,
                "in_reply_to": draft.reply_to_message_id or "",
                "message_id": draft.message_id or "",
                "message_id_norm": draft.message_id or "",
                "parent_chain": False,
            }

            return message_vals

        # ---------- resolve account / folder ----------
        if folder:
            account = folder.account_id
            folder_name = folder.imap_name or folder.name
        else:
            cache_rec = Cache.search([("uid", "=", str(message_uid))], limit=1)
            if cache_rec:
                account = cache_rec.account_id
                folder_name = cache_rec.folder or "INBOX"
            elif account_id:
                account = self.env["mailbox.account"].browse(account_id).exists()
                folder_name = "INBOX"
            else:
                _logger.warning(
                    "get_message_with_attachments: no folder/cache and no account_id for uid=%s",
                    message_uid,
                )
                return {}

        if not account:
            _logger.warning("No account found")
            return {}

        # ---------- Gmail ----------
        if self._is_gmail_account(account):
            service = self._gmail_build_service(account)
            rec = (
                self._gmail_get_message_full(service, account, folder, str(message_uid))
                or {}
            )

            partner_id = rec.get("avatar_partner_id")
            if partner_id:
                partner = self.env["res.partner"].browse(partner_id).exists()
                if partner:
                    rec["partner_trusted"] = bool(partner.trusted_partner)
                    rec["trusted_by_user_id"] = (
                        partner.trusted_by_user_id.id
                        if partner.trusted_by_user_id
                        else False
                    )

            if "message_id_norm" not in rec and rec.get("message_id"):
                rec["message_id_norm"] = rec["message_id"]

            body_html = rec.get("body_original") or rec.get("body_html") or ""
            rec["body_original"] = self._replace_cid_src(
                body_html,
                rec.get("attachments") or [],
            )
            rec["body_original"] = self._sanitize_email_html(rec["body_original"])

            m, r = self._find_linked_document(
                rec.get("message_id_norm"),
                rec.get("in_reply_to"),
            )
            rec["model"] = m
            rec["res_id"] = r
            return self._enrich_full_record_with_tags(account, rec)

        # ---------- Outlook ----------
        if self._is_outlook_account(account):
            sess, base = self._outlook_build_graph(account)
            if re.fullmatch(r"\d+", str(message_uid)):
                _logger.warning(
                    "Outlook get: numeric UID %s → not a valid Graph ID", message_uid
                )
                return {}

            rec = (
                self._outlook_get_message_full(
                    sess, base, account, folder, str(message_uid)
                )
                or {}
            )

            partner_id = rec.get("avatar_partner_id")
            if partner_id:
                partner = self.env["res.partner"].browse(partner_id).exists()
                if partner:
                    rec["partner_trusted"] = bool(partner.trusted_partner)
                    rec["trusted_by_user_id"] = (
                        partner.trusted_by_user_id.id
                        if partner.trusted_by_user_id
                        else False
                    )

            if "message_id_norm" not in rec and rec.get("message_id"):
                rec["message_id_norm"] = rec["message_id"]

            body_html = rec.get("body_original") or rec.get("body_html") or ""
            rec["body_original"] = self._replace_cid_src(
                body_html,
                rec.get("attachments") or [],
            )
            rec["body_original"] = self._sanitize_email_html(rec["body_original"])

            m, r = self._find_linked_document(
                rec.get("message_id_norm"),
                rec.get("in_reply_to"),
            )
            rec["model"] = m
            rec["res_id"] = r
            return self._enrich_full_record_with_tags(account, rec)

        # ---------- plain IMAP ----------
        def _get_delim(client):
            try:
                ns = client.namespace()
                for grp in ns or []:
                    for _, d in grp or []:
                        if d:
                            return d
            except Exception:
                pass
            try:
                res = client.list_folders("", "")
                if res and len(res[0]) >= 2 and res[0][1]:
                    return res[0][1]
            except Exception:
                pass
            return "/"

        def _safe_select(client, name):
            try:
                return client.select_folder(name, readonly=True)
            except Exception as e1:
                _logger.warning("SELECT failed for '%s': %s", name, e1)
                try:
                    delim = _get_delim(client) or "/"
                    alt = (name or "").replace("\\", delim).replace("/", delim)
                    if alt and alt != name:
                        return client.select_folder(alt, readonly=True)
                except Exception as e2:
                    _logger.warning("SELECT retry failed: %s", e2)
                return False

        pool = get_pool(account)
        returned = None

        try:
            with pool.session() as client:
                if not _safe_select(client, folder_name):
                    _logger.warning(
                        "IMAP get_message_with_attachments: cannot SELECT folder %s for uid=%s",
                        folder_name,
                        message_uid,
                    )
                    return {}

                if not re.fullmatch(r"\d+", str(message_uid or "")):
                    _logger.warning(
                        "IMAP get_message_with_attachments: non-numeric UID %s "
                        "for account %s folder %s – skipping",
                        message_uid,
                        account.id if account else "?",
                        folder_name,
                    )
                    return {}

                uid_int = int(message_uid)
                uids = [uid_int]

                fetch_parts = [
                    "ENVELOPE",
                    "FLAGS",
                    "UID",
                    "BODYSTRUCTURE",
                    "RFC822.SIZE",
                    "INTERNALDATE",
                ]
                try:
                    header_data = client.fetch(uids, fetch_parts) or {}
                except Exception as e:
                    _logger.warning("HEADER fetch failed uid=%s: %s", uid_int, e)
                    return {}

                try:
                    full_data = client.fetch(uids, ["BODY.PEEK[]"]) or {}
                except Exception as e:
                    _logger.warning("FULL fetch failed uid=%s: %s", uid_int, e)
                    full_data = {}

                partner_cache = {}
                cache_map = Cache.get_cache_map(account.id, folder_name, uids)

                for uid in uids:
                    hd = header_data.get(uid, {}) or {}
                    fd = full_data.get(uid, {}) or {}
                    env = hd.get(b"ENVELOPE")
                    flags = hd.get(b"FLAGS", []) or []
                    bs = hd.get(b"BODYSTRUCTURE")
                    blob = fd.get(b"BODY[]", b"")
                    if not blob:
                        continue
                            
                    try:
                        msg = message_from_bytes(blob, policy=policy.default)
                    except Exception as e:
                        _logger.warning("Parse failed UID %s: %s", uid, e)
                        continue
                    
                    raw_msg_id = msg["Message-ID"] or ""
                    raw_in_reply = msg["In-Reply-To"] or ""
                    raw_refs_list = msg.get_all("References", []) or []
                    msg_id_norm = self._norm_msgid(raw_msg_id)
                    in_reply_norm = self._norm_msgid(raw_in_reply)
                    refs_norm = " ".join(
                        self._norm_msgid(x) for x in raw_refs_list if x
                    )

                    cache_rec = cache_map.get(uid)

                    subject = (
                        cache_rec.subject
                        if cache_rec
                        else self._decode_header_value(msg["Subject"] or "")
                        or "(no subject)"
                    )

                    sender_email = ""
                    from_header = msg["From"]
                    if (
                        from_header
                        and hasattr(from_header, "addresses")
                        and from_header.addresses
                    ):
                        parsed_from = from_header.addresses[0]
                        sender_email = (parsed_from.addr_spec or "").lower()
                    elif from_header:
                        sender_email = str(from_header)
                    if not sender_email and env and getattr(env, "from_", None):
                        sender_email = self._addr_to_email(env.from_[0])

                    msg_date = self._to_datetime(
                        msg["Date"] or getattr(env, "date", None)
                    )

                    if cache_rec:
                        to_display = cache_rec.to_addrs or ""
                        cc_display = cache_rec.cc_addrs or ""
                        bcc_display = cache_rec.bcc_addrs or ""
                    else:
                        to_display = self._join_addresses(
                            getattr(env, "to", None) if env else None
                        )
                        cc_display = self._join_addresses(
                            getattr(env, "cc", None) if env else None
                        )
                        bcc_display = self._join_addresses(
                            getattr(env, "bcc", None) if env else None
                        )

                    body_html = ""
                    body_plain = ""
                    try:
                        if msg.is_multipart():
                            for part in msg.walk():
                                ctype = (part.get_content_type() or "").lower()
                                if ctype == "text/html":
                                    try:
                                        body_html += part.get_content()
                                    except Exception:
                                        body_html += (
                                            part.get_payload(decode=True) or b""
                                        ).decode("utf-8", "ignore")
                                elif ctype == "text/plain":
                                    try:
                                        body_plain += part.get_content()
                                    except Exception:
                                        body_plain += (
                                            part.get_payload(decode=True) or b""
                                        ).decode("utf-8", "ignore")
                        else:
                            ctype = (msg.get_content_type() or "").lower()
                            payload = (msg.get_payload(decode=True) or b"").decode(
                                "utf-8", "ignore"
                            )
                            if ctype == "text/html":
                                body_html = payload
                            else:
                                body_plain = payload
                    except Exception as e:
                        _logger.warning("Body parse failed UID %s: %s", uid, e)

                    if not body_html and body_plain:
                        safe_plain = html_escape(body_plain)
                        body_html = "<p style='white-space: pre-wrap; margin:0;'>" + safe_plain + "</p>"

                    if sender_email not in partner_cache:
                        partner_cache[sender_email] = self.env[
                            "res.partner"
                        ].search([("email", "=ilike", sender_email)], limit=1)
                    partner = partner_cache[sender_email]

                    partner_trusted = bool(partner.trusted_partner) if partner else False
                    trusted_by_user_id = (
                        partner.trusted_by_user_id.id
                        if partner and partner.trusted_by_user_id
                        else False
                    )

                    has_attachments_flag = (
                        cache_rec.has_attachments
                        if cache_rec
                        else self._has_attachments_from_bodystructure(bs)
                    )

                    attachments_json = []
                    part_index = 0
                    for part in msg.iter_attachments():
                        part_index += 1
                        name = part.get_filename() or "attachment"
                        mimetype = part.get_content_type() or "application/octet-stream"
                        payload = part.get_payload(decode=True) or b""
                        size = len(payload)
                        content_id = (part.get("Content-ID") or "").strip("<>")

                        external_id = (
                            f"imap-{account.id}-{folder_name}-{uid}-{part_index}"
                        )
                        preview_url = (
                            f"/maildesk/imap_attachment/{account.id}/"
                            f"{folder_name}/{uid}/{part_index}"
                        )
                        download_url = f"{preview_url}?download=1"

                        info = self._build_external_attachment(
                            name=name,
                            mimetype=mimetype,
                            size=size,
                            preview_url=preview_url,
                            download_url=download_url,
                            external_id=external_id,
                            content_id=content_id,
                        )
                        attachments_json.append(info)

                    has_attachments_real = bool(attachments_json)
                    if not has_attachments_real and has_attachments_flag:
                        has_attachments_real = True

                    if cache_rec:
                        cache_rec.write({"has_attachments": has_attachments_real})
                    else:
                        cache_rec = Cache.create(
                            {
                                "account_id": account.id,
                                "folder": folder_name,
                                "uid": uid,
                                "subject": subject,
                                "from_addr": sender_email,
                                "date": msg_date,
                                "has_attachments": has_attachments_real,
                                "to_addrs": to_display,
                                "cc_addrs": cc_display,
                                "bcc_addrs": bcc_display,
                                "message_id": msg_id_norm,
                                "in_reply_to": in_reply_norm,
                                "references_hdr": refs_norm,
                                "thread_id": in_reply_norm or msg_id_norm,
                                "thread_root_id": in_reply_norm or msg_id_norm,
                                "body_html": body_html,
                                "body_text": body_plain,
                            }
                        )

                    body_html_resolved = self._replace_cid_src(
                        body_html, attachments_json
                    )
                    sender_name = (
                        partner.name
                        if partner
                        else self._display_name_from_email(sender_email)
                    )

                    rec = {
                        "id": uid,
                        "subject": subject,
                        "email_from": (sender_email or "").lower(),
                        "date": msg_date,
                        "formatted_date": (
                            fields.Datetime.context_timestamp(
                                self, msg_date
                            ).strftime("%d %b %Y %H:%M")
                            if msg_date
                            else ""
                        ),
                        "body_original": body_html_resolved,
                        "body_plain": body_plain,
                        "is_read": b"\\Seen" in flags,
                        "is_starred": b"\\Flagged" in flags,
                        "has_attachments": has_attachments_real,
                        "attachments": attachments_json,
                        "account_display": (
                            f"{account.name} | {account.email}"
                            if account.name != account.email
                            else account.email
                        ),
                        "to_display": to_display or "",
                        "cc_display": cc_display or "",
                        "bcc_display": bcc_display or "",
                        "account_id": [account.id, account.name],
                        "model": False,
                        "res_id": False,
                        "is_draft": b"\\Draft" in flags,
                        "avatar_html": self._avatar_html(sender_email, partner),
                        "avatar_partner_id": partner.id if partner else False,
                        "tag_ids": [],
                        "sender_display_name": self._format_sender_display(
                            sender_name, sender_email
                        ),
                        "partner_trusted": partner_trusted,
                        "trusted_by_user_id": trusted_by_user_id,
                        "in_reply_to": in_reply_norm,
                        "message_id": msg_id_norm,
                        "message_id_norm": msg_id_norm,
                    }
                    
                    returned = rec
                    break
        except Exception as e:
            _logger.warning(
                "IMAP get_message_with_attachments failed for uid=%s account=%s: %s",
                message_uid,
                account.id if account else "?",
                e,
            )
            return {}

        if not returned:
            return {}

        State = self.env["maildesk.email_state"].sudo()
        st = State.search(
            [
                ("account_id", "=", account.id),
                ("folder", "=", folder_name),
                ("uid", "=", str(message_uid)),
            ],
            limit=1,
        )
        if st:
            if st.seen is not None:
                returned["is_read"] = bool(st.seen)
            if st.starred is not None:
                returned["is_starred"] = bool(st.starred)

        m, r = self._find_linked_document(
            returned.get("message_id_norm"),
            returned.get("in_reply_to"),
        )
        returned["model"] = m
        returned["res_id"] = r

        returned = self._enrich_full_record_with_tags(account, returned)
        returned["body_original"] = self._sanitize_email_html(returned["body_original"])
        return returned

    @api.model
    def _build_thread_lazy(self, account, folder_name, msg_id, checked_folders=None, chain=None):
        if not msg_id:
            return chain or []

        Cache = self.env["maildesk.message_cache"].sudo()
        Folder = self.env["mailbox.folder"]
        pool = get_pool(account)

        if chain is None:
            chain = []
        if checked_folders is None:
            checked_folders = set()

        with pool.session() as client:
            try:
                client.select_folder(folder_name, readonly=True)
                uids = client.search(["HEADER", "Message-ID", f"<{msg_id}>"]) or []
            except Exception:
                uids = []

            if uids:
                uid = uids[0]

                folder_rec = Folder.search([
                    ("account_id", "=", account.id),
                    "|", ("imap_name", "=", folder_name),
                        ("name", "=", folder_name),
                ], limit=1)

                full = self.get_message_with_attachments({
                    "uid": uid,
                    "folder_id": folder_rec.id or False,
                    "account_id": account.id,
                })
                if full:
                    Cache.upsert_meta(
                        account_id=account.id,
                        folder=folder_name,
                        uid=uid,
                        vals={
                            "subject": full.get("subject"),
                            "from_addr": full.get("email_from"),
                            "date": full.get("date"),
                            "to_addrs": full.get("to_display"),
                            "cc_addrs": full.get("cc_display"),
                            "bcc_addrs": full.get("bcc_display"),
                            "has_attachments": full.get("has_attachments"),
                            "body_html": full.get("body_original"),
                            "body_text": full.get("body_plain"),
                            "message_id": full.get("message_id"),
                            "sender_display_name": full.get("sender_display_name"),
                            "avatar_html": full.get("avatar_html"),
                        },
                        ttl_minutes=60,
                    )

                    chain.append(full)
                    next_id = full.get("in_reply_to") or ""
                    if next_id:
                        return self._build_thread_lazy(account, folder_name, next_id, checked_folders, chain)
                    return chain

        TOP_FOLDERS = [
            "INBOX", "Sent", "Gesendet", "Gesendete Objekte",
            "Archive", "Archives", "Drafts", "Entwürfe",
            "Trash", "Gelöscht", "Gelöschte Objekte", "Papierkorb",
        ]
        if folder_name not in TOP_FOLDERS:
            TOP_FOLDERS.insert(0, folder_name)

        folders = Folder.search([
            ("account_id", "=", account.id),
            ("imap_name", "in", TOP_FOLDERS),
        ])

        for f in folders:
            if f.imap_name in checked_folders:
                continue
            checked_folders.add(f.imap_name)

            with pool.session() as client:
                try:
                    client.select_folder(f.imap_name, readonly=True)
                    uids = client.search(["HEADER", "Message-ID", f"<{msg_id}>"]) or []
                except Exception:
                    uids = []

            if not uids:
                continue

            uid = uids[0]
            full = self.get_message_with_attachments({
                "uid": uid,
                "folder_id": f.id,
                "account_id": account.id,
            })
            if not full:
                continue

            Cache.upsert_meta(
                account_id=account.id,
                folder=f.imap_name,
                uid=uid,
                vals={
                    "subject": full.get("subject"),
                    "from_addr": full.get("email_from"),
                    "date": full.get("date"),
                    "to_addrs": full.get("to_display"),
                    "cc_addrs": full.get("cc_display"),
                    "bcc_addrs": full.get("bcc_display"),
                    "has_attachments": full.get("has_attachments"),
                    "body_html": full.get("body_original"),
                    "body_text": full.get("body_plain"),
                    "message_id": full.get("message_id"),
                    "sender_display_name": full.get("sender_display_name"),
                    "avatar_html": full.get("avatar_html"),
                },
                ttl_minutes=60,
            )

            chain.append(full)
            next_id = full.get("in_reply_to") or ""
            if next_id:
                return self._build_thread_lazy(account, f.imap_name, next_id, checked_folders, chain)

        return chain

    def _imap_unread_counts(self, account, folder_name, criteria):
        pool = get_pool(account)
        with pool.session(ensure_selected=folder_name, readonly=True) as c:
            st = c.folder_status(folder_name, ['UNSEEN'])
            unread_total = int(st.get(b'UNSEEN') or st.get('UNSEEN') or 0)
            crit_unread = ['UNSEEN'] + [x for x in (criteria or []) if x != 'ALL']

            try:
                raw_caps = c.capabilities() or []
                caps = set()
                for x in raw_caps:
                    if isinstance(x, (bytes, bytearray)):
                        caps.add(x.decode().upper())
                    elif isinstance(x, str):
                        caps.add(x.upper())
            except Exception as e:
                caps = set()

            charset = None
            flat = " ".join(map(str, crit_unread)).upper()
            if 'UTF8=ACCEPT' in caps and any(
                k in flat for k in ('TEXT', 'FROM', 'TO', 'CC', 'BCC', 'SUBJECT')
            ):
                charset = 'UTF-8'

            try:
                uids = c.search(crit_unread, charset=charset) or []
                unread_filtered = len(uids)
            except Exception as e:
                unread_filtered = unread_total

        return unread_total, unread_filtered

    @api.model
    def _fetch_single_from_server(self, account_id, uid):
        Account = self.env["mailbox.account"].browse(int(account_id))
        if not Account:
            return {}
        uid_s = str(uid)

        if self._is_gmail_account(Account):
            service = self._gmail_build_service(Account)
            m = service.users().messages().get(userId="me", id=uid_s, format="full").execute()
            payload = m.get("payload", {}) or {}
            headers = {h["name"].lower(): h.get("value","") for h in payload.get("headers",[]) if "name" in h}
            subject = headers.get("subject","") or ""
            from_ = headers.get("from","")
            to_ = headers.get("to","")
            date_ = headers.get("date","")
            def _walk(parts):
                for p in parts or []:
                    yield p
                    yield from _walk(p.get("parts") or [])
            body_html, body_text, has_atts = "", "", False
            if payload:
                parts = list(_walk(payload.get("parts") or [])) or [payload]
                for p in parts:
                    mime = (p.get("mimeType") or "").lower()
                    body = p.get("body") or {}
                    data = body.get("data")
                    if data:
                        raw = base64.urlsafe_b64decode(data.encode())
                        if mime == "text/html":
                            body_html += raw.decode("utf-8","ignore")
                        elif mime == "text/plain":
                            body_text += raw.decode("utf-8","ignore")
                    if (body.get("attachmentId") or p.get("filename")):
                        has_atts = True
            return {
                "subject": subject,
                "from": from_,
                "to": to_,
                "date": date_,
                "body_html": body_html,
                "body_text": body_text,
                "attachments": [] if not has_atts else [{}],
            }

        if self._is_outlook_account(Account):
            sess, base = self._outlook_build_graph(Account)
            url = f"{base}/messages/{uid_s}"
            r = sess.get(url)
            r.raise_for_status()
            m = r.json()
            subject = m.get("subject","")
            from_ = (m.get("from",{}) or {}).get("emailAddress",{}).get("address","")
            to_ = ", ".join([(p.get("emailAddress",{}) or {}).get("address","") for p in (m.get("toRecipients") or [])])
            date_ = m.get("receivedDateTime") or m.get("sentDateTime") or ""
            body = m.get("body",{}) or {}
            content_type = (body.get("contentType") or "").lower()
            content = body.get("content") or ""
            body_html = content if content_type == "html" else ""
            body_text = content if content_type != "html" else ""
            has_atts = bool(m.get("hasAttachments"))
            return {
                "subject": subject,
                "from": from_,
                "to": to_,
                "date": date_,
                "body_html": body_html,
                "body_text": body_text,
                "attachments": [] if not has_atts else [{}],
            }

        account = Account
        pool = get_pool(account)
        folder_name = "INBOX"

        if not re.fullmatch(r"\d+", uid_s):
            _logger.warning(
                "_fetch_single_from_server(IMAP): non-numeric UID %s for account %s – skipping",
                uid_s,
                account.id,
            )
            return {}
        
        with pool.session(ensure_selected=folder_name, readonly=True) as c:
            data = c.fetch([int(uid_s)], [b'BODY[]', b'BODYSTRUCTURE', b'ENVELOPE']) or {}
            d = data.get(int(uid_s), {}) or {}
            raw = d.get(b'BODY[]') or b''
            has_atts = self._has_attachments_from_bodystructure(d.get(b'BODYSTRUCTURE'))

        body_html, body_text, subject, from_, to_, date_ = "", "", "", "", "", ""
        if raw:
            msg = message_from_bytes(raw, policy=policy.default)
            subject = str(msg.get('Subject','') or '')
            from_ = str(msg.get('From','') or '')
            to_ = str(msg.get('To','') or '')
            date_ = str(msg.get('Date','') or '')
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = (part.get_content_type() or "").lower()
                    if ctype == "text/html":
                        try: body_html += part.get_content()
                        except: body_html += (part.get_payload(decode=True) or b'').decode('utf-8','ignore')
                    elif ctype == "text/plain":
                        try: body_text += part.get_content()
                        except: body_text += (part.get_payload(decode=True) or b'').decode('utf-8','ignore')
            else:
                ctype = (msg.get_content_type() or "").lower()
                payload = (msg.get_payload(decode=True) or b'').decode('utf-8','ignore')
                if ctype == "text/html": body_html = payload
                else: body_text = payload
        return {
            "subject": subject,
            "from": from_,
            "to": to_,
            "date": date_,
            "body_html": body_html,
            "body_text": body_text,
            "attachments": [] if not has_atts else [{}],
        }

    @api.model
    def get_message_attachments(self, account_id, folder, uid):
        Cache = self.env["maildesk.message_cache"].sudo()
        rec = Cache.search([("account_id","=",account_id), ("folder","=",folder), ("uid","=",str(uid))], limit=1)
        if not rec:
            return []
        atts = rec._prepare_attachments()
        if atts:
            return atts
        folder_rec = self.env["mailbox.folder"].search([
            ("account_id", "=", account_id),
            "|", ("imap_name", "=", folder),
                ("name", "=", folder),
        ], limit=1)

        full = self.get_message_with_attachments({
            "uid": str(uid),
            "folder_id": folder_rec.id or False,
            "account_id": account_id,
        }) or {}
        blobs = full.get("attachments") or []
        out = []
        for b in blobs:
            content = b.get("content")
            name = b.get("name") or "file"
            mimetype = b.get("mimetype") or "application/octet-stream"
            if not content:
                continue
            att = self.env["ir.attachment"].sudo().create({
                "name": name,
                "datas": content,
                "mimetype": mimetype,
                "res_model": rec._name,
                "res_id": rec.id,
            })
            out.append({
                "type": "binary",
                "id": att.id,
                "name": att.name,
                "mimetype": att.mimetype,
                "urlRoute": "/web/content",
                "urlQueryParams": {"id": att.id, "download": "false"},
                "defaultSource": f"/web/content/{att.id}",
                "downloadUrl": f"/web/content/{att.id}?download=true",
            })
        return out

    def _enrich_full_record_with_tags(self, account, rec):
        if not rec:
            return rec

        Tag = self.env["mail.message.tag"].sudo()
        Link = self.env["mail.message.tag.link"].sudo()

        msg_id = rec.get("message_id_norm") or rec.get("message_id") or ""
        if not msg_id:
            rec["tag_ids"] = []
            return rec

        links = Link.search_read(
            [("account_id", "=", account.id), ("message_id", "=", msg_id)],
            ["tag_id"]
        )

        tag_ids = [l["tag_id"][0] for l in links if l.get("tag_id")]

        if tag_ids:
            tags = Tag.browse(tag_ids)
            tags_info = tags.read(["name", "color"])
            rec["tag_ids"] = [
                {"id": t["id"], "name": t["name"], "color": t["color"]}
                for t in tags_info
            ]
        else:
            rec["tag_ids"] = []

        return rec

    def _attachment_common_info(self, name, mime):
        viewable = {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            "application/pdf",
        }

        ext = (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
        icon_mime = mime or "application/octet-stream"

        mime_to_ext = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/svg+xml": "svg",
            "application/pdf": "pdf",
            "application/javascript": "js",
            "text/x-python": "py",
            "application/zip": "zip",
            "application/x-rar-compressed": "rar",
            "video/mp4": "mp4",
            "audio/mpeg": "mp3",
            "text/csv": "csv",
            "application/msword": "doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "application/vnd.ms-powerpoint": "ppt",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
            "application/vnd.ms-excel": "xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
            "text/html": "html",
            "application/json": "json",
        }
        if not ext and mime:
            ext = mime_to_ext.get(mime, "")

        extension_map = {
            "psd": "image/vnd.adobe.photoshop",
            "zip": "application/zip",
            "rar": "application/x-rar-compressed",
            "mp4": "video/mp4",
            "mp3": "audio/mpeg",
            "csv": "text/csv",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "ppt": "application/vnd.ms-powerpoint",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "html": "text/html",
            "json": "application/json",
            "js": "application/javascript",
            "py": "text/x-python",
            "pdf": "application/pdf",
        }

        if not mime or mime == "application/octet-stream":
            icon_mime = extension_map.get(ext, "application/octet-stream")

        return {
            "name": name,
            "filename": name,
            "mimetype": mime or "application/octet-stream",
            "icon_mimetype": icon_mime,
            "extension": ext,
            "isImage": icon_mime.startswith("image/") and icon_mime in viewable,
            "isPdf": icon_mime == "application/pdf",
            "isViewable": icon_mime in viewable,
            "uploading": False,
            "isDeletable": False,
        }

    def _build_external_attachment(self, *, name, mimetype, size, preview_url, download_url, external_id, content_id=None):
        info = self._attachment_common_info(name, mimetype)
        info.update(
            {
                "type": "external",
                "urlRoute": preview_url,
                "urlQueryParams": {},
                "defaultSource": preview_url if info["isViewable"] else None,
                "downloadUrl": download_url,
                "size": size or 0,
                "id": external_id,
                "content_id": content_id or "",
            }
        )
        return info
    
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL

    def _is_gmail_account(self, account):
        srv = account.mail_server_id.sudo()
        return bool(srv) and srv.server_type == "gmail"

    def _gmail_build_service(self, account):
        srv = account.mail_server_id.sudo()
        srv._generate_oauth2_string(srv.user, srv.google_gmail_refresh_token)

        token = srv.google_gmail_access_token
        refresh = srv.google_gmail_refresh_token

        Config = self.env['ir.config_parameter'].sudo()
        client_id = Config.get_param('google_gmail_client_id')
        client_secret = Config.get_param('google_gmail_client_secret')

        creds = Credentials(
            token=token,
            refresh_token=refresh,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GMAIL_SCOPES,
        )

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _gmail_query_from_filters(self, account=None, flt=None, text=None, partner_id=None, email_from=None):
        parts = []
        me = (account.email or "").strip().lower() if account else ""
        if flt == "unread":
            parts.append("is:unread")
        elif flt == "starred":
            parts.append("is:starred")
        elif flt == "incoming":
            if me:
                parts.append(f"-from:{me}")
        elif flt == "outgoing":
            if me:
                parts.append(f"from:{me}")
        if partner_id and not email_from:
            partner = self.env["res.partner"].browse(partner_id)
            if partner and partner.email:
                email_from = partner.email
        if email_from:
            parts.append(f"from:{email_from}")
        if text:
            s = re.sub(r"\s+", " ", text.strip())
            if s:
                parts.append(s)
        return " ".join(parts).strip()

    def _gmail_label_ids_for_folder(self, service, account, folder):
        if not folder:
            return None

        local_name = (folder.imap_name or folder.name or "").strip()
        norm = local_name.lower().replace("[gmail]/", "").strip()

        sys_map = {
            "inbox": "INBOX",
            "sent": "SENT",
            "sent mail": "SENT",
            "important": "IMPORTANT",
            "trash": "TRASH",
            "bin": "TRASH",
            "deleted": "TRASH",
            "draft": "DRAFT",
            "drafts": "DRAFT",
            "spam": "SPAM",
            "starred": "STARRED",
        }

        if norm in sys_map:
            return [sys_map[norm]]

        lbls = service.users().labels().list(userId="me").execute().get("labels", [])
        for lbl in lbls:
            if lbl["name"].lower() == local_name.lower():
                return [lbl["id"]]

        return None

    def _gmail_list_message_ids(self, service, account, folder, q, offset, limit):
        label_ids = self._gmail_label_ids_for_folder(service, account, folder)

        need = max(0, (offset or 0) + (limit or 0))
        if need <= 0:
            return [], 0

        if label_ids and len(label_ids) == 1 and not q:
            page_ids = []
            params = {
                "userId": "me",
                "maxResults": min(500, need),
                "includeSpamTrash": False,
                "labelIds": label_ids,
                "fields": "nextPageToken,messages/id",
            }
            req = service.users().messages().list(**params)
            while req is not None and len(page_ids) < need:
                resp = req.execute()
                msgs = resp.get("messages", []) or []
                page_ids.extend([m["id"] for m in msgs])
                npt = resp.get("nextPageToken")
                if not npt:
                    break
                params["pageToken"] = npt
                req = service.users().messages().list(**params)

            if offset >= len(page_ids):
                return [], 0
            return page_ids[offset:offset + limit], 0

        all_ids = []
        params = {
            "userId": "me",
            "maxResults": 500,
            "includeSpamTrash": False,
            "fields": "nextPageToken,messages/id",
        }
        if q:
            params["q"] = q
        if label_ids:
            params["labelIds"] = label_ids

        req = service.users().messages().list(**params)
        while req is not None and len(all_ids) < need:
            resp = req.execute()
            msgs = resp.get("messages", []) or []
            all_ids.extend([m["id"] for m in msgs])
            npt = resp.get("nextPageToken")
            if not npt:
                break
            params["pageToken"] = npt
            req = service.users().messages().list(**params)

        if offset >= len(all_ids):
            return [], 0
        return all_ids[offset:offset + limit], 0

    def _gmail_fetch_meta_batch(self, service, account, folder, ids, partner_cache):
        if not ids:
            return []

        results = {}

        def _cb(request_id, response, exception):
            if exception is None:
                results[request_id] = response

        for i in range(0, len(ids), 50):
            batch = service.new_batch_http_request(callback=_cb)
            for mid in ids[i:i + 50]:
                batch.add(
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="full",
                    ),
                    request_id=mid,
                )
            batch.execute()

        def _payload_has_attachments(payload):
            if not payload:
                return False
            stack = [payload]
            while stack:
                p = stack.pop()
                body = p.get("body") or {}
                filename = (p.get("filename") or "").strip()
                if filename or body.get("attachmentId"):
                    return True
                parts = p.get("parts") or []
                stack.extend(parts)
            return False

        records = []
        fld = folder or False
        Cache = self.env["maildesk.message_cache"].sudo()
        folder_name = (
            getattr(fld, "imap_name", None)
            or getattr(fld, "name", None)
            or "ALL_MAIL"
        )

        for mid in ids:
            m = results.get(mid)
            if not m:
                continue

            payload = m.get("payload") or {}
            payload_headers = {
                (h.get("name") or "").lower(): (h.get("value") or "")
                for h in (payload.get("headers") or [])
            }
            label_ids = set(m.get("labelIds") or [])

            ts_raw = m.get("internalDate") or "0"
            try:
                ts = int(ts_raw)
            except Exception:
                ts = 0
            if ts:
                dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).replace(tzinfo=None)
            else:
                dt = datetime(1970, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)

            _, disp_name, email_from = self._parse_sender_header(
                payload_headers.get("from") or ""
            )
            email_from = (email_from or "").lower()

            partner = partner_cache.get(email_from)
            if partner is None:
                partner = self.env["res.partner"].search(
                    [("email", "=ilike", email_from)], limit=1
                )
                partner_cache[email_from] = partner

            raw_subject = payload_headers.get("subject") or ""
            subject = self._decode_header_value(raw_subject) or "(no subject)"

            is_unread = "UNREAD" in label_ids
            is_starred = "STARRED" in label_ids

            has_atts = _payload_has_attachments(payload)

            message_id_norm = (payload_headers.get("message-id") or "").strip()

            to_display = self._decode_header_value(payload_headers.get("to") or "")
            cc_display = self._decode_header_value(payload_headers.get("cc") or "")
            bcc_display = self._decode_header_value(payload_headers.get("bcc") or "")

            sender_name = partner.name if partner else self._display_name_from_email(email_from)
            rec = {
                "id": m.get("id"),
                "account_id": [account.id, account.name],
                "folder_id": (fld.id if fld else False),
                "subject": subject,
                "email_from": email_from,
                "sender_display_name": self._format_sender_display(sender_name, email_from),
                "date": dt,
                "formatted_date": fields.Datetime.context_timestamp(self, dt).strftime(
                    "%d %b %Y %H:%M"
                )
                if dt
                else "",
                "is_read": not is_unread,
                "tag_ids": [],
                "has_attachments": has_atts,
                "to_display": to_display,
                "cc_display": cc_display,
                "is_draft": "DRAFT" in label_ids,
                "is_starred": is_starred,
                "preview_text": (m.get("snippet") or "")[:120],
                "avatar_html": self._avatar_html(email_from, partner),
                "avatar_partner_id": partner.id if partner else False,
                "message_id_norm": message_id_norm,
            }
            records.append(rec)

            Cache.upsert_meta(
                account_id=account.id,
                folder=folder_name,
                uid=str(mid),
                vals={
                    "subject": subject,
                    "from_addr": email_from,
                    "date": dt,
                    "to_addrs": to_display,
                    "cc_addrs": cc_display,
                    "bcc_addrs": bcc_display,
                    "has_attachments": has_atts,
                    "flags": (
                        ("\\Seen" if rec["is_read"] else "")
                        + (" \\Flagged" if rec["is_starred"] else "")
                    ),
                    "preview": rec["preview_text"],
                    "sender_display_name": rec["sender_display_name"],
                    "message_id": message_id_norm,
                    "in_reply_to": (payload_headers.get("in-reply-to") or "").strip(),
                    "references_hdr": (payload_headers.get("references") or "").strip(),
                    "thread_id": m.get("threadId") or "",
                    "thread_root_id": m.get("threadId") or "",
                },
                ttl_minutes=60,
            )

            memcache_set(f"{account.id}:{folder_name}:{mid}", rec, ttl=3600)

        return records

    def _gmail_get_message_full(self, service, account, folder, message_id):
        LOGP = "[GMAIL msg_full]"

        _logger.info(
            "%s start message_id=%s account_id=%s folder=%s",
            LOGP, message_id, getattr(account, "id", None), folder
        )

        meta = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Subject"],
        ).execute()
        thread_id = meta.get("threadId")

        chain = self._gmail_get_thread_full(
            service, account, thread_id, include_bodies=True
        )

        cur = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        payload = cur.get("payload", {}) or {}
        headers_list = payload.get("headers") or []
        headers = {
            (h.get("name") or "").lower(): (h.get("value") or "")
            for h in headers_list
        }
        labels = set(cur.get("labelIds") or [])
        ts = int(cur.get("internalDate") or "0")
        if ts:
            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        else:
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)

        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        )

        def _hdr_from_part(h_list, name):
            name = (name or "").lower()
            for h in h_list or []:
                if (h.get("name") or "").lower() == name:
                    return h.get("value") or ""
            return ""

        def _content_id(h_list):
            v = _hdr_from_part(h_list, "content-id")
            return v.strip("<>").strip() if v else ""

        def _disp_token(h_list):
            v = _hdr_from_part(h_list, "content-disposition")
            return (v.split(";", 1)[0].strip().lower() if v else "")

        def _add_text(html_ref, text_ref, mime, raw_bytes):
            if not raw_bytes:
                return html_ref, text_ref
            mime = (mime or "").lower()
            if mime.startswith("text/html"):
                html_ref += raw_bytes.decode("utf-8", "ignore")
            elif mime.startswith("text/plain") and not text_ref:
                text_ref = raw_bytes.decode("utf-8", "ignore")
            return html_ref, text_ref

        _, disp_name, email_from = self._parse_sender_header(
            headers.get("from") or ""
        )
        email_from = (email_from or "").lower()

        partner = self.env["res.partner"].search(
            [("email", "=ilike", email_from)], limit=1
        )
        _logger.info(
            "%s partner.lookup email=%s found=%s",
            LOGP, email_from, bool(partner)
        )

        html_body = ""
        text_body = ""
        attachments = []

        stack = [payload] if payload else []
        while stack:
            part = stack.pop()
            subparts = part.get("parts")
            if subparts:
                stack.extend(subparts)
                continue

            mime = (part.get("mimeType") or "").lower()
            body = part.get("body") or {}
            data = body.get("data")
            att_id = body.get("attachmentId")
            filename = (part.get("filename") or "").strip()
            part_headers = part.get("headers") or []
            disp_tok = _disp_token(part_headers)

            if mime == "message/rfc822":
                raw_eml = b""
                if data:
                    try:
                        raw_eml = base64.urlsafe_b64decode(data.encode("utf-8"))
                    except Exception:
                        raw_eml = b""

                if att_id and not raw_eml:
                    name = filename or "message.eml"
                    full_mime = mime or "message/rfc822"
                    size = body.get("size") or 0
                    cid = _content_id(part_headers)
                    preview_url = (
                        "/maildesk/attachment/show"
                        f"?mid={cur['id']}&aid={att_id}&account_id={account.id}"
                        f"&mimetype={full_mime}"
                    )
                    download_url = (
                        f"{base_url}/maildesk/attachment/download"
                        f"?mid={cur['id']}&aid={att_id}&account_id={account.id}"
                        f"&mimetype={full_mime}&name={url_quote(name)}"
                    )
                    external_id = f"gmail-{account.id}-{cur['id']}-{att_id}"

                    info = self._build_external_attachment(
                        name=name,
                        mimetype=full_mime,
                        size=size,
                        preview_url=preview_url,
                        download_url=download_url,
                        external_id=external_id,
                        content_id=cid,
                    )
                    info["defaultSource"] = None
                    attachments.append(info)
                    continue

                if raw_eml:
                    try:
                        em = message_from_bytes(raw_eml, policy=policy.default)

                        def walk_em(msg):
                            if msg.is_multipart():
                                for sp in msg.iter_parts():
                                    yield from walk_em(sp)
                            else:
                                yield msg

                        for sp in walk_em(em):
                            smime = (sp.get_content_type() or "").lower()
                            raw = sp.get_payload(decode=True) or b""
                            html_body, text_body = _add_text(
                                html_body, text_body, smime, raw
                            )
                    except Exception as e:
                        _logger.info("%s rfc822.parse error: %s", LOGP, e)
                continue

            if att_id and mime.startswith("text/") and disp_tok != "attachment":
                try:
                    fetched = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=message_id, id=att_id)
                        .execute()
                    )
                    raw_b64 = fetched.get("data")
                    raw = (
                        base64.urlsafe_b64decode(raw_b64.encode("utf-8"))
                        if raw_b64
                        else b""
                    )
                except Exception:
                    raw = b""
                html_body, text_body = _add_text(html_body, text_body, mime, raw)
                continue

            if data and mime.startswith("text/"):
                try:
                    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
                except Exception:
                    raw = b""
                html_body, text_body = _add_text(html_body, text_body, mime, raw)
                continue

            if att_id and filename:
                full_mime = part.get("mimeType") or "application/octet-stream"
                size = body.get("size") or 0
                cid = _content_id(part_headers)
                name = filename or "attachment"

                preview_url = (
                    "/maildesk/attachment/show"
                    f"?mid={cur['id']}&aid={att_id}&account_id={account.id}"
                    f"&mimetype={full_mime}"
                )
                download_url = (
                    f"{base_url}/maildesk/attachment/download"
                    f"?mid={cur['id']}&aid={att_id}&account_id={account.id}"
                    f"&mimetype={full_mime}&name={url_quote(name)}"
                )
                external_id = f"gmail-{account.id}-{cur['id']}-{att_id}"

                info = self._build_external_attachment(
                    name=name,
                    mimetype=full_mime,
                    size=size,
                    preview_url=preview_url,
                    download_url=download_url,
                    external_id=external_id,
                    content_id=cid,
                )
                attachments.append(info)
                continue

        if not html_body and text_body:
            html_body = "<pre>" + Markup.escape(text_body) + "</pre>"
        if not html_body and not text_body:
            snippet = (cur.get("snippet") or "").strip()
            if snippet:
                text_body = snippet

        sender_name = partner.name if partner else self._display_name_from_email(email_from)
        rec = {
            "id": cur["id"],
            "subject": headers.get("subject") or "(no subject)",
            "email_from": email_from,
            "sender_display_name": self._format_sender_display(sender_name, email_from),
            "date": dt,
            "formatted_date": fields.Datetime.context_timestamp(self, dt).strftime(
                "%d %b %Y %H:%M"
            ),
            "body_original": html_body
            or (("<pre>" + Markup.escape(text_body) + "</pre>") if text_body else ""),
            "body_plain": (
                text_body
                or (
                    self._strip_html_to_text(html_body)
                    if html_body
                    else (cur.get("snippet") or "")
                )
            ),
            "is_read": "UNREAD" not in labels,
            "is_starred": "STARRED" in labels,
            "has_attachments": bool(attachments or ("HAS_ATTACHMENTS" in labels)),
            "attachments": attachments,
            "to_display": self._decode_header_value(headers.get("to") or ""),
            "cc_display": self._decode_header_value(headers.get("cc") or ""),
            "bcc_display": self._decode_header_value(headers.get("bcc") or ""),
            "account_id": [account.id, account.name],
            "avatar_html": self._avatar_html(email_from, partner),
            "avatar_partner_id": partner.id if partner else False,
            "model": False,
            "res_id": False,
            "tag_ids": False,
            "in_reply_to": (headers.get("in-reply-to") or "").strip(),
            "message_id": (headers.get("message-id") or "").strip(),
        }

        def _norm_mid(x):
            return (x or "").strip().lower()

        def _build_ancestors_only(thread_msgs, cur_in_reply_to):
            by_mid = {
                _norm_mid(m.get("message_id")): m
                for m in (thread_msgs or [])
                if m.get("message_id")
            }
            res, seen = [], set()
            mid = _norm_mid(cur_in_reply_to)
            while mid and mid not in seen:
                seen.add(mid)
                m = by_mid.get(mid)
                if not m:
                    break
                res.append(m)
                mid = _norm_mid(m.get("in_reply_to"))
            res.sort(
                key=lambda m: (
                    fields.Datetime.to_datetime(m.get("date") or "1970-01-01").replace(
                        tzinfo=None
                    )
                    if m.get("date")
                    else datetime(1970, 1, 1)
                ),
                reverse=True,
            )
            return res

        chain_wo_current = [r for r in (chain or []) if r.get("id") != message_id]
        ancestors = _build_ancestors_only(chain_wo_current, rec.get("in_reply_to"))
        rec["parent_chain"] = ancestors or False

        Cache = self.env["maildesk.message_cache"].sudo()
        folder_name = (
            getattr(folder, "imap_name", None)
            or getattr(folder, "name", None)
            or "ALL_MAIL"
        )

        cache_rec = Cache.upsert_meta(
            account_id=account.id,
            folder=folder_name,
            uid=message_id,
            vals={
                "subject": rec["subject"],
                "from_addr": rec["email_from"],
                "date": rec["date"],
                "to_addrs": rec["to_display"],
                "cc_addrs": rec["cc_display"],
                "bcc_addrs": rec["bcc_display"],
                "has_attachments": rec["has_attachments"],
                "flags": (
                    ("\\Seen" if rec["is_read"] else "")
                    + (" \\Flagged" if rec["is_starred"] else "")
                ),
                "preview": rec["body_plain"][:200] or rec["subject"],
                "sender_display_name": rec["sender_display_name"],
                "message_id": rec["message_id"],
                "in_reply_to": rec["in_reply_to"],
                "references_hdr": "",
                "thread_id": cur.get("threadId") or "",
                "thread_root_id": cur.get("threadId") or "",
            },
            ttl_minutes=60,
        )

        if cache_rec:
            cache_rec.set_body_cache(
                html=rec["body_original"],
                text=rec["body_plain"],
                minutes=self._body_ttl_minutes(),
            )

        _logger.info(
            "%s done | html_len=%d plain_len=%d atts=%d labels=%s",
            LOGP,
            len(rec["body_original"] or ""),
            len(rec["body_plain"] or ""),
            len(attachments),
            list(labels)[:6],
        )

        memcache_set(f"{account.id}:{folder_name}:{message_id}", rec, ttl=3600)
        return rec

    def _gmail_get_thread_full(self, service, account, thread_id, include_bodies=False):
        LOGP = "[GMAIL thread_full]"

        cache_key = f"gmail:thread:{account.id}:{thread_id}:{int(include_bodies)}"
        cached = memcache_get(cache_key)
        if cached:
            _logger.info(
                "%s cache HIT account_id=%s thread_id=%s include_bodies=%s msgs=%s",
                LOGP,
                getattr(account, "id", None),
                thread_id,
                include_bodies,
                len(cached),
            )
            return cached

        _logger.info(
            "%s start account_id=%s thread_id=%s include_bodies=%s",
            LOGP,
            getattr(account, "id", None),
            thread_id,
            include_bodies,
        )

        t = service.users().threads().get(
            userId="me",
            id=thread_id,
            format="full" if include_bodies else "metadata",
        ).execute()

        def _add_text(html_body_ref, text_body_ref, mime, raw_bytes):
            if not raw_bytes:
                return html_body_ref, text_body_ref
            mime = (mime or "").lower()
            if mime.startswith("text/html"):
                html_body_ref += raw_bytes.decode("utf-8", "ignore")
            elif mime.startswith("text/plain") and not text_body_ref:
                text_body_ref = raw_bytes.decode("utf-8", "ignore")
            return html_body_ref, text_body_ref

        def _content_id(headers_list):
            try:
                for h in headers_list or []:
                    if (h.get("name") or "").lower() == "content-id":
                        v = (h.get("value") or "").strip()
                        return v.strip("<>").strip()
            except Exception:
                pass
            return ""

        def _disp_token(headers_list):
            try:
                for h in headers_list or []:
                    if (h.get("name") or "").lower() == "content-disposition":
                        v = (h.get("value") or "").strip()
                        return (v.split(";", 1)[0] or "").strip().lower()
            except Exception:
                pass
            return ""

        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        )

        msgs = t.get("messages", []) or []
        _logger.info("%s thread contains messages=%d", LOGP, len(msgs))

        out = []
        partner_cache = {}

        for m in msgs:
            payload = m.get("payload", {}) or {}
            headers_list = payload.get("headers") or []
            hs = {
                (h.get("name") or "").lower(): (h.get("value") or "")
                for h in headers_list
            }

            lbls = set(m.get("labelIds") or [])
            ts = int(m.get("internalDate") or "0")
            if ts:
                dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).replace(tzinfo=None)
            else:
                dt = datetime(1970, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)

            _, disp_name, email_from = self._parse_sender_header(
                hs.get("from") or ""
            )
            email_from = (email_from or "").lower()

            partner = partner_cache.get(email_from)
            if partner is None:
                partner = self.env["res.partner"].search(
                    [("email", "=ilike", email_from)], limit=1
                )
                partner_cache[email_from] = partner

            html_body = ""
            text_body = ""
            attachments = []
            has_atts = "HAS_ATTACHMENTS" in lbls

            if include_bodies:
                stack = [payload] if payload else []
                while stack:
                    p = stack.pop()
                    subparts = p.get("parts")
                    if subparts:
                        stack.extend(subparts)
                        continue

                    mime = (p.get("mimeType") or "").lower()
                    body = p.get("body") or {}
                    data = body.get("data")
                    att_id = body.get("attachmentId")
                    filename = (p.get("filename") or "").strip()
                    p_headers = p.get("headers") or []
                    disp_tok = _disp_token(p_headers)

                    if mime == "message/rfc822":
                        raw_eml = b""

                        if data:
                            try:
                                raw_eml = base64.urlsafe_b64decode(data.encode("utf-8"))
                            except Exception:
                                raw_eml = b""

                        if att_id and not raw_eml:
                            name = filename or "message.eml"
                            full_mime = mime or "message/rfc822"
                            size = body.get("size") or 0
                            cid = _content_id(p_headers)

                            preview_url = (
                                "/maildesk/attachment/show"
                                f"?mid={m['id']}&aid={att_id}&account_id={account.id}"
                                f"&mimetype={full_mime}"
                            )
                            download_url = (
                                f"{base_url}/maildesk/attachment/download"
                                f"?mid={m['id']}&aid={att_id}&account_id={account.id}"
                                f"&mimetype={full_mime}&name={url_quote(name)}"
                            )
                            external_id = f"gmail-{account.id}-{m['id']}-{att_id}"

                            info = self._build_external_attachment(
                                name=name,
                                mimetype=full_mime,
                                size=size,
                                preview_url=preview_url,
                                download_url=download_url,
                                external_id=external_id,
                                content_id=cid,
                            )
                            info["defaultSource"] = None
                            attachments.append(info)
                            has_atts = True
                            continue

                        if raw_eml:
                            try:
                                em = message_from_bytes(raw_eml, policy=policy.default)

                                def walk_em(msg):
                                    if msg.is_multipart():
                                        for sp in msg.iter_parts():
                                            yield from walk_em(sp)
                                    else:
                                        yield msg

                                for sp in walk_em(em):
                                    smime = (sp.get_content_type() or "").lower()
                                    raw = sp.get_payload(decode=True) or b""
                                    html_body, text_body = _add_text(
                                        html_body, text_body, smime, raw
                                    )
                            except Exception as e:
                                _logger.info("%s rfc822.parse error: %s", LOGP, e)
                        continue

                    if att_id and mime.startswith("text/") and disp_tok != "attachment":
                        try:
                            fetched = (
                                service.users()
                                .messages()
                                .attachments()
                                .get(userId="me", messageId=m["id"], id=att_id)
                                .execute()
                            )
                            raw_b64 = fetched.get("data")
                            raw = (
                                base64.urlsafe_b64decode(raw_b64.encode("utf-8"))
                                if raw_b64
                                else b""
                            )
                        except Exception:
                            raw = b""
                        html_body, text_body = _add_text(
                            html_body, text_body, mime, raw
                        )
                        continue

                    if data and mime.startswith("text/"):
                        try:
                            raw = base64.urlsafe_b64decode(data.encode("utf-8"))
                        except Exception:
                            raw = b""
                        html_body, text_body = _add_text(
                            html_body, text_body, mime, raw
                        )
                        continue

                    if att_id and filename:
                        has_atts = True
                        full_mime = mime or "application/octet-stream"
                        size = body.get("size") or 0
                        cid = _content_id(p_headers)
                        name = filename or "attachment"

                        preview_url = (
                            "/maildesk/attachment/show"
                            f"?mid={m['id']}&aid={att_id}&account_id={account.id}"
                            f"&mimetype={full_mime}"
                        )
                        download_url = (
                            f"{base_url}/maildesk/attachment/download"
                            f"?mid={m['id']}&aid={att_id}&account_id={account.id}"
                            f"&mimetype={full_mime}&name={url_quote(name)}"
                        )
                        external_id = f"gmail-{account.id}-{m['id']}-{att_id}"

                        info = self._build_external_attachment(
                            name=name,
                            mimetype=full_mime,
                            size=size,
                            preview_url=preview_url,
                            download_url=download_url,
                            external_id=external_id,
                            content_id=cid,
                        )
                        attachments.append(info)
                        continue

                if not html_body and text_body:
                    html_body = "<pre>" + Markup.escape(text_body) + "</pre>"
                if not html_body and not text_body:
                    snip = (m.get("snippet") or "").strip()
                    if snip:
                        text_body = snip

            sender_name = partner.name if partner else self._display_name_from_email(email_from)
            rec = {
                "id": m["id"],
                "threadId": t["id"],
                "subject": hs.get("subject") or "(no subject)",
                "email_from": email_from,
                "sender_display_name": self._format_sender_display(sender_name, email_from),
                "date": dt,
                "formatted_date": fields.Datetime.context_timestamp(self, dt).strftime(
                    "%d %b %Y %H:%M"
                ),
                "body_original": (html_body if include_bodies else ""),
                "body_plain": (
                    text_body
                    or (
                        self._strip_html_to_text(html_body)
                        if include_bodies and html_body
                        else (m.get("snippet") or "")
                    )
                ),
                "is_read": "UNREAD" not in lbls,
                "is_starred": "STARRED" in lbls,
                "has_attachments": bool(
                    has_atts or (attachments if include_bodies else [])
                ),
                "attachments": (attachments if include_bodies else []),
                "to_display": self._decode_header_value(hs.get("to") or ""),
                "cc_display": self._decode_header_value(hs.get("cc") or ""),
                "bcc_display": self._decode_header_value(hs.get("bcc") or ""),
                "account_id": [account.id, account.name],
                "avatar_html": "",
                "avatar_partner_id": False,
                "in_reply_to": hs.get("in-reply-to") or "",
                "message_id": hs.get("message-id") or "",
            }

            rec = self._enrich_partner_meta(rec)

            out.append(rec)

        out.sort(key=lambda x: x["date"], reverse=True)

        memcache_set(cache_key, out, ttl=300)
        _logger.info(
            "%s done msgs=%d include_bodies=%s",
            LOGP,
            len(out),
            include_bodies,
        )
        return out

    def _gmail_unread_counts(self, service, account, folder, q):
        folder_name = (folder.imap_name or folder.name or "").strip()
        norm = folder_name.lower().replace("[gmail]/", "").strip()

        SYSTEM_LABELS = {
            "inbox": "INBOX",
            "sent": "SENT",
            "sent mail": "SENT",
            "important": "IMPORTANT",
            "trash": "TRASH",
            "bin": "TRASH",
            "deleted": "TRASH",
            "draft": "DRAFT",
            "drafts": "DRAFT",
            "spam": "SPAM",
            "starred": "STARRED",
        }

        if norm in SYSTEM_LABELS:
            label_id = SYSTEM_LABELS[norm]
            try:
                lab = service.users().labels().get(userId="me", id=label_id).execute()
                unread_total = int(lab.get("messagesUnread") or 0)
            except Exception:
                unread_total = 0
        else:
            unread_total = None

        if unread_total is None:
            if norm in SYSTEM_LABELS:
                folder_filter = f"in:{norm}"
            else:
                folder_filter = f'label:"{folder_name}"'

            total_q = f'is:unread {folder_filter} -in:spam -in:trash'

            cnt_total = 0
            params = {
                "userId": "me",
                "q": total_q,
                "maxResults": 500,
                "includeSpamTrash": False,
                "fields": "nextPageToken,messages/id",
            }
            req = service.users().messages().list(**params)

            while req is not None:
                resp = req.execute()
                cnt_total += len(resp.get("messages", []) or [])
                npt = resp.get("nextPageToken")
                if not npt:
                    break
                params["pageToken"] = npt
                req = service.users().messages().list(**params)

            unread_total = cnt_total

        q_unread = (q or "").strip()
        if "is:unread" not in q_unread:
            q_unread = "is:unread " + q_unread

        if norm in SYSTEM_LABELS:
            q_unread = f"in:{norm} " + q_unread
        else:
            q_unread = f'label:"{folder_name}" ' + q_unread

        cnt_filtered = 0
        params = {
            "userId": "me",
            "q": q_unread,
            "maxResults": 500,
            "includeSpamTrash": False,
            "fields": "nextPageToken,messages/id",
        }

        req = service.users().messages().list(**params)
        while req is not None:
            resp = req.execute()
            cnt_filtered += len(resp.get("messages", []) or [])
            npt = resp.get("nextPageToken")
            if not npt:
                break
            params["pageToken"] = npt
            req = service.users().messages().list(**params)

        return unread_total, cnt_filtered

    def _enrich_partner_meta(self, rec):
        email = (rec.get("email_from") or "").strip().lower()
        partner = self.env["res.partner"].search([("email", "=ilike", email)], limit=1)

        rec["avatar_partner_id"] = partner.id if partner else False
        rec["partner_trusted"] = bool(partner.trusted_partner) if partner else False

        rec["trusted_by_user_id"] = (
            partner.trusted_by_user_id.id if partner and partner.trusted_by_user_id else False
        )

        rec["avatar_html"] = self._avatar_html(email, partner)

        rec["message_id_norm"] = self._norm_msgid(rec.get("message_id") or "")
        rec["in_reply_to"] = rec.get("in_reply_to") or ""
        rec["in_reply_to_norm"] = self._norm_msgid(rec["in_reply_to"])

        return rec

    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL
    # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL # GMAIL GMAIL GMAIL

    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK

    def _is_outlook_account(self, account):
        srv = account.mail_server_id.sudo()
        return bool(srv) and (srv.server_type or "").lower() == "outlook"

    def _outlook_access_token(self, acc):
        server = acc.mail_server_id.sudo()
        _ = server._generate_outlook_oauth2_string(acc.email or server.user)
        return server.microsoft_outlook_access_token
    
    def _outlook_build_graph(self, account):
        if not account or not account.id:
            return None, None

        server = account.mail_server_id.sudo()
        if not server or (server.server_type or "").lower() != "outlook":
            return None, None

        Config = self.env["ir.config_parameter"].sudo()
        client_id = (Config.get_param("microsoft_outlook_client_id") or "").strip()
        client_secret = (Config.get_param("microsoft_outlook_client_secret") or "").strip()
        tenant = (Config.get_param("microsoft_outlook_tenant", "common") or "").strip()

        if not (client_id and client_secret):
            raise UserError(_("Outlook Graph is not configured. Please set Client Id and Client Secret."))

        refresh_token = (server.microsoft_outlook_refresh_token or "").strip()
        if not refresh_token:
            raise UserError(_("Please connect with your Outlook account before using it."))

        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant}",
        )

        result = app.acquire_token_by_refresh_token(
            refresh_token,
            scopes=GRAPH_SCOPES,
        )

        if "access_token" not in result:
            err_desc = (result.get("error_description") or str(result)).strip()
            err_code = (result.get("error") or "").lower()

            if (
                "invalid_grant" in err_code
                or "interaction_required" in err_code
                or "consent" in err_desc.lower()
                or "aadsts65001" in err_desc.lower()
            ):
                raise UserError(_("Outlook Graph session expired. Please reconnect your Outlook account."))

            raise UserError(_("An error occurred when contacting Microsoft Graph: %s") % err_desc)

        access_token = result["access_token"]
        new_rt = (result.get("refresh_token") or refresh_token).strip()

        if new_rt and new_rt != refresh_token:
            server.write({
                "microsoft_outlook_refresh_token": new_rt,
            })

        sess = requests.Session()
        sess.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Prefer": 'IdType="ImmutableId"',
        })
        return sess, GRAPH_BASE_URL

    def _outlook_query_from_filters(self, account=None, flt=None, text=None, partner_id=None, email_from=None):
        search_q = None
        filter_parts = []
        sender = (account.email or "").lower() if account else ""

        if flt == "unread":
            filter_parts.append("isRead eq false")
        elif flt == "starred":
            filter_parts.append("flag/flagStatus eq 'flagged'")
        elif flt == "incoming" and sender:
            filter_parts.append(f"from/emailAddress/address ne '{sender}'")
        elif flt == "outgoing" and sender:
            filter_parts.append(f"from/emailAddress/address eq '{sender}'")

        if partner_id and not email_from:
            p = self.env["res.partner"].browse(partner_id)
            if p and p.email:
                email_from = p.email

        if email_from:
            addr = (email_from or "").lower().strip()
            search_q = f"\"{addr}\""

        if text:
            s = re.sub(r"\s+", " ", text.strip())
            if s:
                if search_q:
                    search_q += f" OR \"{s}\""
                else:
                    search_q = f"\"{s}\""

        return {
            "$search": search_q,
            "$filter": " and ".join(filter_parts) if filter_parts else None,
        }

    def _outlook_unread_counts(
        self, sess, base_url, account, folder,
        flt=None, text=None, partner_id=None, email_from=None,
    ):
        if not sess or not base_url:
            return 0, 0

        try:
            folder_id = self._outlook_resolve_folder_id(sess, base_url, folder)
        except Exception as e:
            _logger.warning("Outlook unread_counts: resolve folder failed: %s", e)
            return 0, 0

        unread_total = 0
        try:
            url_folder = f"{base_url}/me/mailFolders/{folder_id}"
            r = sess.get(url_folder, params={"$select": "unreadItemCount"}, timeout=30)
            if r.status_code == 200:
                unread_total = int((r.json().get("unreadItemCount") or 0))
            else:
                _logger.warning(
                    "Outlook unread_counts: folder request %s -> %s",
                    url_folder, r.status_code
                )
        except Exception as e:
            _logger.warning("Outlook unread_counts: unread_total failed: %s", e)
            unread_total = 0

        unread_filtered = unread_total
        try:
            qdict = self._outlook_query_from_filters(
                account=account, flt=flt, text=text,
                partner_id=partner_id, email_from=email_from
            )

            filter_expr = qdict.get("$filter") or ""
            if "isRead" not in filter_expr:
                if filter_expr:
                    filter_expr = f"{filter_expr} and isRead eq false"
                else:
                    filter_expr = "isRead eq false"

            search_q = qdict.get("$search") or None

            url_count = f"{base_url}/me/mailFolders/{folder_id}/messages/$count"
            params = {}
            headers = {}

            if filter_expr:
                params["$filter"] = filter_expr
            if search_q:
                params["$search"] = search_q
                headers["ConsistencyLevel"] = "eventual"

            r = sess.get(url_count, params=params, headers=headers, timeout=30)
            if r.status_code == 200:
                try:
                    unread_filtered = int(r.text.strip())
                except Exception:
                    _logger.warning(
                        "Outlook unread_counts: cannot parse $count response: %r",
                        r.text[:200]
                    )
                    unread_filtered = unread_total
            else:
                _logger.warning(
                    "Outlook unread_counts: $count failed (%s), falling back to total",
                    r.status_code,
                )
                unread_filtered = unread_total

        except Exception as e:
            _logger.warning("Outlook unread_counts: filtered part failed: %s", e)
            unread_filtered = unread_total

        return unread_total, unread_filtered

    def _outlook_resolve_folder_id(self, sess, base_url, folder, cache=None):
        if not folder:
            return "inbox"

        path = (folder.imap_name or folder.name or "").strip()
        if not path:
            return "inbox"

        cache_key = f"outlook_folder_id:{folder.account_id.id}:{folder.id}"
        cached = memcache_get(cache_key)
        if cached:
            return cached

        WELL_KNOWN = {
            "inbox": "inbox",
            "sentitems": "sent",
            "drafts": "drafts",
            "deleteditems": "trash",
            "junkemail": "spam",
            "archive": "archive",
        }
        if path.lower() in WELL_KNOWN:
            memcache_set(cache_key, WELL_KNOWN[path.lower()], ttl=86400)
            return WELL_KNOWN[path.lower()]

        parts = [p.strip() for p in path.split("/") if p.strip()]
        if not parts:
            result = "inbox"
        else:
            url = f"{base_url}/me/mailFolders?$select=id,displayName,childFolderCount"
            current_id = None
            for part in parts:
                found = False
                while url:
                    r = sess.get(url, timeout=30)
                    r.raise_for_status()
                    data = r.json()
                    for item in data.get("value", []):
                        if (item.get("displayName") or "").strip().lower() == part.lower():
                            current_id = item["id"]
                            found = True
                            break
                    if found:
                        break
                    url = data.get("@odata.nextLink")
                if not found:
                    _logger.warning("Outlook folder part not found: %s in path %s", part, path)
                    current_id = "inbox"
                    break
                url = f"{base_url}/me/mailFolders/{current_id}/childFolders?$select=id,displayName,childFolderCount"

            result = current_id or "inbox"

        memcache_set(cache_key, result, ttl=86400)
        return result

    def _outlook_list_message_ids(self, sess, base_url, account, folder, qdict, offset, limit):
        need = offset + limit
        got_ids = []
        seen_urls = set()
        params = {"$select": "id", "$top": "50"}
        headers = {}

        if qdict.get("$search"):
            headers["ConsistencyLevel"] = "eventual"
            params["$search"] = qdict["$search"]
        else:
            params["$orderby"] = "receivedDateTime desc"

        if qdict.get("$filter"):
            params["$filter"] = qdict["$filter"]

        if folder:
            fid = self._outlook_resolve_folder_id(sess, base_url, folder)
            url = f"{base_url}/me/mailFolders/{fid}/messages"
        else:
            url = f"{base_url}/me/messages"

        attempt = 0
        while len(got_ids) < need and attempt < 10:
            attempt += 1
            if url in seen_urls:
                _logger.warning("Graph paging loop detected, stopping at attempt %s", attempt)
                break
            seen_urls.add(url)

            r = sess.get(url, params=params, headers=headers, timeout=30)
            if r.status_code >= 400:
                txt = r.text
                if "InefficientFilter" in txt and "$orderby" in (params or {}):
                    _logger.warning("Graph: InefficientFilter → retry without $orderby")
                    params.pop("$orderby", None)
                    continue
                raise Exception(f"Outlook list error: {r.text}")

            data = r.json()
            ids = [m["id"] for m in data.get("value", [])]
            got_ids.extend(ids)

            next_url = data.get("@odata.nextLink")
            if not next_url or not ids:
                break
            url, params = next_url, None

        ids_page = got_ids[offset:offset + limit]
        return ids_page, len(got_ids)

    def _graph_dt(self, dt):
        if not dt:
            return None
        s = str(dt).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            val = datetime.fromisoformat(s)
        except Exception:
            return None
        return val.astimezone(timezone.utc).replace(tzinfo=None) if val.tzinfo else val
    
    def _outlook_get_folder_name(self, sess, base_url, folder_id):
        url = f"{base_url}/me/mailFolders/{folder_id}?$select=displayName"
        r = sess.get(url, timeout=10)
        if r.status_code == 200:
            return (r.json().get("displayName") or "").strip()
        return ""

    def _outlook_fetch_meta_batch(self, sess, base_url, account, folder, ids, partner_cache, update_cache=True):
        if not ids:
            return []

        base_headers = {"Prefer": 'outlook.body-content-type="text"'}
        sess.headers.update(base_headers)

        def fetch_one(mid):
            sel = (
                "id,subject,from,receivedDateTime,hasAttachments,importance,isRead,"
                "ccRecipients,toRecipients,conversationId,flag,internetMessageId,bodyPreview,internetMessageHeaders"
            )
            url = f"{base_url}/me/messages/{mid}?$select={sel}"

            for attempt in range(5):
                r = sess.get(url, timeout=30)
                if r.status_code == 429:
                    ra = r.headers.get("Retry-After")
                    delay = int(ra) if (ra and ra.isdigit()) else (1 + attempt)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
            raise Exception("Outlook Graph throttling: too many 429s")

        folder_name = (folder.imap_name or folder.name) if folder else "Inbox"
        max_workers = min(4, len(ids))
        Cache = self.env["maildesk.message_cache"].sudo()

        messages = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(fetch_one, i) for i in ids]
            for fut in as_completed(futures):
                messages.append(fut.result())

        unknown_emails = set()
        for m in messages:
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "") or ""
            email_from = sender.lower()
            if email_from and email_from not in partner_cache:
                unknown_emails.add(email_from)

        if unknown_emails:
            partners = self.env["res.partner"].search([("email", "in", list(unknown_emails))])
            by_email = {(p.email or "").lower(): p for p in partners}
            for addr in unknown_emails:
                partner_cache[addr] = by_email.get(addr)

        records = []
        for m in messages:
            parent_folder_id = m.get("parentFolderId")
            folder_id = False
            folder_name = None

            if parent_folder_id:
                folder_name = self._outlook_get_folder_name(sess, base_url, parent_folder_id)

                if folder_name:
                    folder_obj = self.env["mailbox.folder"].search([
                        ("account_id", "=", account.id),
                        ("name", "ilike", folder_name)
                    ], limit=1)

                    if folder_obj:
                        folder_id = folder_obj.id

            headers = m.get("internetMessageHeaders") or []
            in_reply_to_raw = ""
            references_raw = ""
            for h in headers:
                name = (h.get("name") or "").lower()
                value = h.get("value") or ""
                if name == "in-reply-to":
                    in_reply_to_raw = value
                elif name == "references":
                    references_raw = value

            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "") or ""
            email_from = sender.lower()
            partner = partner_cache.get(email_from)

            dt_raw = m.get("receivedDateTime") or m.get("sentDateTime") or m.get("createdDateTime")
            msg_dt = self._graph_dt(dt_raw)

            if msg_dt:
                user_dt = fields.Datetime.context_timestamp(self, msg_dt)
                date_user = user_dt.strftime("%Y-%m-%d %H:%M:%S")
                formatted_date = user_dt.strftime("%d %b %Y %H:%M")
            else:
                date_user = False
                formatted_date = "—"

            flag = (m.get("flag") or {}).get("flagStatus")
            is_starred = (flag == "flagged")

            to_disp = ", ".join(
                [(x.get("emailAddress") or {}).get("address", "") for x in (m.get("toRecipients") or [])]
            )
            cc_disp = ", ".join(
                [(x.get("emailAddress") or {}).get("address", "") for x in (m.get("ccRecipients") or [])]
            )

            preview = (m.get("bodyPreview") or "").strip()
            if preview:
                preview = preview.replace("\r", " ").replace("\n", " ")
                if len(preview) > 160:
                    preview = preview[:160]

            has_atts = bool(m.get("hasAttachments"))

            sender_name = partner.name if partner else self._display_name_from_email(email_from)
            rec = {
                "id": m["id"],
                "account_id": [account.id, account.name],
                "folder_id": folder_id,
                "subject": m.get("subject") or "(no subject)",
                "email_from": email_from,
                "sender_display_name": self._format_sender_display(sender_name, email_from),
                "date": date_user,
                "formatted_date": formatted_date,
                "is_read": bool(m.get("isRead")),
                "is_starred": is_starred,
                "tag_ids": [],
                "has_attachments": has_atts,
                "to_display": to_disp,
                "cc_display": cc_disp,
                "is_draft": False,
                "preview_text": preview,
                "avatar_html": self._avatar_html(email_from, partner),
                "avatar_partner_id": partner.id if partner else False,
                "conversation_id": m.get("conversationId") or "",
                "message_id_norm": (m.get("internetMessageId") or "").strip("<>"),
            }

            if folder_name:
                cache_key_folder = folder_name
            else:
                cache_key_folder = "UNKNOWN"

            memcache_set(f"{account.id}:{cache_key_folder}:{m['id']}", rec, ttl=3600)

            if update_cache:
                flags_str = ("\\Seen" if rec["is_read"] else "") + (" \\Flagged" if rec["is_starred"] else "")
                vals = {
                    "message_id": rec["message_id_norm"],
                    "subject": rec["subject"],
                    "from_addr": rec["email_from"],
                    "to_addrs": to_disp,
                    "cc_addrs": cc_disp,
                    "bcc_addrs": "",
                    "date": date_user,
                    "flags": flags_str.strip(),
                    "has_attachments": has_atts,
                    "preview": preview,
                    "sender_display_name": rec["sender_display_name"],
                    "thread_id": m.get("conversationId") or "",
                    "in_reply_to": in_reply_to_raw,
                    "references_hdr": references_raw, 
                }
                try:
                    Cache.upsert_meta(
                        account_id=account.id,
                        folder=cache_key_folder,
                        uid=str(m["id"]),
                        vals=vals,
                        ttl_minutes=60,
                    )
                except (SerializationFailure, LockNotAvailable, UniqueViolation) as e:
                    _logger.debug(
                        "Graph meta upsert skipped for %s (concurrency): %s", m["id"], e
                    )

            records.append(rec)

        return records

    def _outlook_get_message_full(self, sess, base_url, account, folder, message_id, update_cache=True):
        folder_name = (folder.imap_name or folder.name) if folder else "Inbox"
        Cache = self.env["maildesk.message_cache"].sudo()
        InlineAtt = self.env["maildesk.inline.attachment"].sudo()

        cache_rec = Cache.search([
            ("account_id", "=", account.id),
            ("folder", "=", folder_name),
            ("uid", "=", str(message_id)),
        ], limit=1)

        sel = (
            "id,subject,from,toRecipients,ccRecipients,bccRecipients,"
            "receivedDateTime,hasAttachments,isRead,importance,flag,"
            "internetMessageId,conversationId,body,bodyPreview,internetMessageHeaders"
        )
        url = f"{base_url}/me/messages/{message_id}?$select={sel}"
        r = sess.get(url, timeout=30)
        r.raise_for_status()
        m = r.json()

        headers = m.get("internetMessageHeaders") or []
        in_reply_to_raw = ""
        references_raw = ""
        for h in headers:
            name = (h.get("name") or "").lower()
            value = h.get("value") or ""
            if name == "in-reply-to":
                in_reply_to_raw = value
            elif name == "references":
                references_raw = value

        use_cache_body = (
            cache_rec
            and cache_rec.body_cached
            and cache_rec.body_cache_until
            and cache_rec.body_cache_until > fields.Datetime.now()
        )

        if use_cache_body:
            body_html = cache_rec.body_html or ""
            body_plain = cache_rec.body_text or ""
        else:
            body = m.get("body") or {}
            body_html = body.get("content") or ""
            try:
                body_plain = BeautifulSoup(body_html, "lxml").get_text("\n", strip=True)
            except Exception:
                body_plain = BeautifulSoup(body_html, "html.parser").get_text("\n", strip=True)

        attachments_json = []
        inline_map = {}

        url_atts = (
            f"{base_url}/me/messages/{message_id}/attachments"
            f"?$select=id,name,contentType,size,isInline,contentId,contentBytes"
        )
        try:
            r2 = sess.get(url_atts, timeout=30)
            r2.raise_for_status()
            atts = r2.json().get("value", [])
        except Exception:
            atts = []

        for att in atts:
            att_id = att.get("id")
            if not att_id:
                continue

            name = att.get("name") or "attachment"
            mime = (att.get("contentType") or "application/octet-stream").lower()
            size = att.get("size") or 0
            content_id_raw = att.get("contentId") or ""
            cid_norm = content_id_raw.strip().strip("<>").strip().lower()
            is_inline = bool(att.get("isInline"))

            if is_inline and cid_norm and mime.startswith("image/"):
                blob = b""
                raw_b64 = att.get("contentBytes") or ""
                if raw_b64:
                    try:
                        blob = base64.b64decode(raw_b64)
                    except Exception:
                        blob = b""
                if not blob:
                    url_data = f"{base_url}/me/messages/{message_id}/attachments/{att_id}/$value"
                    try:
                        r3 = sess.get(url_data, timeout=60)
                        r3.raise_for_status()
                        blob = r3.content or b""
                    except Exception:
                        blob = b""
                if not blob:
                    continue

                vals = {
                    "data": blob,
                    "mimetype": mime,
                    "name": name,
                }
                if "cid" in InlineAtt._fields:
                    vals["cid"] = cid_norm
                if "message_uid" in InlineAtt._fields:
                    vals["message_uid"] = str(message_id)
                if "account_id" in InlineAtt._fields:
                    vals["account_id"] = account.id

                inline_rec = InlineAtt.create(vals)
                inline_map[cid_norm] = f"/maildesk/inline/{inline_rec.id}"
                continue

            if is_inline:
                continue

            preview_url = (
                f"/maildesk/attachment/show"
                f"?mid={message_id}"
                f"&aid={att_id}"
                f"&account_id={account.id}"
                f"&mimetype={mime}"
            )
            download_url = (
                f"/maildesk/attachment/download"
                f"?mid={message_id}"
                f"&aid={att_id}"
                f"&account_id={account.id}"
                f"&name={url_quote(name)}"
                f"&mimetype={mime}"
            )
            external_id = f"outlook-{account.id}-{folder_name}-{message_id}-{att_id}"

            attachments_json.append(
                self._build_external_attachment(
                    name=name,
                    mimetype=mime,
                    size=size,
                    preview_url=preview_url,
                    download_url=download_url,
                    external_id=external_id,
                    content_id=content_id_raw or "",
                )
            )

        if not inline_map:
            raw_url = f"{base_url}/me/messages/{message_id}/$value"
            try:
                r_raw = sess.get(raw_url, timeout=30)
                r_raw.raise_for_status()
                raw_bytes = r_raw.content
                msg_obj = message_from_bytes(raw_bytes)

                for part in msg_obj.walk():
                    cid = (part.get("Content-ID") or "").strip("<>").strip()
                    if not cid:
                        cid = (part.get("Content-Location") or "").strip("<>").strip()
                    if not cid:
                        continue

                    mime = (part.get_content_type() or "").lower()
                    if not mime.startswith("image/"):
                        continue

                    try:
                        blob = part.get_payload(decode=True)
                    except Exception:
                        blob = b""
                    if not blob:
                        continue

                    cid_norm = cid.lower()
                    vals = {
                        "data": blob,
                        "mimetype": mime,
                        "name": cid,
                    }
                    if "cid" in InlineAtt._fields:
                        vals["cid"] = cid_norm
                    if "message_uid" in InlineAtt._fields:
                        vals["message_uid"] = str(message_id)
                    if "account_id" in InlineAtt._fields:
                        vals["account_id"] = account.id

                    inline_rec = InlineAtt.create(vals)
                    inline_map[cid_norm] = f"/maildesk/inline/{inline_rec.id}"

            except Exception:
                pass
        
        if body_html:
            try:
                soup = BeautifulSoup(body_html, "lxml")
            except Exception:
                soup = BeautifulSoup(body_html, "html.parser")

            for img in soup.find_all("img"):
                src = (img.get("src") or "").strip()
                if not src.lower().startswith("cid:"):
                    continue

                cid = src[4:].strip("<>").strip().lower()
                url = inline_map.get(cid)
                if url:
                    img["src"] = url
                else:
                    img["data-missing"] = "1"

            body_html = str(soup)

        sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "") or ""
        email_from = sender.lower()

        partner = self.env["res.partner"].search([("email", "=ilike", email_from)], limit=1)

        dt_raw = m.get("receivedDateTime") or m.get("sentDateTime") or m.get("createdDateTime")
        msg_dt = self._graph_dt(dt_raw)

        if msg_dt:
            user_dt = fields.Datetime.context_timestamp(self, msg_dt)
            date_user = user_dt.strftime("%Y-%m-%d %H:%M:%S")
            formatted_date = user_dt.strftime("%d %b %Y %H:%M")
        else:
            date_user = False
            formatted_date = "—"

        flag = (m.get("flag") or {}).get("flagStatus")
        is_starred = (flag == "flagged")

        to_disp = ", ".join([
            (x.get("emailAddress") or {}).get("address", "") for x in (m.get("toRecipients") or [])
        ])
        cc_disp = ", ".join([
            (x.get("emailAddress") or {}).get("address", "") for x in (m.get("ccRecipients") or [])
        ])
        bcc_disp = ", ".join([
            (x.get("emailAddress") or {}).get("address", "") for x in (m.get("bccRecipients") or [])
        ])

        msg_id_norm = (m.get("internetMessageId") or "").strip("<>")
        sender_name = partner.name if partner else self._display_name_from_email(email_from)

        rec = {
            "id": message_id,
            "subject": m.get("subject") or "(no subject)",
            "email_from": email_from,
            "date": date_user,
            "formatted_date": formatted_date,
            "body_original": body_html,
            "body_plain": body_plain,
            "is_read": bool(m.get("isRead")),
            "is_starred": is_starred,
            "has_attachments": bool(attachments_json) or bool(m.get("hasAttachments")),
            "attachments": attachments_json,
            "account_display": (
                f"{account.name} | {account.email}" if account.name != account.email else account.email
            ),
            "to_display": to_disp,
            "cc_display": cc_disp,
            "bcc_display": bcc_disp,
            "account_id": [account.id, account.name],
            "is_draft": False,
            "avatar_html": self._avatar_html(email_from, partner),
            "avatar_partner_id": partner.id if partner else False,
            "tag_ids": [],
            "sender_display_name": self._format_sender_display(sender_name, email_from),
            "partner_trusted": partner.trusted_partner if partner else False,
            "trusted_by_user_id": False,
            "in_reply_to": in_reply_to_raw,
            "message_id": msg_id_norm,
            "references_hdr": references_raw,
        }

        if update_cache:
            vals = {
                "message_id": msg_id_norm,
                "subject": rec["subject"],
                "from_addr": email_from,
                "to_addrs": to_disp,
                "cc_addrs": cc_disp,
                "bcc_addrs": bcc_disp,
                "date": date_user,
                "flags": "\\Seen" if rec["is_read"] else "",
                "has_attachments": bool(m.get("hasAttachments")),
                "preview": m.get("bodyPreview") or "",
                "sender_display_name": rec["sender_display_name"],
                "thread_id": m.get("conversationId") or "",
                "thread_root_id": m.get("conversationId") or "",
                "in_reply_to": in_reply_to_raw,
                "references_hdr": references_raw,
            }

            try:
                if not cache_rec:
                    cache_rec = Cache.create({
                        **vals,
                        "account_id": account.id,
                        "folder": folder_name,
                        "uid": str(message_id),
                        "cache_until": fields.Datetime.now() + relativedelta(hours=1),
                    })
                else:
                    cache_rec.write(vals)
            except Exception:
                pass

            if cache_rec and not use_cache_body:
                try:
                    cache_rec.set_body_cache(html=body_html, text=body_plain)
                except Exception:
                    pass

        memcache_set(f"{account.id}:{folder_name}:{message_id}", rec, ttl=3600)
        return rec

    def _outlook_resolve_folder_ids(self, names_or_ids, account):
        if not account or not account.id:
            _logger.error("[GRAPH] _outlook_resolve_folder_ids called with empty account")
            return {}

        sess, base = self._outlook_build_graph(account)
        if not sess:
            return {}

        res = {}
        well_known = {
            "INBOX":   f"{base}/me/mailFolders/inbox",
            "SENT":    f"{base}/me/mailFolders/sentitems",
            "DRAFTS":  f"{base}/me/mailFolders/drafts",
            "DELETED": f"{base}/me/mailFolders/deleteditems",
            "ARCHIVE": f"{base}/me/mailFolders/archive",
            "JUNK":    f"{base}/me/mailFolders/junkemail",
        }

        for n in names_or_ids:
            key = (n or "").strip()
            up  = key.upper()
            if up in well_known:
                r = sess.get(well_known[up], timeout=30)
                r.raise_for_status()
                res[n] = r.json().get("id") or n
            else:
                res[n] = None

        pending = [n for n, fid in res.items() if not fid]
        if pending:
            url = f"{base}/me/mailFolders?$top=500&$select=id,displayName"
            while url and pending:
                r = sess.get(url, timeout=60)
                r.raise_for_status()
                data = r.json()
                by_name = {
                    (it.get("displayName") or "").strip().upper(): it.get("id")
                    for it in data.get("value", []) or []
                }
                for n in list(pending):
                    fid = by_name.get(n.strip().upper())
                    if fid:
                        res[n] = fid
                        pending.remove(n)
                url = data.get("@odata.nextLink")

            for n in pending:
                res[n] = n

        return res

    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK
    # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK # OUTLOOK OUTLOOK OUTLOOK

    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions

    @api.model
    def unread_counts_for_folder(
        self, account_id, folder_id, flt=None, text=None, partner_id=None, email_from=None
    ):
        Account = self.env['mailbox.account'].browse(account_id)
        Folder  = self.env['mailbox.folder'].browse(folder_id)
        if not Account or not Folder:
            return {'unread_total': 0, 'unread_filtered': 0}

        is_gmail   = self._is_gmail_account(Account)
        is_outlook = self._is_outlook_account(Account)

        try:
            if is_gmail:
                q = self._gmail_query_from_filters(
                    account=Account, flt=flt, text=text,
                    partner_id=partner_id, email_from=email_from
                )
                service = self._gmail_build_service(Account)
                unread_total, unread_filtered = self._gmail_unread_counts(
                    service, Account, Folder, q
                )

            elif is_outlook:
                sess, base_url = self._outlook_build_graph(Account)
                unread_total, unread_filtered = self._outlook_unread_counts(
                    sess, base_url, Account, Folder,
                    flt=flt, text=text, partner_id=partner_id, email_from=email_from,
                )

            else:
                folder_name = Folder.imap_name or Folder.name or 'INBOX'
                criteria = self._build_search_criteria(
                    account=Account, flt=flt, text=text,
                    partner_id=partner_id, email_from=email_from
                )
                unread_total, unread_filtered = self._imap_unread_counts(
                    Account, folder_name, criteria
                )

        except Exception:
            return {'unread_total': 0, 'unread_filtered': 0}

        new_total = int(unread_total or 0)
        if (Folder.unread_count or 0) != new_total:
            try:
                Folder.sudo().write({'unread_count': new_total})
            except Exception:
                pass

        return {
            'unread_total': new_total,
            'unread_filtered': int(unread_filtered or 0),
        }

    @api.model
    def action_open_create_partner(self, message_id=None, email_from=None, sender_display_name=None):
        email = (email_from or "").strip()
        display_name = (sender_display_name or "").strip()

        m = re.search(r"<?([\w.\+\-]+@[\w.\-]+\.\w+)>?", email)
        email = (m.group(1) if m else email).lower()
        if not email:
            raise UserError(_("Email address is missing."))

        d = defaults_from_email(email, display_name)
        Partner = self.env["res.partner"]

        partner = Partner.search([("email", "=ilike", email)], limit=1)

        if not partner:
            partner = Partner.create({
                "name": d["name"],
                "email": email,
                "lang": d["lang"],
                "tz": d["tz"],
                "website": d["website"],
            })

        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": partner.id,
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "create_partner_return_to_maildesk": True,
            },
        }

    @api.model
    def _resolve_msg_triplet(self, any_id, explicit_folder_id=None):
        Cache = self.env["maildesk.message_cache"].sudo()
        s = str(any_id)

        rec = None
        if explicit_folder_id:
            Fld = self.env["mailbox.folder"].browse(explicit_folder_id)
            folder = (Fld.imap_name or Fld.name or "INBOX")
            rec = Cache.search([("folder", "=", folder), ("uid", "=", s)], limit=1)

        if not rec:
            rec = Cache.search([("uid", "=", s)], limit=1)

        if rec:
            return rec.account_id.id, rec.folder or "INBOX", str(rec.uid)

        acc = self.env["mailbox.account"].search([], limit=1)
        return acc.id if acc else False, "INBOX", s

    @api.model
    def set_flags(self, ids, is_read=None, is_starred=None, folder_id=None):
        State = self.env["maildesk.email_state"].sudo()
        for _id in ids or []:
            acc_id, folder, uid = self._resolve_msg_triplet(_id, folder_id)
            State.record_flags(acc_id, folder, uid, seen=is_read, starred=is_starred, source="ui")
        return True

    @api.model
    def set_flags_bulk(self, ops, folder_id=None):
        State = self.env["maildesk.email_state"].sudo()
        for op in ops or []:
            for _id in op.get('ids') or []:
                acc_id, folder, uid = self._resolve_msg_triplet(_id, folder_id)
                State.record_flags(acc_id, folder, uid, seen=op.get('is_read'), starred=op.get('is_starred'), source="ui")
        return True

    @api.model
    def move_messages_to_folder(self, ids, target_folder_id):
        F = self.env["mailbox.folder"].browse(target_folder_id)
        to_name = (F.imap_name or F.name or "INBOX")
        State = self.env["maildesk.email_state"].sudo()

        for _id in ids or []:
            acc_id, from_name, uid = self._resolve_msg_triplet(_id)
            State.record_move(acc_id, uid, from_name, to_name, source="ui")
        return True

    def _get_tags_for_message_ids(self, account_id, msg_ids):
        if not msg_ids:
            return {}

        Link = self.env["mail.message.tag.link"].sudo()
        rows = Link.search_read(
            [("account_id", "=", account_id), ("message_id", "in", msg_ids)],
            ["message_id", "tag_id", "color"]
        )

        out = {}
        for r in rows:
            msg_id = r["message_id"]
            tag_id, tag_name = r["tag_id"][0], r["tag_id"][1]
            out.setdefault(msg_id, []).append({
                "id": tag_id,
                "name": tag_name,
                "color": r["color"],
            })
        return out

    @api.model
    def update_tags(self, message_uids, tag_ids):
        Cache = self.env["maildesk.message_cache"].sudo()
        Link = self.env["mail.message.tag.link"].sudo()

        for uid in message_uids:
            cache = Cache.search([("uid", "=", str(uid))], limit=1)
            if not cache:
                continue

            message_id = cache.message_id
            account_id = cache.account_id.id

            old_links = Link.search([("account_id", "=", account_id), ("message_id", "=", message_id)])
            old_links.unlink()

            for tid in tag_ids:
                Link.create({
                    "account_id": account_id,
                    "message_id": message_id,
                    "tag_id": tid,
                })

        return True

    def _to_list(self, txt):
        if not txt:
            return []
        return [x.strip() for x in txt.splitlines() if x.strip()]

    def _to_text(self, lst):
        return "\n".join([x.strip() for x in (lst or []) if x])

    @api.model
    def save_draft(self, **kw):
        Draft = self.env["maildesk.draft"].sudo()
        draft = False
        if kw.get("draft_id"):
            draft = Draft.browse(int(kw["draft_id"])).exists()

        account = self.env["mailbox.account"].browse(int(kw.get("account_id") or 0))
        if not account:
            raise UserError(_("Account not found."))
        self._check_account_access(account)

        body_html = kw.get("body_html") or kw.get("body") or ""
        to_list = kw.get("to") or []
        cc_list = kw.get("cc") or []
        bcc_list = kw.get("bcc") or []
        attachments = kw.get("attachment_ids") or kw.get("attachments") or []

        vals = {
            "account_id": account.id,
            "subject": kw.get("subject") or "",
            "body_html": body_html,
            "to_emails": self._to_text(to_list),
            "cc_emails": self._to_text(cc_list),
            "bcc_emails": self._to_text(bcc_list),
            "request_read_receipt": bool(kw.get("request_read_receipt")),
            "request_delivery_receipt": bool(kw.get("request_delivery_receipt")),
            "sender_display_name": kw.get("from_display") or "",
            "reply_to_message_id": kw.get("reply_to_message_id"),
            "reply_to_cache_uid": kw.get("reply_to_cache_uid"),
            "model": kw.get("model"),
            "res_id": kw.get("res_id") or False,
        }

        att_ids = [a for a in attachments if a]
        vals["attachment_ids"] = [(6, 0, att_ids)] if att_ids else [(5, 0, 0)]

        if draft:
            draft.write(vals)
        else:
            draft = Draft.create(vals)

        return draft.id

    @api.model
    def delete_messages(self, ids, folder_id=None):
        State = self.env["maildesk.email_state"].sudo()
        for any_id in ids or []:
            acc_id, folder, uid = self._resolve_msg_triplet(any_id, folder_id)
            if not acc_id or not uid:
                continue
            State.record_delete(acc_id, folder, uid, source="ui")
        return True

    @api.model
    def update_draft(self, draft_id, **kw):
        kw = dict(kw or {})
        kw["draft_id"] = draft_id
        return self.save_draft(**kw)

    @api.model
    def load_draft(self, draft_id):
        Draft = self.env["maildesk.draft"].sudo()
        draft = Draft.browse(int(draft_id))
        if not draft or not draft.exists():
            raise UserError(_("Draft not found."))

        account = draft.account_id
        self._check_account_access(account)

        to_list = self._to_list(draft.to_emails)
        cc_list = self._to_list(draft.cc_emails)
        bcc_list = self._to_list(draft.bcc_emails)

        attachments = [
            {
                "id": att.id,
                "name": att.name,
                "mimetype": att.mimetype,
            }
            for att in draft.attachment_ids
        ]

        return {
            "id": draft.id,
            "account_id": account.id,
            "subject": draft.subject or "",
            "body_html": draft.body_html or "",
            "to": to_list,
            "cc": cc_list,
            "bcc": bcc_list,
            "attachments": attachments,
            "reply_to_msg": draft.reply_to_cache_uid or None,
            "request_read_receipt": bool(draft.request_read_receipt),
            "request_delivery_receipt": bool(draft.request_delivery_receipt),
            "from_display": draft.sender_display_name
                            or account.sender_name
                            or account.name
                            or (account.email or ""),
            "model": draft.model or None,
            "res_id": draft.res_id or None,
            "message_id": draft.reply_to_message_id or "",
        }

    @api.model
    def delete_draft(self, draft_id):
        d = self.env["maildesk.draft"].sudo().browse(int(draft_id)).exists()
        if d:
            d.unlink()
        return True

    def _prepare_email(
        self,
        account,
        subject,
        body_html,
        to,
        cc=None,
        bcc=None,
        reply_message_id=None,
        attachments=None,
        request_delivery_receipt=False,
        request_read_receipt=False,
        from_display=False,
    ):

        def clean(v):
            return re.sub(r"[\r\n]+", " ", str(v or "")).strip()

        def parse_addr(lst):
            if not lst:
                return ""
            out = []
            for raw in lst:
                s = raw.strip()
                m = re.match(r"^(.*?)\s*<([^>]+)>$", s)
                if m:
                    out.append(formataddr((clean(m.group(1)), clean(m.group(2)))))
                else:
                    out.append(clean(s))
            return ", ".join(out)

        def html2text(html):
            if not BeautifulSoup:
                return ""
            soup = BeautifulSoup(html or "", "html.parser")
            for t in soup(["style", "script", "head", "meta", "link", "svg", "noscript"]):
                t.decompose()
            for a in soup.find_all("a", href=True):
                t = a.get_text(strip=True) or a["href"]
                a.string = t
                a.insert_after(f" ({a['href']})")
            txt = soup.get_text(separator="\n").strip()
            return re.sub(r"\n{3,}", "\n\n", txt)

        def ref(mid):
            if not mid:
                return None
            mid = mid.strip()
            if not mid.startswith("<"):
                mid = f"<{mid.strip('<>')}>"
            return mid

        msg = EmailMessage()
        msg_id = make_msgid(domain=(account.email or "local").split("@")[-1])

        frm = formataddr((clean(from_display or account.sender_name or account.name), clean(account.email)))

        msg["Subject"] = clean(subject)
        msg["From"] = frm
        if parse_addr(to):
            msg["To"] = parse_addr(to)
        if parse_addr(cc):
            msg["Cc"] = parse_addr(cc)
        if parse_addr(bcc):
            msg["Bcc"] = parse_addr(bcc)

        msg["Message-ID"] = msg_id
        msg["X-Original-Message-ID"] = msg_id
        msg["Reply-To"] = frm
        msg["User-Agent"] = "Maildesk"
        msg["X-Mailer"] = "Maildesk"
        msg["Date"] = formatdate(localtime=False, usegmt=True)
        msg["MIME-Version"] = "1.0"

        r = ref(reply_message_id)
        if r:
            msg["In-Reply-To"] = r
            msg["References"] = r

        if request_delivery_receipt:
            msg["Return-Receipt-To"] = clean(account.email)
        if request_read_receipt:
            msg["Disposition-Notification-To"] = clean(account.email)
            msg["X-Confirm-Reading-To"] = clean(account.email)

        plain = html2text(body_html) if body_html else ""
        msg.set_content(plain or "", subtype="plain", charset="utf-8")
        msg.add_alternative(body_html or "", subtype="html", charset="utf-8")

        if attachments:
            att = self.env["ir.attachment"].browse(attachments)
            for a in att:
                data = base64.b64decode(a.datas or b"")
                mt = a.mimetype or "application/octet-stream"
                if "/" in mt:
                    maintype, subtype = mt.split("/", 1)
                else:
                    maintype, subtype = "application", "octet-stream"
                msg.add_attachment(data, maintype, subtype, filename=a.name or "file")

        return msg, msg_id

    def _smtp_send(
        self,
        account,
        to,
        subject,
        html,
        cc=None,
        bcc=None,
        atts=None,
        reply_mid=None,
        req_delivery=False,
        req_read=False,
        from_display=False,
    ):
        self._check_account_access(account)
        smtp = account.sudo().mail_send_server_id
        if not smtp:
            raise UserError(_("SMTP server not configured."))

        msg, mid = self._prepare_email(
            account,
            subject,
            html,
            to,
            cc,
            bcc,
            reply_message_id=reply_mid,
            attachments=atts,
            request_delivery_receipt=req_delivery,
            request_read_receipt=req_read,
            from_display=from_display,
        )

        s = self.env["ir.mail_server"]._connect__(mail_server_id=smtp.id)
        try:
            try:
                s.send_message(msg)
            except Exception:
                self.env["ir.mail_server"].send_email(msg, smtp_session=s)
        finally:
            try:
                s.quit()
            except Exception:
                pass
        
        try:
            if self._need_manual_sent_append(account):
                self._imap_append_to_sent(account, msg)
        except Exception:
            _logger.exception("Error while trying to save sent message to IMAP Sent")

        return mid

    @api.model
    def send_email(self, **kw):
        Draft = self.env["maildesk.draft"].sudo()
        draft = False
        if kw.get("draft_id"):
            draft = Draft.browse(int(kw["draft_id"])).exists()

        if draft:
            a = draft.account_id
            self._check_account_access(a)
            to = self._to_list(draft.to_emails)
            cc = self._to_list(draft.cc_emails)
            bcc = self._to_list(draft.bcc_emails)
            mid = self._smtp_send(
                account=a,
                to=to,
                subject=draft.subject or "",
                html=draft.body_html or "",
                cc=cc,
                bcc=bcc,
                atts=draft.attachment_ids.ids,
                reply_mid=draft.reply_to_message_id,
                req_delivery=draft.request_delivery_receipt,
                req_read=draft.request_read_receipt,
                from_display=draft.sender_display_name or "",
            )
            draft.unlink()
            return {"message_id": mid}

        a = self.env["mailbox.account"].browse(int(kw.get("account_id") or 0))
        self._check_account_access(a)
        mid = self._smtp_send(
            account=a,
            to=kw.get("to_emails") or [],
            subject=kw.get("subject") or "",
            html=kw.get("body_html") or "",
            cc=kw.get("cc_emails") or [],
            bcc=kw.get("bcc_emails") or [],
            atts=kw.get("attachment_ids") or [],
            reply_mid=kw.get("reply_to_message_id"),
            req_delivery=kw.get("request_delivery_receipt"),
            req_read=kw.get("request_read_receipt"),
            from_display=kw.get("from_display"),
        )
        return {"message_id": mid}

    def _imap_append_to_sent(self, account, msg):
        if not self._need_manual_sent_append(account):
            return

        Folder = self.env["mailbox.folder"]
        sent_folder = None

        fld = Folder.search(
            [("account_id", "=", account.id), ("folder_type", "=", "sent")],
            limit=1,
        )
        if fld:
            sent_folder = fld.imap_name or fld.name

        if not sent_folder:
            fld = Folder.search(
                [
                    ("account_id", "=", account.id),
                    "|",
                    ("imap_name", "ilike", "sent"),
                    ("name", "ilike", "sent"),
                ],
                limit=1,
            )
            if fld:
                sent_folder = fld.imap_name or fld.name

        if not sent_folder:
            sent_folder = "Sent"

        raw_bytes = msg.as_bytes()

        pool = get_pool(account)
        try:
            with pool.session() as client:
                client.append(sent_folder, raw_bytes, flags=(SEEN,))
        except Exception:
            _logger.exception(
                "Failed to append sent message to IMAP Sent for account %s",
                account.id,
            )

    def _need_manual_sent_append(self, account):
        email = (account.email or "").lower()
        if "@" not in email:
            return True
        domain = email.split("@", 1)[1]

        gmail_domains = {
            "gmail.com",
            "googlemail.com",
        }
        outlook_domains = {
            "outlook.com",
            "hotmail.com",
            "live.com",
            "msn.com",
        }

        if domain in gmail_domains | outlook_domains:
            return False

        return True

    def _check_account_access(self, account):
        if self.env.uid == SUPERUSER_ID:
            return
        if not account:
            raise UserError(_("Mailbox account is required."))
        if (
            not self.env.user.has_group("maildesk_mail_client.group_mailbox_admin")
            and self.env.user not in account.access_user_ids
        ):
            raise UserError(_("You do not have access to this mailbox account."))

    @api.model
    def mark_partner_trusted(self, message):
        if not isinstance(message, dict):
            raise UserError("Invalid message data")

        Partner = self.env["res.partner"]

        email_from = (message.get("email_from") or "").strip()
        sender_name = (message.get("sender_display_name") or email_from).strip()

        if hasattr(self, "_extract_email_address") and email_from:
            email = self._extract_email_address(email_from) or ""
        else:
            from email.utils import parseaddr
            email = parseaddr(email_from)[1] if email_from else ""

        if not email:
            raise UserError("Unable to determine e-mail address")

        partner = False
        avatar_partner_id = message.get("avatar_partner_id")
        if avatar_partner_id:
            partner = Partner.browse(avatar_partner_id).exists()

        if not partner:
            partner = Partner.search([("email", "=ilike", email)], limit=1)

        if not partner:
            partner = Partner.create({
                "name": sender_name or email,
                "email": email,
            })

        partner.write({
            "trusted_partner": True,
            "trusted_by_user_id": self.env.user.id,
        })

        return {
            "partner_id": partner.id,
            "trusted_partner": True,
            "trusted_by_user_id": partner.trusted_by_user_id.id if partner.trusted_by_user_id else False,
            "avatar_partner_id": partner.id,
        }

    @api.model
    def get_open_document_action(self, model, res_id):
        if not model or not res_id:
            return False

        record = self.env[model].browse(int(res_id))
        if not record.exists():
            return False

        view = self.env["ir.ui.view"].search(
            [("model", "=", model), ("type", "=", "form")],
            order="priority",
            limit=1,
        )

        name = record.display_name or f"{model} #{res_id}"

        return {
            "type": "ir.actions.act_window",
            "name": _("Open: %s") % name,
            "res_model": model,
            "res_id": int(res_id),
            "view_mode": "form",
            "views": [[view.id, "form"]] if view else [[False, "form"]],
            "target": "current",
        }
    
    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions
    # user functions # user functions # user functions # user functions
    
