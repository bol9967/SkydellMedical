# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license

from odoo import api, fields, models
from .mailbox_sync import GRAPH_BASE_URL

EXCLUDE_PARTS = {
    "calendar", "kalender", "contacts", "kontakte", "tasks", "aufgaben",
    "notes", "notizen", "journal", "public", "rss", "search", "conversation",
    "quick", "synchronisierungsprobleme", "sync", "serverfehler", "konflikte", "postausgang"
}

FOLDER_PRIORITY = {
    "INBOX": 0,
    "Sent": 1, "Sent Items": 1, "Gesendet": 1, "Отправленные": 1,
    "Drafts": 2, "Черновики": 2, "Entwürfe": 2,
    "Archive": 3, "Архив": 3, "Archiv": 3,
    "Spam": 4, "Junk": 4,
    "Trash": 5, "Удаленные": 5, "Gelöschte": 5, "Bin": 5,
}

GMAIL_FOLDER_MAP = {
    "[Gmail]/Bin": "trash",
    "[Gmail]/Trash": "trash",
    "[Google Mail]/Bin": "trash",
    "[Google Mail]/Trash": "trash",
    "[Gmail]/Sent Mail": "sent",
    "[Google Mail]/Sent Mail": "sent",
    "[Gmail]/Drafts": "drafts",
    "[Google Mail]/Drafts": "drafts",
    "[Gmail]/Spam": "spam",
    "[Google Mail]/Spam": "spam",
    "[Gmail]/All Mail": "archive",
    "[Google Mail]/All Mail": "archive",
}

FOLDER_TYPE_SELECTION = [
    ("inbox", "Inbox"),
    ("starred", "Starred"),
    ("sent", "Sent"),
    ("drafts", "Drafts"),
    ("archive", "Archive"),
    ("spam", "Spam"),
    ("trash", "Trash"),
    ("other", "Other"),
]

SPECIAL_USE_MAP = {
    "\\inbox": "inbox",
    "\\sent": "sent",
    "\\drafts": "drafts",
    "\\junk": "spam",
    "\\spam": "spam",
    "\\trash": "trash",
    "\\archive": "archive",
    "\\all": "archive",
    "\\allmail": "archive",
    "\\flagged": "starred",
    "\\important": "starred",
}

FOLDER_SEQUENCE = {
    "inbox": 1,
    "starred": 2,
    "sent": 3,
    "drafts": 4,
    "archive": 5,
    "spam": 6,
    "trash": 7,
    "other": 90,
}

FOLDER_CODE_ALIASES = {
    # Trash
    "papierkorb": "trash",
    "trash": "trash",
    "bin": "trash",
    "deleted": "trash",
    "corbeille": "trash",
    "cestino": "trash",
    "eliminati": "trash",
    "borrados": "trash",
    "удаленные": "trash",
    "deleted messages": "trash",
    "gelöschte nachrichten": "trash",
    # Spam
    "junk": "spam",
    "spam": "spam",
    "correo no deseado": "spam",
    "нежелательная почта": "spam",
    # Starred
    "flagged": "starred",
    "important": "starred",
    "важное": "starred",
    # Sent
    "sent": "sent",
    "отправленные": "sent",
    "gesendet": "sent",
    "envoyés": "sent",
    "inviati": "sent",
    "enviados": "sent",
    "sent messages": "sent",
    "gesendete nachrichten": "sent",
    # Drafts
    "drafts": "drafts",
    "черновики": "drafts",
    "entwürfe": "drafts",
    "brouillons": "drafts",
    # Archive
    "archive": "archive",
    "archiv": "archive",
    "архив": "archive",
    "all_mail": "archive",
    "alle nachrichten": "archive",
    # Inbox
    "INBOX": "inbox",
    "inbox": "inbox",
    "входящие": "inbox",
    "eingang": "inbox",
    "réception": "inbox",
    "posta in arrivo": "inbox",
    "bandeja de entrada": "inbox",
}

GRAPH_FOLDER_SELECT = (
    "id,displayName,parentFolderId,childFolderCount,unreadItemCount,isHidden"
)

OUTLOOK_WELLKNOWN_MAP = {
    "inbox": "inbox",
    "sentitems": "sent",
    "drafts": "drafts",
    "deleteditems": "trash",
    "junkemail": "spam",
    "archive": "archive",
}

def is_real_mail_folder(folder):
    if folder.get("isHidden") is True:
        return False

    name_l = (folder.get("displayName") or "").strip().lower()

    if any(part in name_l for part in EXCLUDE_PARTS):
        return False

    if (
        len(name_l) >= 30
        and "-" in name_l
        and all(c.isalnum() or c in "-_" for c in name_l)
    ):
        return False

    return True


def classify_folder(display_name):
    name_l = (display_name or "").lower()

    if "inbox" in name_l or "входящие" in name_l or "eingang" in name_l:
        return "inbox"
    if "sent" in name_l or "gesendet" in name_l or "отправленные" in name_l:
        return "sent"
    if "draft" in name_l or "entwürfe" in name_l or "черновики" in name_l:
        return "drafts"
    if "spam" in name_l or "junk" in name_l or "нежелательная почта" in name_l:
        return "spam"
    if (
        "trash" in name_l
        or "deleted" in name_l
        or "gelöschte" in name_l
        or "удаленные" in name_l
        or "bin" in name_l
    ):
        return "trash"
    if "archive" in name_l or "archiv" in name_l or "архив" in name_l:
        return "archive"

    return "other"


def fetch_folder_tree(session):
    resp = session.get(
        f"{GRAPH_BASE_URL}/me/mailFolders",
        params={"$top": "100", "$select": GRAPH_FOLDER_SELECT}
    )
    resp.raise_for_status()
    roots = resp.json().get("value", [])

    def load_children(folder):
        fid = folder["id"]

        resp = session.get(
            f"{GRAPH_BASE_URL}/me/mailFolders/{fid}/childFolders",
            params={"$top": "100", "$select": GRAPH_FOLDER_SELECT}
        )
        resp.raise_for_status()

        children = []
        for child in resp.json().get("value", []):
            if is_real_mail_folder(child):
                child["children"] = load_children(child)
                children.append(child)

        return children

    tree = []
    for root in roots:
        if not is_real_mail_folder(root):
            continue
        root["children"] = load_children(root)
        tree.append(root)

    return tree

class MailboxFolder(models.Model):
    _name = "mailbox.folder"
    _description = "Mailbox Folder"
    _rec_name = "name"
    _order = "account_id, sequence, name"

    name = fields.Char(required=True)
    imap_name = fields.Char(index=True, readonly=True, store=True)
    account_id = fields.Many2one("mailbox.account", required=True, ondelete="cascade")
    parent_id = fields.Many2one("mailbox.folder", ondelete="cascade")
    child_ids = fields.One2many("mailbox.folder", "parent_id")
    is_visible = fields.Boolean(default=True)
    uid_validity = fields.Integer(default=0)
    last_uid = fields.Integer(default=0)
    unread_count = fields.Integer(default=0, string="Unread Count")
    sequence = fields.Integer(default=100, compute="_compute_sequence", store=True)
    sync_modseq = fields.Char(default="0")
    folder_type = fields.Selection(
        FOLDER_TYPE_SELECTION, default="other", required=True
    )

    @api.depends('folder_type', 'name')
    def _compute_sequence(self):
        for folder in self:
            base = FOLDER_SEQUENCE.get(folder.folder_type or "other", 90)
            depth = (folder.imap_name or "").count("/") + (folder.imap_name or "").count("\\")
            folder.sequence = base * 10 + min(depth, 9)

    @api.model
    def sync_folders_for_account(self, account):
        self = self.sudo()
        srv = account.mail_server_id.sudo()
        if srv.server_type == "outlook":
            return self._sync_outlook_graph(account)

        with self.env['mailbox.sync']._get_imap_client(account) as client:
            self._ensure_inbox(client, account)
            self._sync_all(client, account)

    def _ensure_inbox(self, client, account):
        status = client.folder_status("INBOX", ["UIDVALIDITY", "UIDNEXT", "UNSEEN"])
        uidv = status.get(b"UIDVALIDITY", 0)
        nxt = status.get(b"UIDNEXT", 1)
        last_uid = int(nxt) - 1
        unseen = int(status.get(b"UNSEEN", 0))
        inbox = self.search([("account_id", "=", account.id), ("imap_name", "=", "INBOX")], limit=1)
        if not inbox:
            self.create({
                "name": "INBOX", "imap_name": "INBOX", "account_id": account.id,
                "uid_validity": uidv, "last_uid": last_uid, "unread_count": unseen,
            })

    def _sync_all(self, client, account):
        entries = client.list_folders() or []
        if not entries:
            return {"created": 0, "updated": 0, "total": 0, "by_name": {}}

        nodes = {}
        for flags, delim_char, raw_name in entries:
            imap_name = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
            delim_char = delim_char.decode() if isinstance(delim_char, bytes) else (delim_char or "/")
            label = imap_name.rsplit(delim_char, 1)[-1].strip()
            if not label:
                continue

            label_l = label.lower()
            if any(p in label_l for p in EXCLUDE_PARTS):
                continue

            norm_flags = [self._norm_flag(f) for f in (flags or [])]
            if "\\noselect" in norm_flags:
                continue

            status = client.folder_status(imap_name, ["UIDVALIDITY", "UIDNEXT", "UNSEEN"]) or {}
            uidv = int(status.get(b"UIDVALIDITY", 0))
            nxt = int(status.get(b"UIDNEXT", 1))
            unseen = int(status.get(b"UNSEEN", 0))

            if delim_char in imap_name:
                parent_path = delim_char.join(imap_name.split(delim_char)[:-1]) or False
            else:
                parent_path = False

            nodes[imap_name] = {
                "imap_name": imap_name,
                "label": label,
                "label_l": label_l,
                "delim_char": delim_char,
                "flags": flags,
                "norm_flags": norm_flags,
                "uid_validity": uidv,
                "last_uid": max(nxt - 1, 0),
                "unseen": unseen,
                "parent_path": parent_path,
            }

        existing = self.search([("account_id", "=", account.id)])
        rec_cache = {f.imap_name: f for f in existing}

        created = 0
        updated = 0

        def _ensure_folder(imap_name):
            nonlocal created, updated
            if not imap_name:
                return self.env["mailbox.folder"]
            if imap_name in rec_cache:
                return rec_cache[imap_name]

            data = nodes.get(imap_name)
            if not data:
                return self.env["mailbox.folder"]

            parent_rec = _ensure_folder(data["parent_path"]) if data["parent_path"] else self.env["mailbox.folder"]

            vals = {
                "name": data["label"],
                "imap_name": data["imap_name"],
                "account_id": account.id,
                "uid_validity": data["uid_validity"],
                "last_uid": data["last_uid"],
                "unread_count": data["unseen"],
                "parent_id": parent_rec.id or False,
                "delim_char": data["delim_char"],
                "special_use_flags": data["flags"],
            }

            existing = self.search([
                ("account_id", "=", account.id),
                ("imap_name", "=", data["imap_name"]),
            ], limit=1)

            if existing:
                vals.pop("name", None)
                existing.write(vals)
                rec = existing
                updated += 1
            else:
                rec = self.create(vals)
                created += 1

            rec_cache[imap_name] = rec
            return rec

        for imap_name in nodes.keys():
            _ensure_folder(imap_name)

        return {
            "created": created,
            "updated": updated,
            "total": len(rec_cache),
            "by_name": {k: v.id for k, v in rec_cache.items()},
        }

    @api.model
    def get_folder_tree(self, account_id, domain=None):
        folders = self.search([("account_id", "=", account_id), ("is_visible", "=", True)])
        root = folders.filtered(lambda f: not f.parent_id)
        return [self._serialize(f) for f in root.sorted('sequence')]

    def _serialize(self, folder):
        return {
            "id": folder.id, "name": folder.name, "imap_name": folder.imap_name,
            "unread_count": folder.unread_count,
            "children": [self._serialize(c) for c in folder.child_ids.sorted('sequence')],
            "folder_type": folder.folder_type,
        }
    
    def _norm_flag(self, f):
        if isinstance(f, bytes):
            f = f.decode(errors="ignore")
        return (f or "").strip().lower()

    @api.model
    def _classify_folder(self, flags, delim, imap_name):
        norm_flags = [self._norm_flag(f) for f in (flags or [])]
        for f in norm_flags:
            code = SPECIAL_USE_MAP.get(f)
            if code:
                return code
        if "flagged" in norm_flags or "important" in norm_flags:
            return "starred"

        if imap_name in GMAIL_FOLDER_MAP:
            return GMAIL_FOLDER_MAP[imap_name]

        delim = (delim or "/")
        label = imap_name.split(delim)[-1] if delim in (imap_name or "") else (imap_name or "")
        label_l = (label or "").strip().lower()

        if (imap_name or "").upper() == "INBOX" or label_l == "inbox":
            return "inbox"

        code = FOLDER_CODE_ALIASES.get(label_l)
        if code:
            return code

        for known, code in [
            ("sent", "sent"),
            ("draft", "drafts"),
            ("spam", "spam"),
            ("junk", "spam"),
            ("trash", "trash"),
            ("bin", "trash"),
            ("archive", "archive"),
            ("all mail", "archive"),
            ("starred", "starred"),
        ]:
            if known in label_l:
                return code

        return "other"
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            imap_name = vals.get("imap_name") or ""
            delim = vals.get("delim_char") or "/"
            flags = vals.get("special_use_flags") or []
            if not vals.get("folder_type"):
                ftype = self._classify_folder(flags, delim, imap_name)
                vals["folder_type"] = ftype or "other"
            vals.pop("delim_char", None)
            vals.pop("special_use_flags", None)
        records = super().create(vals_list)
        return records

    def write(self, vals):
        if "folder_type" in vals:
            vals.pop("delim_char", None)
            vals.pop("special_use_flags", None)
            return super().write(vals)

        need_reclass = False
        for key in ("imap_name", "delim_char", "special_use_flags", "name"):
            if key in vals:
                need_reclass = True
                break

        if need_reclass:
            for rec in self:
                imap_name = vals.get("imap_name", rec.imap_name or "")
                delim = vals.get("delim_char") or "/"
                flags = vals.get("special_use_flags") or []
                ftype = self._classify_folder(flags, delim, imap_name) or rec.folder_type or "other"

                local_vals = dict(vals)
                local_vals["folder_type"] = ftype
                local_vals.pop("delim_char", None)
                local_vals.pop("special_use_flags", None)
                super(MailboxFolder, rec).write(local_vals)
            return True

        vals.pop("delim_char", None)
        vals.pop("special_use_flags", None)
        return super().write(vals)

    @api.model
    def _sync_outlook_graph(self, account):
        session, _base_url = self.env["mailbox.sync"]._outlook_build_graph(account)
        raw_roots = fetch_folder_tree(session)

        def build_node(folder, parent_path=""):
            name = (folder.get("displayName") or "").strip()
            if not name:
                return None

            path = f"{parent_path}/{name}" if parent_path else name
            well_known = (folder.get("wellKnownName") or "").lower()
            if well_known in OUTLOOK_WELLKNOWN_MAP:
                folder_type = OUTLOOK_WELLKNOWN_MAP[well_known]
            else:
                folder_type = classify_folder(name)

            node = {
                "name": name,
                "path": path,
                "unread": int(folder.get("unreadItemCount") or 0),
                "folder_type": folder_type,
                "children": [],
            }

            for child in folder.get("children") or []:
                child_node = build_node(child, parent_path=path)
                if child_node:
                    node["children"].append(child_node)

            return node

        root_nodes = []
        for raw in raw_roots:
            node = build_node(raw, parent_path="")
            if node:
                root_nodes.append(node)

        existing = self.search([("account_id", "=", account.id)])
        rec_by_path = {f.imap_name: f for f in existing}

        created = updated = 0

        def ensure_folder(node, parent_rec=False):
            nonlocal created, updated
            if not node:
                return

            path = node["path"]
            rec = rec_by_path.get(path)

            vals = {
                "name": node["name"],
                "imap_name": path,
                "account_id": account.id,
                "unread_count": node["unread"],
                "parent_id": parent_rec.id if parent_rec else False,
                "folder_type": node["folder_type"],
            }

            if rec:
                rec.write(vals)
                updated += 1
            else:
                rec = self.create(vals)
                created += 1

            rec_by_path[path] = rec

            for child in node["children"]:
                ensure_folder(child, rec)

        for root in root_nodes:
            ensure_folder(root, parent_rec=False)

        return {
            "created": created,
            "updated": updated,
            "total": len(rec_by_path),
        }
