# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


import asyncio
import atexit
import logging
import queue
import random
import threading
import time
import re
from contextlib import suppress, nullcontext
from inspect import isawaitable
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from odoo import api, SUPERUSER_ID, sql_db

try:
    import aioimaplib
except Exception:
    aioimaplib = None

_logger = logging.getLogger(__name__)

_MANAGERS = {}
_MANAGERS_LOCK = threading.RLock()


def _env_manage():
    m = getattr(api.Environment, "manage", None)
    return m() if m else nullcontext()

def get_idle_manager(env):
    dbname = env.cr.dbname
    with _MANAGERS_LOCK:
        mgr = _MANAGERS.get(dbname)
        if not mgr:
            mgr = IdleManager(dbname)
            _MANAGERS[dbname] = mgr
        return mgr

def _norm_resp_line(line):
    if isinstance(line, (bytes, bytearray)):
        return line.decode("utf-8", "ignore")
    if isinstance(line, str):
        return line
    parts = []
    for t in (line or []):
        if isinstance(t, (bytes, bytearray)):
            parts.append(t.decode("utf-8", "ignore"))
        else:
            parts.append(str(t))
    return " ".join(parts)

async def _maybe_await(x):
    return await x if isawaitable(x) else x


async def _maybe_call(obj, name, *args, **kwargs):
    meth = getattr(obj, name, None)
    if meth is None:
        raise AttributeError(f"{obj!r} has no attribute {name}")
    res = meth(*args, **kwargs)
    return await _maybe_await(res)


class BusPublisher:
    def __init__(self, dbname, batch_ms=50, max_batch=200, qsize=2000):
        self.dbname = dbname
        self.batch_ms = batch_ms / 1000.0
        self.max_batch = max_batch
        self.q = queue.Queue(maxsize=qsize)
        self._thr = threading.Thread(
            target=self._run, name=f"maildesk-bus-{dbname}", daemon=True
        )
        self._thr.start()

    def enqueue(self, channel, payload):
        try:
            self.q.put_nowait((channel, payload))
        except queue.Full:
            acc = payload.get("account_id")
            folded = {"type": "refresh", "account_id": acc}
            with suppress(Exception):
                self.q.get_nowait()
            try:
                self.q.put_nowait((channel, folded))
            except queue.Full:
                pass

    def _coalesce(self, items):
        by_key = {}
        out = []
        for ch, msg in items:
            t = msg.get("type")
            key = (ch, t, msg.get("account_id"), msg.get("folder"))
            if t in ("refresh", "flags", "removed", "added"):
                cur = by_key.get(key)
                if cur is None:
                    by_key[key] = (ch, dict(msg))
                else:
                    _ch, agg = cur
                    if t in ("removed", "flags"):
                        by_key[key] = (ch, dict(msg))  # last-wins
                    elif t == "added":
                        agg.setdefault("uids", []).extend(msg.get("uids") or [])
                        agg.setdefault("meta", []).extend(msg.get("meta") or [])
            else:
                out.append((ch, msg))
        out.extend(by_key.values())
        return out

    def _run(self):
        while True:
            try:
                try:
                    first = self.q.get()
                except Exception:
                    time.sleep(0.05)
                    continue

                batch = [first]
                deadline = time.time() + self.batch_ms
                while len(batch) < self.max_batch and time.time() < deadline:
                    try:
                        batch.append(self.q.get_nowait())
                    except queue.Empty:
                        break

                batch = self._coalesce(batch)

                with _env_manage():
                    db = sql_db.db_connect(self.dbname)
                    cr = db.cursor()
                    try:
                        env = api.Environment(cr, SUPERUSER_ID, {})
                        Bus = env["bus.bus"].sudo()
                        Account = env["mailbox.account"].sudo()
                        Folder = env["mailbox.folder"].sudo()
                        Sync = env["mailbox.sync"].sudo()

                        for ch, payload in batch:
                            acc_id = payload.get("account_id")
                            if not acc_id:
                                continue

                            acc = Account.browse(acc_id)
                            if not acc or not acc.exists():
                                continue

                            server_kind = (
                                (acc.server_kind or acc.mail_server_id.server_type or "")
                                or ""
                            ).lower()
                            payload.setdefault("server_kind", server_kind)

                            if (
                                payload.get("type") == "added"
                                and server_kind not in ("gmail", "outlook")
                                and not payload.get("meta")
                            ):
                                uids = payload.get("uids") or []
                                folder_name = payload.get("folder") or "INBOX"

                                if uids:
                                    folder = Folder.search(
                                        [
                                            ("account_id", "=", acc_id),
                                            "|",
                                            ("imap_name", "=", folder_name),
                                            ("name", "=", folder_name),
                                        ],
                                        limit=1,
                                    )
                                    if folder:
                                        try:
                                            metas = Sync.message_meta_bulk(
                                                acc_id,
                                                folder.id,
                                                uids,
                                            ) or []
                                            payload["meta"] = metas
                                        except Exception as e2:
                                            _logger.warning(
                                                "BusPublisher meta enrich failed "
                                                "acc=%s folder=%s uids=%s: %s",
                                                acc_id,
                                                folder_name,
                                                uids,
                                                e2,
                                            )

                            channel_name = ch or f"maildesk.account.{acc_id}"
                            channel = (self.dbname, channel_name)
                            Bus._sendone(channel, "maildesk", payload)

                        cr.commit()
                    except Exception as e:
                        cr.rollback()
                        _logger.error("Bus publish failed: %s", e)
                    finally:
                        cr.close()
            except Exception as e:
                _logger.error("BusPublisher loop error: %s", e)
                time.sleep(0.1)

class IdleManager:
    IDLE_CHANNEL_TPL = "maildesk.account.{account_id}"
    HEARTBEAT_TTL = 60
    GC_INTERVAL = 10

    def __init__(self, dbname):
        self.dbname = dbname
        self._loop = None
        self._loop_thread = None
        self._leader_db = None
        self._leader_cur = None
        self._is_leader = False

        self._watchers = {}
        self._subs = defaultdict(set)
        self._beats = {}
        self._metrics = defaultdict(
            lambda: {"events": 0, "last_event": 0, "last_error": None}
        )

        self._lock = threading.RLock()
        self._publisher = BusPublisher(dbname)

        self._ensure_loop()
        self._elect_leader()
        self._start_gc_thread()

        atexit.register(self._shutdown)

    def _ensure_loop(self):
        if self._loop:
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            name=f"maildesk-idle-{self.dbname}",
            daemon=True,
        )
        self._loop_thread.start()
        _logger.info("[IdleManager] event loop started for DB '%s'", self.dbname)

    def _run_coro(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _elect_leader(self):
        self._leader_db = sql_db.db_connect(self.dbname)
        self._leader_cur = self._leader_db.cursor()
        cr = self._leader_cur
        cr.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))",
            (f"maildesk-idle:{self.dbname}",),
        )
        self._is_leader = bool(cr.fetchone()[0])
        _logger.info("[IdleManager] leader=%s for DB '%s'", self._is_leader, self.dbname)

    def is_leader(self):
        return self._is_leader

    def subscribe(self, env, account_id: int, session_id: str):
        with self._lock:
            self._subs[account_id].add(session_id)
            self._beats[(account_id, session_id)] = time.time()
            if not self.is_leader():
                return
            if account_id not in self._watchers:
                w = AccountWatcher(
                    dbname=self.dbname,
                    account_id=account_id,
                    on_event=self._on_event_push,
                    on_error=self._on_watcher_error,
                )
                self._watchers[account_id] = w
                self._run_coro(w.start())
                self._publish_status(account_id, "watcher.started")
                _logger.info("[IdleManager] watcher started for account %s", account_id)

    def unsubscribe(self, account_id: int, session_id: str):
        with self._lock:
            subs = self._subs.get(account_id, set())
            subs.discard(session_id)
            self._beats.pop((account_id, session_id), None)
            if not subs:
                self._subs.pop(account_id, None)
                w = self._watchers.pop(account_id, None)
                if w:
                    self._run_coro(w.stop())
                    self._publish_status(account_id, "watcher.stopped")
                    _logger.info(
                        "[IdleManager] watcher stopped for account %s", account_id
                    )

    def touch(self, account_id: int, session_id: str):
        with self._lock:
            subs = self._subs.get(account_id, set())
            if session_id in subs:
                self._beats[(account_id, session_id)] = time.time()
                return

            _logger.info(
                "[IdleManager] touch() from unknown session → auto-subscribe "
                "acc=%s sid=%s", account_id, session_id,
            )
            self.subscribe(None, account_id, session_id)

    def _on_event_push(self, payload: dict):
        try:
            acc = payload.get("account_id")
            m = self._metrics[acc]
            m["events"] += 1
            m["last_event"] = time.time()
            channel = self.IDLE_CHANNEL_TPL.format(account_id=acc)
            self._publisher.enqueue(channel, payload)
        except Exception as e:
            _logger.warning("[IdleManager] enqueue failed: %s", e)

    def _on_watcher_error(self, account_id: int, exc: Exception):
        _logger.warning("[Watcher %s] error: %s", account_id, exc)
        self._metrics[account_id]["last_error"] = f"{type(exc).__name__}: {exc}"
        payload = {
            "type": "watcher.error",
            "account_id": account_id,
            "message": str(exc)[:200],
        }
        channel = self.IDLE_CHANNEL_TPL.format(account_id=account_id)
        self._publisher.enqueue(channel, payload)

    def _publish_status(self, account_id: int, event: str, **extra):
        payload = {"type": event, "account_id": account_id}
        payload.update(extra or {})
        self._on_event_push(payload)

    def _start_gc_thread(self):
        t = threading.Thread(
            target=self._gc_loop, name=f"maildesk-idle-gc-{self.dbname}", daemon=True
        )
        t.start()

    def _gc_loop(self):
        while True:
            now = time.time()
            dead = []
            with self._lock:
                for (acc, sid), ts in list(self._beats.items()):
                    if now - ts > self.HEARTBEAT_TTL:
                        dead.append((acc, sid))
                for acc, sid in dead:
                    self._subs.get(acc, set()).discard(sid)
                    self._beats.pop((acc, sid), None)
                    if acc in self._watchers and not self._subs.get(acc):
                        w = self._watchers.pop(acc, None)
                        if w:
                            self._run_coro(w.stop())
                            self._publish_status(acc, "watcher.stopped")
            time.sleep(self.GC_INTERVAL)

    def status(self):
        with self._lock:
            return {
                "is_leader": self._is_leader,
                "watchers": list(self._watchers.keys()),
                "subs": {k: len(v) for k, v in self._subs.items()},
                "metrics": self._metrics,
            }

    def _shutdown(self):
        with suppress(Exception):
            with self._lock:
                for w in list(self._watchers.values()):
                    self._run_coro(w.stop())
                self._watchers.clear()
        with suppress(Exception):
            if self._leader_cur:
                self._leader_cur.close()
                self._leader_cur = None
        with suppress(Exception):
            if self._leader_db:
                self._leader_db.close()
                self._leader_db = None


class _IdleAdapter:
    def __init__(self, client, acc_id):
        self.c = client
        self.mode = None
        if hasattr(self.c, "idle_start") and hasattr(self.c, "idle_wait"):
            self.mode = "new"
        elif hasattr(self.c, "idle") and hasattr(self.c, "wait_server_push"):
            self.mode = "old"
        else:
            self.mode = "none"
        _logger.info("[Idle] adapter acc=%s mode=%s", acc_id, self.mode)

    async def start(self):
        if self.mode == "new":
            try:
                await _maybe_call(self.c, "idle_start")
            except TypeError:
                await _maybe_call(self.c, "idle_start")
            return
        if self.mode == "old":
            asyncio.create_task(_maybe_call(self.c, "idle"))
            return
        raise RuntimeError("IDLE not supported by this aioimaplib version")

    async def wait_push(self, timeout=30):
        if self.mode == "new":
            try:
                resp = await asyncio.wait_for(_maybe_call(self.c, "idle_wait", timeout=timeout), timeout=timeout + 1)
            except asyncio.TimeoutError:
                return []
            lines = []
            if resp is not None:
                raw = getattr(resp, "lines", None)
                if raw:
                    lines = [(_norm_resp_line(l) or "") for l in raw]
            return lines
        if self.mode == "old":
            try:
                msg = await asyncio.wait_for(_maybe_call(self.c, "wait_server_push"), timeout=timeout + 1)
            except asyncio.TimeoutError:
                return []
            return [str(msg)] if msg else []
        return []

    async def done(self):
        if hasattr(self.c, "idle_done"):
            return await _maybe_call(self.c, "idle_done")
        if hasattr(self.c, "idle_stop"):  # rare alt
            return await _maybe_call(self.c, "idle_stop")


class AccountWatcher:
    def __init__(self, dbname, account_id: int, on_event, on_error):
        self.dbname = dbname
        self.account_id = account_id
        self.on_event = on_event
        self.on_error = on_error
        self._task = None
        self._stop = asyncio.Event()
        self._backoff = 1

    async def start(self):
        if getattr(self, "_task", None) and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._runner(), name=f"maildesk-watch-{self.account_id}"
        )

    async def stop(self):
        self._stop.set()
        if getattr(self, "_task", None):
            try:
                await asyncio.wait_for(self._task, timeout=3)
            except Exception:
                pass

    async def _runner(self):
        while not self._stop.is_set():
            try:
                await self._run_once()
                self._backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.on_error(self.account_id, e)
                await asyncio.sleep(self._backoff + random.uniform(0, 0.5))
                self._backoff = min(self._backoff * 2, 30)

    def _with_env(self, fn):
        with _env_manage():
            db = sql_db.db_connect(self.dbname)
            cr = db.cursor()
            try:
                env = api.Environment(cr, SUPERUSER_ID, {})
                return fn(env)
            finally:
                cr.close()

    async def _run_once(self):
        conf = self._load_account_conf()
        kind = str(conf.get("server_kind") or "").lower()

        if kind == "gmail":
            await self._gmail_history_loop(account_id=self.account_id)
            return

        if kind == "outlook":
            await self._outlook_delta_loop(
                self.account_id,
                folders=("INBOX", "SENT", "DELETED", "JUNK", "ARCHIVE"),
            )
            return

        if aioimaplib is None:
            raise RuntimeError("aioimaplib is not installed")

        client = None
        try:
            ClientCls = aioimaplib.IMAP4_SSL if conf["is_ssl"] else aioimaplib.IMAP4
            client = ClientCls(host=conf["host"], port=conf["port"], timeout=60)

            with suppress(Exception):
                await _maybe_call(client, "wait_hello_from_server")

            while not self._stop.is_set():
                try:
                    await _maybe_call(client, "login", conf["login"], conf["password"])

                    with suppress(Exception):
                        await _maybe_call(client, "enable", "UTF8=ACCEPT")

                    await self._idle_inbox_loop(client)
                    break

                except aioimaplib.Error as e:
                    err = (str(e) or "").upper()
                    if (
                        "AUTHENTICATIONFAILED" in err
                        or "LOGIN" in err
                        or "NONAUTH" in err
                    ):
                        _logger.warning(
                            "[Watcher %s] IMAP login failed for %s: %s",
                            self.account_id,
                            conf["host"],
                            e,
                        )
                        raise
                    raise

                except Exception as e:
                    self.on_error(self.account_id, e)
                    await asyncio.sleep(2)

        finally:
            if client:
                with suppress(Exception):
                    await _maybe_call(client, "logout")

    async def _gmail_history_loop(self, account_id, batch=500, quiet_sleep=30, active_sleep=5):
        def _build_service(env):
            acc = env['mailbox.account'].browse(account_id).sudo()
            return env['mailbox.sync']._gmail_build_service(acc)
        service = self._with_env(_build_service)

        def _ensure_anchor(env):
            acc = env['mailbox.account'].browse(account_id).sudo()
            if acc.gmail_last_history_id:
                return acc.gmail_last_history_id
            msg = service.users().messages().list(userId="me", maxResults=1, q="-in:spam -in:trash").execute()
            items = msg.get("messages", []) or []
            if not items:
                acc.write({"gmail_last_history_id": "0"})
                return "0"
            last_id = items[0]["id"]
            m = service.users().messages().get(userId="me", id=last_id, format="metadata").execute()
            hid = str(m.get("historyId") or "0")
            acc.write({"gmail_last_history_id": hid})
            return hid

        def pick_primary_folder(labels):
            if "TRASH" in labels: return "TRASH"
            if "SPAM" in labels: return "SPAM"
            if "SENT" in labels: return "SENT"
            if "INBOX" in labels: return "INBOX"
            if labels: return "ALL"
            return None

        start_id = self._with_env(_ensure_anchor)
        sleep_cur = quiet_sleep

        while not self._stop.is_set():
            try:
                req = service.users().history().list(
                    userId="me",
                    startHistoryId=start_id,
                    maxResults=batch,
                )
                all_hist = []
                newest_hid = start_id
                while req is not None:
                    resp = req.execute()
                    hist = resp.get("history", []) or []
                    all_hist.extend(hist)
                    if hist:
                        newest_hid = str(hist[-1].get("id") or newest_hid)
                    req = service.users().history().list_next(previous_request=req, previous_response=resp)

                if not all_hist:
                    await asyncio.sleep(sleep_cur)
                    continue

                sleep_cur = active_sleep

                added_ids, removed_ids, flags_map = [], [], {}
                moves = []

                for h in all_hist:
                    for ev in h.get("messagesAdded", []):
                        added_ids.append(ev["message"]["id"])
                    for ev in h.get("messagesDeleted", []):
                        removed_ids.append(ev["message"]["id"])
                    for ev in h.get("labelsAdded", []):
                        mid = ev["message"]["id"]
                        labs = set(ev.get("labelIds") or [])
                        f = flags_map.setdefault(mid, {"seen": None, "starred": None})
                        if "UNREAD" in labs:
                            f["seen"] = False
                        if "STARRED" in labs:
                            f["starred"] = True
                        dst = pick_primary_folder(labs)
                        if dst in {"TRASH", "SPAM"}:
                            moves.append((mid, None, dst))
                    for ev in h.get("labelsRemoved", []):
                        mid = ev["message"]["id"]
                        labs = set(ev.get("labelIds") or [])
                        f = flags_map.setdefault(mid, {"seen": None, "starred": None})
                        if "UNREAD" in labs:
                            f["seen"] = True
                        if "STARRED" in labs:
                            f["starred"] = False
                        if "INBOX" in labs:
                            moves.append((mid, "INBOX", "ALL"))

                metas = []
                if added_ids:
                    def _meta(env):
                        acc = env['mailbox.account'].browse(account_id).sudo()
                        return env['mailbox.sync']._gmail_fetch_meta_batch(service, acc, folder=False, ids=added_ids, partner_cache={})
                    metas = self._with_env(_meta) or []
                    if metas:
                        self.on_event({
                            "type": "added",
                            "account_id": account_id,
                            "folder": None,
                            "uids": [m["id"] for m in metas],
                            "meta": metas,
                        })

                if removed_ids:
                    self.on_event({
                        "type": "removed",
                        "account_id": account_id,
                        "folder": None,
                        "uids": removed_ids,
                    })

                out_flags = {}
                for mid, f in flags_map.items():
                    cur = {}
                    if f["seen"] is not None:
                        cur["seen"] = bool(f["seen"])
                    if f["starred"] is not None:
                        cur["starred"] = bool(f["starred"])
                    if cur:
                        out_flags[mid] = cur
                if out_flags:
                    self.on_event({
                        "type": "flags",
                        "account_id": account_id,
                        "folder": None,
                        "flags_map": out_flags,
                    })

                move_add_ids = [mid for (mid, _src, dst) in moves if dst]
                metas_move = []
                if move_add_ids:
                    def _meta_move(env):
                        acc = env['mailbox.account'].browse(account_id).sudo()
                        return env['mailbox.sync']._gmail_fetch_meta_batch(service, acc, folder=False, ids=list(set(move_add_ids)), partner_cache={})
                    metas_move = self._with_env(_meta_move) or []
                    meta_by_id = {m["id"]: m for m in metas_move}
                else:
                    meta_by_id = {}

                for mid, src, dst in moves:
                    if src:
                        self.on_event({
                            "type": "removed",
                            "account_id": account_id,
                            "folder": src,
                            "uids": [mid],
                        })
                    if dst:
                        m = meta_by_id.get(mid)
                        self.on_event({
                            "type": "added",
                            "account_id": account_id,
                            "folder": dst,
                            "uids": [mid],
                            "meta": [m] if m else [],
                        })

                def _save_anchor(env, hid):
                    env['mailbox.account'].browse(account_id).sudo().write({"gmail_last_history_id": str(hid)})
                self._with_env(lambda env: _save_anchor(env, newest_hid))
                start_id = newest_hid

            except Exception as e:
                msg = (str(e) or "").lower()
                if "404" in msg or ("historyid" in msg and "invalid" in msg):
                    def _reinit(env):
                        acc = env['mailbox.account'].browse(account_id).sudo()
                        msg = service.users().messages().list(userId="me", maxResults=1, q="-in:spam -in:trash").execute()
                        items = msg.get("messages", []) or []
                        if not items:
                            acc.write({"gmail_last_history_id": "0"})
                            return "0"
                        last = items[0]["id"]
                        m = service.users().messages().get(userId="me", id=last, format="metadata").execute()
                        hid = str(m.get("historyId") or "0")
                        acc.write({"gmail_last_history_id": hid})
                        return hid
                    start_id = self._with_env(_reinit)
                    sleep_cur = quiet_sleep
                    continue
                if "401" in msg or "unauthorized" in msg or "invalid_grant" in msg:
                    service = self._with_env(_build_service)
                    await asyncio.sleep(2)
                    continue
                self.on_error(self.account_id, e)
                await asyncio.sleep(min(self._backoff + 1, 30))

    async def _idle_inbox_loop(self, client):
        acc = self.account_id
        folder = "INBOX"

        _logger.info("[Idle] start acc=%s folder=%s → select", acc, folder)
        t0 = time.time()
        await self._safe_select(client, folder)
        _logger.info(
            "[Idle] selected acc=%s folder=%s in %.3fs", acc, folder, time.time() - t0
        )

        uidnext, unseen, recent = await self._status(client, folder)
        last_uidnext = uidnext or 0
        _logger.info(
            "[Idle] baseline acc=%s folder=%s uidnext=%s unseen=%s recent=%s",
            acc,
            folder,
            uidnext,
            unseen,
            recent,
        )

        async def _emit_refresh(reason=None):
            self.on_event(
                {
                    "type": "refresh",
                    "account_id": acc,
                    "folder": folder,
                    "hint": {"reason": reason} if reason else {},
                }
            )

        async def _emit_added_from(uid_from):
            self.on_event(
                {
                    "type": "added",
                    "account_id": acc,
                    "folder": folder,
                    "uids": [int(uid_from or 0)],
                    "meta": [],
                }
            )

        adapter = _IdleAdapter(client, acc)
        KEEPALIVE_SEC = 60 * 25
        POLL_SEC = 10
        last_keepalive = time.time()

        idle_supported = adapter.mode in ("new", "old")
        if not idle_supported:
            _logger.info("[Idle] IDLE unsupported acc=%s → polling mode", acc)

        while not self._stop.is_set():
            try:
                if idle_supported:
                    _logger.info(
                        "[Idle] enter IDLE acc=%s folder=%s (mode=%s)",
                        acc,
                        folder,
                        adapter.mode,
                    )
                    t_idle_start = time.time()
                    try:
                        await adapter.start()
                    except Exception as e:
                        _logger.info(
                            "[Idle] cannot start IDLE acc=%s → polling (%s)", acc, e
                        )
                        idle_supported = False
                        continue

                    while not self._stop.is_set():
                        lines = []
                        try:
                            lines = await adapter.wait_push(timeout=5)
                        except asyncio.TimeoutError:
                            lines = []
                        except Exception as e:
                            _logger.info("[Idle] wait error acc=%s → fallback to polling (%s)", acc, e)
                            idle_supported = False
                            break
                        
                        if lines:
                            _logger.debug("[Idle] notify acc=%s lines=%d sample=%s", acc, len(lines), lines[:2])

                            if any(re.search(r"\bEXISTS\b", ln, re.I) for ln in lines):
                                _logger.info("[Idle] EXISTS acc=%s → exit IDLE and resync", acc)
                                with suppress(Exception):
                                    await adapter.done()
                                await self._safe_select(client, folder)
                                uidnext2, _, _ = await self._status(client, folder)
                                if uidnext2 and uidnext2 != last_uidnext:
                                    await _emit_added_from(last_uidnext)
                                    last_uidnext = uidnext2
                                break

                            if any(re.search(r"\bEXPUNGE\b", ln, re.I) for ln in lines):
                                _logger.info("[Idle] EXPUNGE acc=%s → exit IDLE and refresh", acc)
                                with suppress(Exception):
                                    await adapter.done()
                                await _emit_refresh("expunge")
                                uidnext2, _, _ = await self._status(client, folder)
                                if uidnext2:
                                    last_uidnext = uidnext2
                                break
                            
                            if any(re.search(r"\bFETCH\b.*\bFLAGS\b", ln, re.I) for ln in lines):
                                _logger.info("[Idle] FLAGS acc=%s → emit flags", acc)
                                seqs = set()
                                for ln in lines:
                                    s = ln.decode() if isinstance(ln, (bytes, bytearray)) else str(ln)
                                    for num in re.findall(r"(?:^\*\s*)?(\d+)\s+FETCH\b", s, flags=re.I):
                                        try:
                                            seqs.add(int(num))
                                        except Exception:
                                            pass

                                if not seqs:
                                    self.on_event({"type": "flags", "account_id": acc, "folder": folder})
                                else:
                                    with suppress(Exception):
                                        await adapter.done()

                                    seqs_sorted = sorted(seqs)
                                    ranges = []
                                    start = prev = seqs_sorted[0]
                                    for n in seqs_sorted[1:]:
                                        if n == prev + 1:
                                            prev = n
                                        else:
                                            ranges.append(f"{start}:{prev}" if start != prev else str(start))
                                            start = prev = n
                                    ranges.append(f"{start}:{prev}" if start != prev else str(start))
                                    seqset = ",".join(ranges)

                                    resp = await _maybe_call(client, "fetch", seqset, "(UID FLAGS)")
                                    lines_fetch = [_norm_resp_line(l) for l in (getattr(resp, "lines", []) or [])]

                                    flags_map = {}
                                    deleted_uids = []

                                    for line in lines_fetch:
                                        m_uid = re.search(r"\bUID\s+(\d+)\b", line, re.I)
                                        if not m_uid:
                                            continue
                                        uid = int(m_uid.group(1))
                                        m_flags = re.search(r"\bFLAGS\s*\((.*?)\)", line, re.I)
                                        flags_str = (m_flags.group(1) if m_flags else "").strip()
                                        flags = [f for f in re.split(r"\s+", flags_str) if f]

                                        seen    = any(re.fullmatch(r"\\?Seen",    f, re.I) for f in flags)
                                        starred = any(re.fullmatch(r"\\?Flagged", f, re.I) for f in flags)
                                        deleted = any(re.fullmatch(r"\\?Deleted", f, re.I) for f in flags)

                                        if deleted:
                                            deleted_uids.append(uid)
                                            continue

                                        flags_map[uid] = {"seen": seen, "starred": starred}

                                    if flags_map:
                                        def _upd(env):
                                            env['maildesk.message_cache'].sudo().update_flags_bulk(acc, folder, flags_map)
                                        self._with_env(_upd)

                                        self.on_event({
                                            "type": "flags",
                                            "account_id": acc,
                                            "folder": folder,
                                            "flags_map": flags_map,
                                        })

                                    if deleted_uids:
                                        def _rm(env):
                                            env['maildesk.message_cache'].sudo().remove_uids(acc, folder, deleted_uids)
                                        self._with_env(_rm)
                                        self.on_event({
                                            "type": "removed",
                                            "account_id": acc,
                                            "folder": folder,
                                            "uids": deleted_uids,
                                        })
                                break

                        now = time.time()
                        if now - last_keepalive > KEEPALIVE_SEC:
                            _logger.info("[Idle] keepalive acc=%s → idle_done + NOOP (%.0fs in IDLE)", acc, now - t_idle_start)
                            with suppress(Exception):
                                await adapter.done()
                            with suppress(Exception):
                                await _maybe_call(client, "noop")
                            last_keepalive = now
                            break
                    continue

                _logger.debug("[Idle] poll tick acc=%s folder=%s", acc, folder)
                await asyncio.sleep(POLL_SEC)
                uidnext2, _, _ = await self._status(client, folder)
                if uidnext2 and uidnext2 != last_uidnext:
                    _logger.info(
                        "[Idle] poll: uidnext changed acc=%s %s→%s",
                        acc,
                        last_uidnext,
                        uidnext2,
                    )
                    await _emit_added_from(last_uidnext)
                    last_uidnext = uidnext2
                with suppress(Exception):
                    await _maybe_call(client, "noop")

            except asyncio.CancelledError:
                _logger.info("[Idle] cancelled acc=%s", acc)
                break
            except Exception as e:
                _logger.warning("[Idle] loop error acc=%s: %s", acc, e)
                await asyncio.sleep(0.8)
                raise

    async def _safe_select(self, client, name: str):
        acc = self.account_id
        try:
            await _maybe_call(client, "select", name or "INBOX")
            _logger.debug(
                "[Idle] select acc=%s folder=%s mode=SELECT", acc, name or "INBOX"
            )
            return
        except Exception as e1:
            _logger.debug("[Idle] select failed acc=%s folder=%s: %s", acc, name, e1)

        with suppress(Exception):
            await _maybe_call(client, "examine", name or "INBOX")
            _logger.debug(
                "[Idle] select acc=%s folder=%s mode=EXAMINE", acc, name or "INBOX"
            )
            return

        delim = await self._get_delim(client)
        alt = (name or "INBOX").replace("\\", delim).replace("/", delim)
        if alt and alt != name:
            with suppress(Exception):
                await _maybe_call(client, "select", alt)
                _logger.debug("[Idle] select acc=%s alt=%s mode=SELECT", acc, alt)
                return
            with suppress(Exception):
                await _maybe_call(client, "examine", alt)
                _logger.debug("[Idle] select acc=%s alt=%s mode=EXAMINE", acc, alt)
                return

        with suppress(Exception):
            await _maybe_call(client, "select", "INBOX")
            _logger.debug("[Idle] select fallback acc=%s INBOX mode=SELECT", acc)
            return
        await _maybe_call(client, "examine", "INBOX")
        _logger.debug("[Idle] select fallback acc=%s INBOX mode=EXAMINE", acc)

    async def _get_delim(self, client) -> str:
        with suppress(Exception):
            ns = await _maybe_call(client, "namespace")
            if ns and isinstance(ns, (list, tuple)):
                for grp in ns:
                    if isinstance(grp, (list, tuple)):
                        for _prefix, d in grp:
                            if d:
                                return d
        with suppress(Exception):
            lst = await _maybe_call(client, "list", "", "")
            if lst and len(lst[0]) >= 2 and lst[0][1]:
                return lst[0][1]
        return "/"

    async def _status(self, client, folder: str):
        acc = self.account_id
        t0 = time.time()
        try:
            resp = await _maybe_call(client, "status", folder or "INBOX", "(UIDNEXT UNSEEN RECENT)")
            lines = [ _norm_resp_line(l) for l in (getattr(resp, "lines", []) or []) ]
            blob = " ".join(lines) if lines else _norm_resp_line(resp) or ""
            def grab(name):
                m = re.search(rf"{name}\s+(\d+)", blob, re.I)
                return int(m.group(1)) if m else None
            uidnext, unseen, recent = grab("UIDNEXT"), grab("UNSEEN"), grab("RECENT")
            _logger.debug(
                "[Idle] status acc=%s folder=%s took=%.3fs uidnext=%s unseen=%s recent=%s raw=%s",
                acc,
                folder,
                time.time() - t0,
                uidnext,
                unseen,
                recent,
                blob,
            )
            return uidnext, unseen, recent
        except Exception as e:
            _logger.warning("[Idle] status error acc=%s folder=%s: %s", acc, folder, e)
            self.on_event({"type": "refresh", "account_id": acc, "folder": folder})
            return None, None, None

    def _load_account_conf(self):
        def _fn(env):
            acc = env["mailbox.account"].browse(self.account_id)
            server = acc.mail_server_id
            login = (getattr(acc, "login", None) or getattr(server, "user", None) or "").strip()
            password = (getattr(acc, "password", None) or getattr(server, "password", None) or "")
            server_kind = getattr(server, "server_type", None) or ""
            return dict(
                host=server.server,
                port=int(server.port or 993),
                is_ssl=bool(server.is_ssl),
                login=login,
                password=password,
                server_kind=server_kind,
            )
        return self._with_env(_fn)
    
    async def _rate_limited_get(self, sess, url, *, params=None, headers=None, max_retries=5):
        attempt = 0
        while True:
            r = await _maybe_await(sess.get(url, params=params, headers=headers, timeout=60))
            if r.status_code != 429:
                r.raise_for_status()
                return r
            attempt += 1
            if attempt >= max_retries:
                r.raise_for_status()
            ra = r.headers.get("Retry-After")
            delay = int(ra) if (ra and ra.isdigit()) else min(1 + attempt, 10)
            await asyncio.sleep(delay)

    async def _outlook_name_by_folder_id(self, sess, base, fid, cache):
        if not fid:
            return None
        if fid in cache:
            return cache[fid]
        r = await self._rate_limited_get(sess, f"{base}/me/mailFolders/{fid}", params={"$select": "displayName"})
        name = (r.json().get("displayName") or "").strip() or None
        cache[fid] = name
        return name

    async def _outlook_delta_loop(
        self,
        account_id,
        folders=None,
        page_size=100,
        quiet_sleep=30,
        active_sleep=5,
        initial_days=30,
    ):
        def _build_session(env):
            acc = env['mailbox.account'].browse(account_id).sudo()
            return env['mailbox.sync']._outlook_build_graph(acc)

        def _get_tokens(env):
            acc = env['mailbox.account'].browse(account_id).sudo()
            return dict(acc.outlook_delta_tokens or {})

        def _save_tokens(env, tokens):
            env['mailbox.account'].browse(account_id).sudo().write({"outlook_delta_tokens": tokens})

        def _set_folder(env, mid, fid):
            env['maildesk.message_cache'].sudo().set_folder(account_id, mid, fid)

        def _get_folder(env, mid):
            return env['maildesk.message_cache'].sudo().get_folder(account_id, mid)

        def _update_flags(env, folder_name, fmap):
            env['maildesk.message_cache'].sudo().update_flags_bulk(account_id, folder_name, fmap)

        sess, base = self._with_env(_build_session)
        if not sess:
            raise RuntimeError("Outlook Graph session unavailable")

        tokens = self._with_env(_get_tokens)
        fname_cache = {}
        sleep_cur = quiet_sleep

        SELECT = (
            "id,subject,from,toRecipients,receivedDateTime,hasAttachments,"
            "internetMessageId,parentFolderId,isRead,flag"
        )
        prefer_hdr = {
            "Prefer": f'odata.maxpagesize={page_size}, outlook.body-content-type="text"'
        }

        def _initial_params():
            """Параметры для самого первого delta-запроса (нет токена)."""
            params = {"$select": SELECT}
            if initial_days and initial_days > 0:
                since = datetime.now(timezone.utc) - timedelta(days=initial_days)
                since_str = since.isoformat().replace("+00:00", "Z")
                params["$filter"] = f"receivedDateTime ge {since_str}"
            return params

        while not self._stop.is_set():
            had_changes = False
            try:
                loop_mode = "GLOBAL" if not folders else "BY_FOLDER"
                if not folders:
                    key = "__ALL__"

                    if key in tokens:
                        url = tokens[key]
                        params = None
                    else:
                        url = f"{base}/me/messages/delta"
                        params = _initial_params()

                    added_ids, removed_ids, flags_map, moves = [], [], {}, []
                    last_delta = None

                    while url:
                        r = await self._rate_limited_get(sess, url, headers=prefer_hdr, params=params)
                        j = r.json()
                        items = j.get("value", []) or []

                        params = None

                        for it in items:
                            if "@removed" in it:
                                mid = it.get("id")
                                if mid:
                                    removed_ids.append(mid)
                                continue

                            mid = it.get("id")
                            is_read = bool(it.get("isRead"))
                            fstatus = ((it.get("flag") or {}).get("status") or "").lower()
                            starred = (fstatus == "flagged")
                            pfid = it.get("parentFolderId") or None
                            prev = self._with_env(lambda env, _mid=mid: _get_folder(env, _mid))

                            flags_map[mid] = {"seen": is_read, "starred": starred}

                            if prev and prev != pfid:
                                moves.append((mid, prev, pfid))

                            added_ids.append(mid)
                            self._with_env(lambda env, _mid=mid, _pfid=pfid: _set_folder(env, _mid, _pfid))

                        url = j.get("@odata.nextLink")
                        last_delta = j.get("@odata.deltaLink") or last_delta

                    metas = []
                    if added_ids:
                        def _meta(env, _ids=list(set(added_ids))):
                            acc = env['mailbox.account'].browse(account_id).sudo()
                            sync = env['mailbox.sync']
                            return sync._outlook_fetch_meta_batch(
                                sess, base, acc, folder=False, ids=_ids, partner_cache={}
                            )
                        metas = self._with_env(_meta) or []
                        if metas:
                            sample_id = metas[0].get("id")
                            had_changes = True
                            self.on_event({
                                "type": "added",
                                "account_id": account_id,
                                "folder": None,
                                "uids": [m["id"] for m in metas],
                                "meta": metas,
                            })

                    if removed_ids:
                        had_changes = True
                        self.on_event({
                            "type": "removed",
                            "account_id": account_id,
                            "folder": None,
                            "uids": removed_ids,
                        })

                    if flags_map:
                        had_changes = True
                        self._with_env(lambda env, _fmap=flags_map: _update_flags(env, None, _fmap))
                        self.on_event({
                            "type": "flags",
                            "account_id": account_id,
                            "folder": None,
                            "flags_map": flags_map,
                        })

                    for mid, src_fid, dst_fid in moves:
                        had_changes = True
                        src_name = await self._outlook_name_by_folder_id(sess, base, src_fid, fname_cache)
                        dst_name = await self._outlook_name_by_folder_id(sess, base, dst_fid, fname_cache)

                        if src_name:
                            self.on_event({
                                "type": "removed",
                                "account_id": account_id,
                                "folder": src_name,
                                "uids": [mid],
                            })
                        self.on_event({
                            "type": "added",
                            "account_id": account_id,
                            "folder": dst_name,
                            "uids": [mid],
                            "meta": [],
                        })

                    if last_delta:
                        tokens[key] = last_delta

                else:
                    def _resolve_ids(env):
                        sync = env["mailbox.sync"]
                        acc = env["mailbox.account"].browse(account_id).sudo()
                        return sync._outlook_resolve_folder_ids(folders, acc)

                    fids = self._with_env(_resolve_ids)

                    for fname, fid in fids.items():
                        if fid in tokens:
                            url = tokens[fid]
                            params = None
                        else:
                            url = f"{base}/me/mailFolders/{fid}/messages/delta"
                            params = _initial_params()

                        added_ids, removed_ids, flags_map, moves = [], [], {}, []
                        last_delta = None

                        while url:
                            r = await self._rate_limited_get(sess, url, headers=prefer_hdr, params=params)
                            j = r.json()
                            items = j.get("value", []) or []

                            params = None

                            for it in items:
                                if "@removed" in it:
                                    mid = it.get("id")
                                    if mid:
                                        removed_ids.append(mid)
                                    continue

                                mid = it.get("id")
                                is_read = bool(it.get("isRead"))
                                fstatus = ((it.get("flag") or {}).get("status") or "").lower()
                                starred = (fstatus == "flagged")
                                pfid = it.get("parentFolderId") or None
                                prev = self._with_env(lambda env, _mid=mid: _get_folder(env, _mid))

                                flags_map[mid] = {"seen": is_read, "starred": starred}

                                if prev and prev != pfid:
                                    moves.append((mid, prev, pfid))

                                added_ids.append(mid)
                                self._with_env(lambda env, _mid=mid, _pfid=pfid: _set_folder(env, _mid, _pfid))

                            url = j.get("@odata.nextLink")
                            last_delta = j.get("@odata.deltaLink") or last_delta

                        metas = []
                        if added_ids:
                            def _meta(env, _ids=list(set(added_ids))):
                                acc = env['mailbox.account'].browse(account_id).sudo()
                                sync = env['mailbox.sync']
                                return sync._outlook_fetch_meta_batch(
                                    sess, base, acc, folder=False, ids=_ids, partner_cache={}
                                )
                            metas = self._with_env(_meta) or []
                            if metas:
                                sample_id = metas[0].get("id")
                                had_changes = True
                                self.on_event({
                                    "type": "added",
                                    "account_id": account_id,
                                    "folder": fname,
                                    "uids": [m["id"] for m in metas],
                                    "meta": metas,
                                })

                        if removed_ids:
                            had_changes = True
                            self.on_event({
                                "type": "removed",
                                "account_id": account_id,
                                "folder": fname,
                                "uids": removed_ids,
                            })

                        if flags_map:
                            had_changes = True
                            self._with_env(lambda env, _fmap=flags_map: _update_flags(env, fname, _fmap))
                            self.on_event({
                                "type": "flags",
                                "account_id": account_id,
                                "folder": fname,
                                "flags_map": flags_map,
                            })

                        for mid, src_fid, dst_fid in moves:
                            had_changes = True
                            src_name = await self._outlook_name_by_folder_id(sess, base, src_fid, fname_cache)
                            dst_name = await self._outlook_name_by_folder_id(sess, base, dst_fid, fname_cache)

                            if src_name:
                                self.on_event({
                                    "type": "removed",
                                    "account_id": account_id,
                                    "folder": src_name,
                                    "uids": [mid],
                                })
                            self.on_event({
                                "type": "added",
                                "account_id": account_id,
                                "folder": dst_name,
                                "uids": [mid],
                                "meta": [],
                            })

                        if last_delta:
                            tokens[fid] = last_delta

                self._with_env(lambda env: _save_tokens(env, tokens))
                await asyncio.sleep(active_sleep if had_changes else sleep_cur)

            except Exception as e:
                self.on_error(account_id, e)
                await asyncio.sleep(min(self._backoff + 1, 30))
