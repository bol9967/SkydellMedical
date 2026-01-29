// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {
  Component,
  markup,
  onMounted,
  onWillStart,
  onWillUnmount,
  useRef,
  useState,
} from "@odoo/owl";
import {rpc} from "@web/core/network/rpc";
import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import {usePopover} from "@web/core/popover/popover_hook";
import {useFileViewer} from "@web/core/file_viewer/file_viewer_hook";
import {debounce} from "@web/core/utils/timing";
import {useService} from "@web/core/utils/hooks";
import {standardActionServiceProps} from "@web/webclient/actions/action_service";
import {user} from "@web/core/user";
import {AttachmentList} from "@mail/core/common/attachment_list";

import {AssignTagsDialog} from "./assign_tags_dialog.esm.js";
import {ComposeMail} from "./compose_mail.esm.js";
import {ContactPickerDialog} from "./contact_picker_dialog.esm.js";
import {MoveToFolderDialog} from "./move_to_folder_dialog.esm.js";
import {PartnerCardPopover} from "./partner_card_popover.esm.js";

export class MailDesk extends Component {
  static props = {
    action: Object,
    className: {
      type: String,
      optional: true,
    },
    ...standardActionServiceProps,
  };

  setup() {
    this.rpc = rpc;
    this.busService = useService("bus_service");
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.notification = useService("notification");
    this.actionService = useService("action");
    this.fileViewer = useFileViewer();
    this.listRef = useRef("list");
    this.partnerCard = usePopover(PartnerCardPopover);

    this.shiftAnchor = null;
    this._idleTokens = new Map(); 

    this.state = useState({
      messages: [],
      selectedMessage: null,
      selectedIds: [],
      selectMode: false,
      allSelected: false,
      preselectMessageId: null,
      accounts: [],
      tags: [],
      foldersByAccount: {},
      currentAccount: null,
      currentFolderId: null,
      currentFilter: "all",
      messageOffset: 0,
      messageLimit: 30,
      searchQuery: "",
      totalMessagesCount: null,
      partnerId: null,
      emailFrom: null,
      loadingMore: false,
      partnerName: null,
      hiddenMessageIds: [],
      isRefreshing: false,
      selectedTagId: [],
      expandedFolderIds: [],
    });

    this._reqStamp = 0;

    const params = this.props.action.params || {};
    this.state.partnerId = params.partner_id || null;
    this.state.emailFrom = params.email_from || null;
    this.state.partnerName = params.partner_name || null;
    this.onDelayedSearch = debounce(() => this.refreshMessages(), 800);

    this._msgKey = (m) => {
      const acc = Array.isArray(m.account_id) ? m.account_id[0] : m.account_id;
      const fld = m.folder_id;
      const uid = m.uid ?? m.id; 
      return `${acc}|${fld}|${uid}`;
    };

    this._getIndexByKey = (key) => {
      return this.state.messages.findIndex(m => this._msgKey(m) === key);
    };

    onWillStart(async () => {
      await this.loadInitialMessages();
      this.defaultExpandedAccountId = this.state.currentAccount || (this.state.accounts[0] && this.state.accounts[0].id);
      if (this.state.currentFolderId) {
        this._expandFolderParents(this.state.currentFolderId);
      }
    });

    onMounted(async () => {
      const listEl = this.listRef.el;
      listEl.addEventListener("scroll", () => {
        const nearBottom = listEl.scrollTop + listEl.clientHeight >= listEl.scrollHeight - 10;
        if (nearBottom && !this.state.loadingMore) this.loadMoreMessages();
      });
      document.addEventListener("click", this._onClickAnywhere);
      document.addEventListener("keydown", this.onKeyDown);

      this._busListener = (payload) => this.onAccountEvent(payload);
      this.busService.subscribe("maildesk", this._busListener);

      this._busChannels = [];
      for (const acc of this.state.accounts) {
        const ch = `maildesk.account.${acc.id}`;
        this.busService.addChannel(ch);
        this._busChannels.push(ch);
      }

      for (const acc of this.state.accounts) {
        const token = `${user.userId}-${Date.now()}-${acc.id}`;
        this._idleTokens.set(acc.id, token);
        try {
          await this.orm.call("mailbox.sync", "idle_subscribe", [acc.id, token]);
        } catch (e) {
          console.warn("idle_subscribe fail", e);
        }
      }
      this._idlePing = setInterval(() => {
        for (const acc of this.state.accounts) {
          const token = this._idleTokens.get(acc.id);
          if (token) this.orm.call("mailbox.sync", "idle_touch", [acc.id, token]).catch(() => {});
        }
      }, 30000);

    })

    onWillUnmount(() => {
      document.removeEventListener("click", this._onClickAnywhere);
      document.removeEventListener("keydown", this.onKeyDown);

      if (this._busListener) {
        this.busService.unsubscribe("maildesk", this._busListener);
        this._busListener = null;
      }
      if (this._busChannels) {
        for (const ch of this._busChannels) {
          try { this.busService.deleteChannel(ch); } catch (_) {}
        }
        this._busChannels = [];
      }

      for (const acc of this.state.accounts) {
        const token = this._idleTokens.get(acc.id);
        if (token) this.orm.call("mailbox.sync", "idle_unsubscribe", [acc.id, token]).catch(() => {});
      }
      this._idleTokens.clear();
      if (this._idlePing) clearInterval(this._idlePing);
    })
    }

    _folderNameOfCurrent() {
      if (!this.state.currentFolderId || !this.state.foldersByAccount || !this.state.currentAccount) return null;
      const list = this.state.foldersByAccount[this.state.currentAccount] || [];
      const f = list.find(x => x.id === this.state.currentFolderId);
      return f ? (f.imap_name || f.name) : null;
    }

    _resolveFolderIdByName(accountId, folderName) {
      if (!accountId || !folderName) return null;
      const list = this.state.foldersByAccount[accountId] || [];
      const target = list.find(f => (f.imap_name || f.name) === folderName);
      return target ? target.id : null;
    }

    onAccountEvent = async (payload) => {
      const _t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
      try {
        const watchingAll = this.isAllFilterActive && this.isAllFilterActive();
        const sameAccount = watchingAll || !this.state.currentAccount || payload.account_id === this.state.currentAccount;

        let sameFolder = true;
        if (!watchingAll && this.state.currentFolderId) {
          const curName = this._folderNameOfCurrent ? this._folderNameOfCurrent() : null;
          if (payload.folder) sameFolder = (curName || "INBOX") === payload.folder;
        }

        if (!sameAccount) {
          return;
        }
        if (!sameFolder) {
          return;
        }

        switch (payload.type) {
          case "added": {
            const uids = Array.isArray(payload.uids) ? payload.uids : [];
            const inline = Array.isArray(payload.meta) ? payload.meta : [];
            if (inline.length) {
              this._insertOrUpdateSorted(inline);
              break;
            }
            if (uids.length) {
              let folderId = this._resolveFolderIdByName(payload.account_id, payload.folder);
              try {
                let meta = [];
                if (folderId) {
                  meta = await this.orm.call("mailbox.sync", "message_meta_bulk", [payload.account_id, folderId, uids]);
                } else {
                  meta = await this._fetchMetaAnyFolder(payload.account_id, uids);
                }
                this._insertOrUpdateSorted(meta || []);
              } catch (e) {
                console.warn("[MailDesk] added: meta fetch failed → refreshLight", e);
                this.refreshLight(payload);
              }
            } else {
              this.refreshLight(payload);
            }
            break;
          }
          case "removed": {
            const ids = payload.uids || [];
            const acc = payload.account_id;
            const fld = this._resolveFolderIdByName(acc, payload.folder) ?? this.state.currentFolderId;
            const keys = ids.map(uid => `${acc}|${fld}|${uid}`);
            this._removeByKeys(keys);
            break;
          }
          case "flags": {
            if (payload.flags_map && Object.keys(payload.flags_map).length) {
              const acc = payload.account_id;
              const fld = this._resolveFolderIdByName(acc, payload.folder) ?? this.state.currentFolderId;
              const kmap = {};
              for (const [uid, vals] of Object.entries(payload.flags_map)) {
                kmap[`${acc}|${fld}|${uid}`] = vals;
              }
              this._updateFlagsByKey(kmap);
            } else {
              this.refreshLight(payload);
            }
            break;
          }

          case "refresh": {
            break;
          }
          case "watcher.started":
          case "watcher.stopped":
          case "watcher.error": {
            break;
          }
          default:
            console.warn("[MailDesk] unknown event type:", payload?.type, payload);
        }
      } catch (err) {
        console.error("[MailDesk] onAccountEvent error:", err, "payload:", payload);
        try { this.refreshLight(payload); } catch (_e) {}
      } finally {
        const _t1 = (typeof performance !== "undefined" ? performance.now() : Date.now());
      }
    };

    refreshLight = debounce(async (payload) => {
      const stamp = ++this._reqStamp;

      const domainFilters = {};
      if (this.state.partnerId) {
        domainFilters.partner_id = this.state.partnerId;
      }
      if (this.state.emailFrom) {
        domainFilters.email_from = this.state.emailFrom;
      }

      const effAccountId =
        this.state.currentAccount ?? payload?.account_id ?? null;

      const effFolderId =
        this.state.currentFolderId ??
        (payload?.folder
          ? this._resolveFolderIdByName(effAccountId, payload.folder)
          : null) ??
        null;

      let result;
      try {
        result = await this.orm.call(
          "mailbox.sync",
          "message_search_load",
          [],
          {
            account_id: effAccountId,
            folder_id: effFolderId,
            filter: this.state.currentFilter,
            search: this.state.searchQuery,
            offset: 0,
            limit: this.state.messageLimit,
            tag_ids: this.state.selectedTagId,
            ...domainFilters,
          }
        );
      } catch (e) {
        console.warn("[MailDesk] refreshLight RPC failed:", e);
        return;
      }

      if (stamp !== this._reqStamp) {
        return;
      }

      const next = (result.records || []).map((m) => this.normalizeMessage(m));

      const list = this.state.messages;
      const byKey = new Map(list.map((m) => [this._msgKey(m), m]));

      for (const n of next) {
        const k = this._msgKey(n);
        const ex = byKey.get(k);
        if (ex) {
          this._safeMergeMessage(ex, n);
        } else {
          list.push(n);
          byKey.set(k, n);
        }
      }

      this._insertOrUpdateSorted([]);
      this.state.messageOffset = this.state.messages.length;
    }, 400);


     normalizeMessage(m) {
      return {
        ...m,
        avatar_html: m.avatar_html ? markup(m.avatar_html) : "",
        uid: m.uid != null ? Number(m.uid) : m.uid,
        sender_display_name: m.sender_display_name || m.email_from || "",
        preview_text: m.preview_text || "",
        formatted_date: m.formatted_date || this.formatUserDate(m.date) || "",
      };
    }

    _safeMergeMessage(target, incoming) {
      if (!incoming) {
        return target;
      }
      for (const [key, value] of Object.entries(incoming)) {
        if (value === undefined || value === null) {
          continue;
        }
        if (typeof value === "string" && value.trim() === "") {
          continue;
        }
        target[key] = value;
      }
      return target;
    }

    async loadInitialMessages() {
      const urlParams = this.getUrlParams();

      let acc = parseInt(urlParams.get("account"));
      let fld = parseInt(urlParams.get("folder"));

      this.state.currentAccount = isNaN(acc) ? null : acc;
      this.state.currentFolderId = isNaN(fld) ? null : fld;

      this.state.messageOffset = 0;
      this.state.currentFilter = urlParams.get("filter") || "all";
      this.state.preselectMessageId = parseInt(urlParams.get("mail")) || null;

      const tagsRaw = urlParams.get("tags") || "";
      this.state.selectedTagId = tagsRaw
          ? tagsRaw.split(",").map((t) => parseInt(t))
          : [];

      if (!acc && !fld) {
          const accounts = await this.orm.searchRead(
              "mailbox.account",
              [["access_user_ids", "in", [user.userId]]],
              ["id"]
          );

          if (accounts?.length) {
              this.state.currentAccount = accounts[0].id;

              const folders = await this.orm.call(
                  "mailbox.folder",
                  "get_folder_tree",
                  [accounts[0].id]
              );

              if (folders?.length) {
                  this.state.currentFolderId = folders[0].id;
              }
          }
      }

      await this.loadData();
      await this.loadMoreMessages();
  }

    async loadData() {
      try {
        const accounts = await this.orm.searchRead(
          "mailbox.account",
          [["access_user_ids", "in", [user.userId]]],
          ["id", "name", "email", "sender_name"]
        );
        if (!accounts || accounts.length === 0) throw new Error("No accounts found.");
        this.state.accounts = accounts;

        const domainFilters = {};
        if (this.state.partnerId) domainFilters.partner_id = this.state.partnerId;
        if (this.state.emailFrom) domainFilters.email_from = this.state.emailFrom;

        const foldersByAccount = {};
        for (const account of accounts) {
          try {
            const foldersData = await this.orm.call("mailbox.folder", "get_folder_tree", [account.id]);
            foldersByAccount[account.id] = foldersData;
          } catch (err) {
            console.error(`Failed to load folders for account ${account.id}:`, err);
          }
        }
        this.state.foldersByAccount = foldersByAccount;

        const tags = await this.orm.searchRead("mail.message.tag", [], ["id", "name", "color"]);
        this.state.tags = tags;
      } catch (err) {
        console.error("Error loading data:", err);
      }
    }

    refreshMessages = async () => {
  this._reqStamp += 1;
  const stamp = this._reqStamp;

  const domainFilters = {};
  if (this.state.partnerId) domainFilters.partner_id = this.state.partnerId;
  if (this.state.emailFrom) domainFilters.email_from = this.state.emailFrom;

  const prevMessages = this.state.messages.slice();

  try {
    this.state.isRefreshing = true;
    this.render();

    const result = await this.orm.call("mailbox.sync", "message_search_load", [], {
      account_id: this.state.currentAccount,
      folder_id: this.state.currentFolderId,
      filter: this.state.currentFilter,
      search: this.state.searchQuery,
      offset: 0,
      limit: this.state.messageLimit,
      tag_ids: this.state.selectedTagId,
      ...domainFilters,
    });

    if (stamp !== this._reqStamp) return;

    const next = (result.records || []).map((m) => {
      return {
        ...m,
        avatar_html: m.avatar_html ? markup(m.avatar_html) : "",
        uid: m.uid != null ? Number(m.uid) : m.uid,
      };
    });

    const nextById = new Map(next.map((m) => [m.id, m]));
    const order = new Map(next.map((m, i) => [m.id, i]));
    const have = new Set();

    const merged = [];

    for (const msg of this.state.messages) {
      const updated = nextById.get(msg.id);
      if (updated) {
        merged.push(Object.assign({}, msg, updated));
        have.add(msg.id);
      }
    }

    for (const m of next) {
      if (!have.has(m.id)) merged.push(m);
    }

    merged.sort((a, b) => (order.get(a.id) ?? 999999) - (order.get(b.id) ?? 999999));

    this.state.messages = merged;
    this.state.totalMessagesCount = result.totalMessagesCount || merged.length;
    this.state.messageOffset = merged.length;


  } catch (err) {
    console.error("[MailDesk] Refresh error:", err);
    this.state.messages = prevMessages;
  } finally {
    if (stamp === this._reqStamp) {
      this.state.isRefreshing = false;
      this.render();
      this._fetchUnreadCounters();
    }
  }
};

    async loadMoreMessages() {
      if (this.state.loadingMore) return;
      this.state.loadingMore = true;

      const epoch = this._reqStamp;
      const startOffset = this.state.messageOffset;

      const domainFilters = {};
      if (this.state.partnerId) domainFilters.partner_id = this.state.partnerId;
      if (this.state.emailFrom) domainFilters.email_from = this.state.emailFrom;

      this.orm.call("mailbox.sync", "message_search_load", [], {
        account_id: this.state.currentAccount,
        folder_id: this.state.currentFolderId,
        filter: this.state.currentFilter,
        search: this.state.searchQuery,
        offset: startOffset,
        limit: this.state.messageLimit,
        tag_ids: this.state.selectedTagId,
        ...domainFilters,
      }).then(async (result) => {
        console.log(result)
        if (epoch !== this._reqStamp) return;
        const batch = result.records || [];
        this.state.totalMessagesCount = result.totalMessagesCount || 0;
        for (const m of batch) if (m.avatar_html) m.avatar_html = markup(m.avatar_html);
        const have = new Set(this.state.messages.map(m => m.id));
        const add = [];
        for (const m of batch) if (!have.has(m.id)) { add.push(m); have.add(m.id); }
        if (add.length) this.state.messages.push(...add);
        this.state.messageOffset = startOffset + add.length;

        if (this.state.preselectMessageId) {
          const msg = this.state.messages.find(m => m.id === this.state.preselectMessageId);
          if (msg) await this.selectMessage(msg);
          this.state.preselectMessageId = null;
        }
      }).catch((e) => {
        console.error("Failed to load messages:", e);
      }).finally(() => {
        if (epoch === this._reqStamp) this.state.loadingMore = false;
      });
    }

  onClickMessage(ev, msg) {
    const isShift = ev.shiftKey;
    const isCtrlOrCmd = ev.ctrlKey || ev.metaKey;
    const currentIdx = this.state.messages.findIndex((m) => m.id === msg.id);

    if (isShift) {
      if (this.shiftAnchor === null) {
        this.shiftAnchor = this.state.messages.findIndex(
          (m) => m.id === this.state.selectedMessage?.id
        );
      }
      const [a, b] = [this.shiftAnchor, currentIdx].sort((x, y) => x - y);
      this.state.selectedIds = this.state.messages.slice(a, b + 1).map((m) => m.id);
    } else if (isCtrlOrCmd) {
      const alreadySelected = this.state.selectedIds.includes(msg.id);
      if (alreadySelected) {
        this.state.selectedIds = this.state.selectedIds.filter((id) => id !== msg.id);
      } else {
        this.state.selectedIds.push(msg.id);
      }
      this.shiftAnchor = currentIdx;
    } else {
      this.shiftAnchor = currentIdx;
      this.selectMessage(msg);
    }
  }

  async selectMessage(msg) {
    const token = (this._selTok = (this._selTok || 0) + 1);
    this.state.isLoadingMessage = true;

    const wasUnread = !msg.is_read;

    try {
      const fullMsg = await this.orm.call(
        "mailbox.sync",
        "get_message_with_attachments",
        [{
          uid: msg.id,
          folder_id: msg.folder_id || this.state.currentFolderId,
          account_id: msg.account_id[0],
          backend: msg.backend_type,
          is_internal_draft: msg.is_internal_draft,
        }]
      );
      if (this._selTok !== token) return;

      if (Array.isArray(fullMsg.parent_chain)) {
        fullMsg.parent_chain = fullMsg.parent_chain.map((m) => ({
          ...m,
          avatar_html: markup(m.avatar_html || ""),
        }));
      }
      fullMsg.avatar_html = markup(fullMsg.avatar_html || "");

      this.state.selectedMessage = fullMsg;

      if (wasUnread) {
        msg.is_read = true;

        const idx = this.state.messages.findIndex((m) => m.id === msg.id);
        if (idx !== -1) {
          this.state.messages[idx].is_read = true;
        }

        if (this.state.currentFolderId) {
          const changed = this._bumpFolderUnread(this.state.currentFolderId, -1);
          if (changed) {
            const accId = this.state.currentAccount;
            const tree = this.state.foldersByAccount[accId] || [];
            this.state.foldersByAccount = {
              ...this.state.foldersByAccount,
              [accId]: [...tree],
            };
          }
        }
      }

      this.updateURLHash();

      requestAnimationFrame(() =>
        setTimeout(() => this.autoResizeAllIframes(), 200)
      );
    } catch (e) {
      if (this._selTok !== token) return;
      this.state.selectedMessage = null;
    } finally {
      if (this._selTok === token) this.state.isLoadingMessage = false;
    }
  }

  async trustEmailOnce(message) {
    this.state.selectedMessage.force_show_content = true;
  }

  async createPartnerFromMessage(msg) {
    if (!msg?.id || !msg?.email_from) return;

    try {
      const action = await this.orm.call("mailbox.sync", "action_open_create_partner", [
        msg.id,
        msg.email_from,
        msg.sender_display_name,
      ]);

      await this.actionService.doAction(action);

      msg.avatar_partner_id = action.res_id;
      this.state.selectedMessage.avatar_partner_id = action.res_id;
      this.notification.add(_t("Contact created and linked."), { type: "success" });

    } catch (err) {
      console.error(err);
      this.notification.add(_t("Failed to create contact."), { type: "danger" });
    }
  }

  async trustPartner(msg) {
    if (!msg?.id) return;

    try {
      const result = await this.orm.call("mailbox.sync", "mark_partner_trusted", [
        msg,
      ]);
      const partnerId = result.partner_id;

      msg.avatar_partner_id = partnerId;

      this.notification.add(_t("Partner marked as trusted."), {
        type: "success",
      });

      if (this.state.selectedMessage?.id === msg.id) {
        this.state.selectedMessage.avatar_partner_id = partnerId;
        this.state.selectedMessage.partner_trusted = true;
      }

      await this.selectMessage(this.state.selectedMessage);
    } catch (err) {
      console.error(err);
      this.notification.add(_t("Failed to mark partner as trusted."), {
        type: "danger",
      });
    }
  }

  autoResizeAllIframes() {
    setTimeout(() => {
      const iframes = document.querySelectorAll("iframe.email-preview-iframe");
      for (const iframe of iframes) {
        this.autoResizeIframe(iframe);
      }
    }, 100);
  }

  autoResizeIframe(iframe) {
    if (!iframe) return;
    iframe.style.height = "auto";
    try {
      const doc = iframe.contentDocument || iframe.contentWindow.document;
      const height = Math.max(
        doc.body?.scrollHeight || 0,
        doc.documentElement?.scrollHeight || 0
      );

      iframe.style.height = height + "px";
    } catch (err) {
      console.warn("Iframe resize failed:", err);
    }
  }

  generateIframeSrcdoc(body_original) {
  return `<!DOCTYPE html>
  <html>
  <head>
    <meta charset="utf-8">
    <!-- Odoo Bootstrap -->
    <link rel="stylesheet" href="/web/static/lib/bootstrap/dist/css/bootstrap.css">
    <style>
      body {
        font-family: Arial, sans-serif;
        font-size: 14px;
        line-height: 1.6;
        margin: 0;
        padding: 10px;
      }
      img {
        max-width: 100%;
        height: auto;
      }
      blockquote {
        border-left: 4px solid #ccc;
        padding-left: 1em;
        color: #555;
        background: #f9f9f9;
      }
    </style>
  </head>
  <body>
    ${body_original || ""}
    <script>
      document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("a").forEach(function (a) {
          a.addEventListener("click", function (e) {
            const href = a.getAttribute("href");
            const target = a.getAttribute("target");
            if (href && target === "_blank") {
              e.preventDefault();
              window.top.open(href, "_blank", "noopener,noreferrer");
            }
          });
        });
      });
    </script>
  </body>
  </html>`;
  }

  getIframeSandbox(message) {
    if (message.force_show_content || message.partner_trusted) {
      return "allow-scripts allow-same-origin allow-popups";
    }
    return "allow-same-origin";
  }

  formatUserDate(dateStr) {
    return dateStr;
  }

  onKeyDown = async (ev) => {
    const tag = ev.target.tagName;
    const isTextInput =
      ["INPUT", "TEXTAREA"].includes(tag) || ev.target.isContentEditable;
    if (isTextInput) return;

    const msgs = this.state.messages;
    if (!msgs.length || !["ArrowUp", "ArrowDown"].includes(ev.key)) return;

    const curIdx = msgs.findIndex((m) => m.id === this.state.selectedMessage?.id);
    if (curIdx === -1) return;

    ev.preventDefault();

    let tgtIdx = curIdx;
    if (ev.key === "ArrowUp" && curIdx > 0) tgtIdx = curIdx - 1;
    if (ev.key === "ArrowDown" && curIdx < msgs.length - 1) tgtIdx = curIdx + 1;

    const tgtMsg = msgs[tgtIdx];
    if (!tgtMsg) return;

    if (ev.shiftKey) {
      if (this.shiftAnchor === null) this.shiftAnchor = curIdx;
      const [a, b] = [this.shiftAnchor, tgtIdx].sort((x, y) => x - y);
      this.state.selectedIds = msgs.slice(a, b + 1).map((m) => m.id);
    } else {
      this.shiftAnchor = null;
      this.state.selectedIds = [];
    }

    await this.selectMessage(tgtMsg);
  };

  _onClickAnywhere = () => {
    if (this.contextMenu) {
      this.contextMenu.remove();
      this.contextMenu = null;
    }
  };

  onClickPartner(ev, partnerId) {
    if (partnerId) {
      if (typeof partnerId !== "number") {
        return;
      }
      this.partnerCard.open(ev.currentTarget, {id: partnerId});
    }
  }

  async onClickViewProfile(partnerId) {
    const action = {
      type: "ir.actions.act_window",
      res_model: "res.partner",
      res_id: partnerId,
      views: [[false, "form"]],
      view_mode: "form",
    };
    this.actionService.doAction(action);
  }

  async openDraftComposer(msg) {
    this.dialog.add(ComposeMail, {
      msgID: msg.id,
      draft: true,
    });
  }

  async openComposer() {
    this.dialog.add(ComposeMail, {});
  }

  async openReplyComposer(msg) {
    this.dialog.add(ComposeMail, {
      msgID: msg.id,
      reply: true,
      account_id: msg.account_id?.[0],
    });
  }

  async openReplyAllComposer(msg) {
    this.dialog.add(ComposeMail, {
      msgID: msg.id,
      replyAll: true,
      account_id: msg.account_id?.[0],
    });
  }

  async openForwardComposer(msg) {
    this.dialog.add(ComposeMail, {
      msgID: msg.id,
      forward: true,
    });
  }

  async clearContactFilter() {
    this.state.partnerId = null;
    this.state.emailFrom = null;
    this.state.partnerName = null;
    await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
  }

  async openContactSelector() {
    this.dialog.add(ContactPickerDialog, {
      onSelect: async (partnerId) => {
        if (!partnerId) {
          this.clearContactFilter();
          return;
        }
        const [p] = await this.orm.read(
          "res.partner",
          [partnerId],
          ["id", "name", "email"]
        );
        this.state.partnerId = p.id;
        this.state.emailFrom = p.email;
        this.state.partnerName = p.name;
        await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
      },
    });
  }

  resetFilters = async (all = null) => {
    this.state.currentFolderId = null;
    this.state.currentAccount = null;

    if (all) {
      this.state.currentFilter = "all";
      this.state.searchQuery = "";
    }

    this.clearSelection();
    this.updateURLHash();
    await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
  };

  toggleStar = async (msg) => {
    msg.is_starred = !msg.is_starred;
    await this.orm.write("mailbox.sync", [msg.id], {
      is_starred: msg.is_starred,
    });
  };

  async printMessage(msg = null) {
    if (msg) {
      this.selectMessage(msg);
    }
    setTimeout(() => {
      print();
    }, 900);
  }

  onSearchInput = (ev) => {
    this.state.searchQuery = ev.target.value;
    this.onDelayedSearch();
  };

  filterBy = (filterType) => {
    this.state.currentFilter = filterType;
    this.updateURLHash();
    this.refreshMessages().then(() => this._fetchUnreadCounters());
  };

  filterByFolder = async (folderId) => {
    this.state.currentFolderId = folderId;
    this.updateURLHash();
    await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
  };

  filterByAccount = async (accountId) => {
    this.state.currentAccount = accountId;
    this.state.currentFolderId = null;
    this.updateURLHash();

    const accountElement = document.querySelector(`h6[data-account-id="${accountId}"]`);
    if (accountElement) {
      const folderList = document.querySelector(`#folders-${accountId}`);
      if (folderList && !folderList.classList.contains("show")) {
        const toggleButton = accountElement.querySelector(".folder-toggle-icon");
        if (toggleButton) {
          toggleButton.click();
        }
      }
    }
    await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
  };

  filterByTag = async (tagId) => {
    const idx = this.state.selectedTagId.indexOf(tagId);
    if (idx === -1) {
      this.state.selectedTagId.push(tagId);
    } else {
      this.state.selectedTagId.splice(idx, 1);
    }
    this.updateURLHash();
    await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
  };

  filterByFolderAndAccount = async (folderId, accountId) => {
      this.state.currentFolderId = folderId;
      this.state.currentAccount = accountId;

      this._expandFolderParents(folderId);
      this.updateURLHash();

      await this.showListSkeletonWhile(async () => {
          await this.refreshMessages();
          setTimeout(() => this._fetchUnreadCounters(), 100);
      });
  };

  _expandFolderParents(folderId) {
    if (!folderId) return;

    if (this.state.currentAccount) {
        this.state.expandedFolderIds.push(this.state.currentAccount);
    }

    const tree = this.state.foldersByAccount[this.state.currentAccount] || [];
    const findAndExpand = (nodes) => {
        for (const node of nodes) {
            if (node.id === folderId) {
                this.state.expandedFolderIds.push(node.id);
                return true;
            }
            if (node.children?.length) {
                if (findAndExpand(node.children)) {
                    this.state.expandedFolderIds.push(node.id);
                    return true;
                }
            }
        }
        return false;
    };

    findAndExpand(tree);
}

  _findFolderById(folderId) {
      for (const accountId in this.state.foldersByAccount) {
          const tree = this.state.foldersByAccount[accountId];
          const search = (nodes) => {
              for (const node of nodes) {
                  if (node.id === folderId) return node;
                  if (node.children?.length) {
                      const found = search(node.children);
                      if (found) return found;
                  }
              }
              return null;
          };
          const found = search(tree);
          if (found) return found;
      }
      return null;
  }

  async _fetchUnreadCounters() {
    if (!this.state.currentAccount || !this.state.currentFolderId) return;

    const domainFilters = {};
    if (this.state.partnerId) domainFilters.partner_id = this.state.partnerId;
    if (this.state.emailFrom) domainFilters.email_from = this.state.emailFrom;

    try {
      const res = await this.orm.call("mailbox.sync", "unread_counts_for_folder", [], {
        account_id: this.state.currentAccount,
        folder_id: this.state.currentFolderId,
        flt: this.state.currentFilter,
        text: this.state.searchQuery,
        ...domainFilters,
      });

      this.state.currentFolderUnreadTotal = res.unread_total;
      this.state.currentFolderUnreadFiltered = res.unread_filtered;

      const val = this._useFilteredCount() ? res.unread_filtered : res.unread_total;
      const changed = this._setFolderUnread(this.state.currentFolderId, val);

      if (changed) {
        const accId = this.state.currentAccount;
        const tree = this.state.foldersByAccount[accId] || [];
        this.state.foldersByAccount = {
          ...this.state.foldersByAccount,
          [accId]: [...tree],
        };
      }
    } catch (e) {
      console.warn("unread counters failed", e);
    }
  }

  _setFolderUnread(folderId, unread) {
    const accId = this.state.currentAccount;
    if (!accId) return false;

    let changed = false;

    const walk = (nodes) => {
      for (const f of nodes) {
        if (f.id === folderId) {
          const next = unread || 0;
          if (f.unread_count !== next) {
            f.unread_count = next;
            changed = true;
          }
          return true;
        }
        if (f.children && walk(f.children)) return true;
      }
      return false;
    };

    const tree = this.state.foldersByAccount[accId] || [];
    walk(tree);
    return changed;
  }

  _bumpFolderUnread(folderId, delta) {
    if (!delta) return false;
    const accId = this.state.currentAccount;
    if (!accId) return false;

    let changed = false;

    const walk = (nodes) => {
      for (const f of nodes) {
        if (f.id === folderId) {
          const cur = f.unread_count || 0;
          const next = Math.max(0, cur + delta);
          if (cur !== next) {
            f.unread_count = next;
            changed = true;
          }
          return true;
        }
        if (f.children && walk(f.children)) return true;
      }
      return false;
    };

    const tree = this.state.foldersByAccount[accId] || [];
    walk(tree);
    return changed;
  }

  _useFilteredCount() {
    return (
      (this.state.currentFilter && this.state.currentFilter !== "all") ||
      (this.state.searchQuery && this.state.searchQuery.trim()) ||
      (this.state.selectedTagId && this.state.selectedTagId.length) ||
      this.state.partnerId || this.state.emailFrom
    );
  }

  async showListSkeletonWhile(callbackOrPromise) {
    const token = (this._skelTok = (this._skelTok || 0) + 1);
    const curTok = token;

    this.state.messages = [];
    this.state.totalMessagesCount = 0;

    this.state.isRefreshing = true;
    this.render();

    const delay = new Promise((r) => setTimeout(r, 150));

    try {
      const resultPromise =
        typeof callbackOrPromise === "function"
          ? callbackOrPromise()
          : callbackOrPromise;

      await Promise.allSettled([delay, resultPromise]);
    } catch (err) {
      console.error("[MailDesk] Skeleton-wrapped action failed:", err);
    } finally {
      if (curTok === this._skelTok) {
        this.state.isRefreshing = false;
        this.render();
      }
    }
  }

  getUrlParams() {
    return new URLSearchParams(window.location.hash.slice(1));
  }

  updateURLHash() {
    const hashParams = new URLSearchParams();

    if (this.state.currentAccount !== null) {
      hashParams.set("account", this.state.currentAccount);
    } else {
      hashParams.delete("account");
    }

    if (this.state.currentFolderId !== null) {
      hashParams.set("folder", this.state.currentFolderId);
    } else {
      hashParams.delete("folder");
    }

    if (this.state.currentFilter) {
      hashParams.set("filter", this.state.currentFilter);
    } else {
      hashParams.delete("filter");
    }

    if (this.state.selectedMessage?.id) {
      hashParams.set("mail", this.state.selectedMessage.id);
    } else {
      hashParams.delete("mail");
    }

    if (this.state.selectedTagId.length) {
      hashParams.set("tags", this.state.selectedTagId.join(","));
    } else {
      hashParams.delete("tags");
    }

    const newHash = `#${hashParams.toString()}`;
    if (window.location.hash !== newHash) {
      history.replaceState(null, "", newHash);
    }
  }

  async openLinkedDocument(msg = null) {
      const message = msg || this.state.selectedMessage;
      if (!message?.model || !message?.res_id) return;

      const action = await this.orm.call("mailbox.sync", "get_open_document_action", [
          message.model,
          message.res_id,
      ]);

      if (action) {
          this.actionService.doAction(action);
      } else {
          this.env.services.notification.add("No linked document available", {
              type: "warning",
          });
      }
  }

  isAllFilterActive() {
    return !this.state.currentAccount && !this.state.currentFolderId;
  }

  refreshFolderTree = async () => {
    const foldersByAccount = {};
    const domainFilters = {};
    if (this.state.partnerId) {
      domainFilters.partner_id = this.state.partnerId;
    }
    if (this.state.emailFrom) {
      domainFilters.email_from = this.state.emailFrom;
    }
    for (const account of this.state.accounts) {
      try {
        const folders = await this.orm.call("mailbox.folder", "get_folder_tree", [
          account.id,
          domainFilters,
        ]);
        foldersByAccount[account.id] = folders;
      } catch (err) {
        console.error(`Error loading folders for account ${account.id}:`, err);
      }
    }
    this.state.foldersByAccount = foldersByAccount;
  };

  async openAssignTagsDialog(msg = null) {
      const ids = msg?.id
          ? [msg.id]
          : this.state.selectedIds.length
          ? this.state.selectedIds
          : this.state.selectedMessage?.id
          ? [this.state.selectedMessage.id]
          : [];

      if (!ids.length) {
          this.notification.add("No message selected.", { type: "warning" });
          return;
      }

      const tags = await this.orm.searchRead(
          "mail.message.tag",
          [],
          ["id", "name", "color"]
      );

      const selectedTagIds = new Set();

      for (const id of ids) {
          let msgObj = this.state.messages.find((m) => m.id === id);

          if (!msgObj && this.state.selectedMessage && this.state.selectedMessage.id === id) {
              msgObj = this.state.selectedMessage;
          }

          if (msgObj?.tag_ids?.length) {
              for (const tag of msgObj.tag_ids) {
                  if (typeof tag === "number") {
                      selectedTagIds.add(tag);
                  }
                  else if (tag && typeof tag.id === "number") {
                      selectedTagIds.add(tag.id);
                  }
              }
          }
      }

      this.dialog.add(AssignTagsDialog, {
          tags,
          selectedTagIds,
          onSelect: async (finalTagIds, { close }) => {
              await this.orm.call("mailbox.sync", "update_tags", [ids, finalTagIds]);

              const tagById = new Map(tags.map((t) => [t.id, t]));
              const newTagObjs = finalTagIds
                  .map((id) => tagById.get(id))
                  .filter(Boolean)
                  .map((t) => ({ ...t }));

              for (const id of ids) {
                  const msg = this.state.messages.find((m) => m.id === id);
                  if (msg) {
                      msg.tag_ids = newTagObjs;
                  }
                  if (this.state.selectedMessage && this.state.selectedMessage.id === id) {
                      this.state.selectedMessage.tag_ids = newTagObjs;
                  }
              }

              close();
          },
      });
  }

  async openMoveToFolderDialog(msg = null) {
    const ids = msg?.id
      ? [msg.id]
      : this.state.selectedIds.length
      ? this.state.selectedIds
      : this.state.selectedMessage?.id
      ? [this.state.selectedMessage.id]
      : [];

    if (!ids.length) {
      this.notification.add("No message selected to move.", {
        type: "warning",
      });
      return;
    }

    const accountId =
      msg?.account_id?.[0] ||
      this.state.selectedMessage?.account_id?.[0] ||
      this.state.messages.find((m) => m.id === ids[0])?.account_id?.[0];

    if (!accountId) {
      this.notification.add("No account found for selected message.", {
        type: "danger",
      });
      return;
    }

    const folders = this.getFolderTree(accountId).filter(
      (f) => !f.is_trash && !f.is_archive
    );

    this.dialog.add(MoveToFolderDialog, {
      folders,
      onSelect: async (folder, {close}) => {
        await this.orm.call("mailbox.sync", "move_messages_to_folder", [
          ids,
          folder.id,
        ]);
        close();
        this.clearSelection();
        await this.refreshFolderTree();
        await this._fetchUnreadCounters();
      },
    });
  }

  get currentFolderName() {
    if (!this.state.currentAccount || !this.state.currentFolderId) return null;
    const folders = this.getFolderTree(this.state.currentAccount);
    const folder = folders.find((f) => f.id === this.state.currentFolderId);
    return folder ? folder.name : null;
  }

  getFolderIconSrc(folder) {
    const code = (folder.folder_type || "").toLowerCase();

    const map = {
      read: "read.svg",
      unread: "unread.svg",
      move: "move.svg",
      inbox: "inbox.svg",
      sent: "sent.svg",
      sent_mail: "sent.svg",
      drafts: "drafts.svg",
      draft: "drafts.svg",
      trash: "trash.svg",
      bin: "trash.svg",
      archive: "archive.svg",
      all_mail: "archive.svg",
      spam: "spam.svg",
      junk: "spam.svg",
      starred: "starred.svg",
      flagged: "starred.svg",
    };

    const fileName = map[code] || "folder.svg";
    return `/maildesk_mail_client/static/src/icons/${fileName}`;
  }

  getFolderTree(accountId) {
    return this.state.foldersByAccount[accountId] || [];
  }

  onMessageRightClick(ev, msg) {
    ev.preventDefault();
    if (this.contextMenu) this.contextMenu.remove();
    const items = [
      {id: "reply", label: _t("Reply"), show: true},
      {id: "reply_all", label: _t("Reply All"), show: true},
      {id: "forward", label: _t("Forward"), show: true},
      {id: "mark_read", label: _t("Mark as Read"), show: !msg.is_read},
      {
        id: "mark_unread",
        label: _t("Mark as Unread"),
        show: msg.is_read,
      },
      {
        id: "star",
        label: msg.is_starred ? _t("Remove Star") : _t("Add Star"),
        show: true,
      },
      {id: "move", label: _t("Move to Folder…"), show: true},
      {
        id: "tag",
        label: _t("Assign Tags…"),
        show: Boolean(this.state.tags.length),
      },
      {
        id: "contact",
        label: _t("Create Contact"),
        show: !msg.avatar_partner_id,
      },
      {
        id: "open_contact",
        label: _t("Open Contact"),
        show: Boolean(msg.avatar_partner_id),
      },
      {
        id: "open_doc",
        label: _t("Open Linked Document"),
        show: Boolean(msg.model && msg.res_id),
      },
      {id: "print", label: _t("Print"), show: true},
      {id: "delete", label: _t("Delete"), show: true},
    ];
    const menu = document.createElement("div");
    menu.className = "custom-context-menu";
    const ul = document.createElement("ul");
    items
      .filter((i) => i.show)
      .forEach((i) => {
        const li = document.createElement("li");
        li.dataset.action = i.id;
        li.textContent = i.label;
        ul.appendChild(li);
      });
    menu.appendChild(ul);
    document.body.appendChild(menu);
    const {clientX: x, clientY: y} = ev;
    const w = menu.offsetWidth,
      h = menu.offsetHeight;
    const left = Math.max(0, Math.min(x, window.innerWidth - w - 4));
    const top = Math.max(0, Math.min(y, window.innerHeight - h - 4));
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    this.contextMenu = menu;
    menu.addEventListener("click", (e) => {
      const a = e.target?.dataset?.action;
      if (!a) return;
      switch (a) {
        case "reply":
          this.openReplyComposer(msg);
          break;
        case "reply_all":
          this.openReplyAllComposer(msg);
          break;
        case "forward":
          this.openForwardComposer(msg);
          break;
        case "mark_read":
          this.markSelectedAsRead(msg);
          break;
        case "mark_unread":
          this.markSelectedAsUnread(msg);
          break;
        case "star":
          this.toggleStar(msg);
          break;
        case "move":
          this.openMoveToFolderDialog(msg);
          break;
        case "tag":
          this.openAssignTagsDialog(msg);
          break;
        case "contact":
          this.createPartnerFromMessage(msg);
          break;
        case "open_contact":
          this.onClickViewProfile(msg.avatar_partner_id);
          break;
        case "open_doc":
          this.openLinkedDocument(msg);
          break;
        case "delete":
          this.deleteSelected(msg);
          break;
        case "print":
          this.printMessage(msg);
          break;
      }
      this.contextMenu.remove();
      this.contextMenu = null;
    });
  }

markSelectedAsRead = async (msg = null) => {
  const baseIds = msg?.id
    ? [msg.id]
    : this.state.selectedIds.length
    ? this.state.selectedIds
    : this.state.selectedMessage?.id
    ? [this.state.selectedMessage.id]
    : [];
  if (!baseIds.length) return;

  await this.orm.call("mailbox.sync", "set_flags", [baseIds], {
    is_read: true,
    folder_id: this.state.currentFolderId || null,
  });

  let delta = 0;

  this.state.messages.forEach((m) => {
    if (baseIds.includes(m.id) && !m.is_read) {
      m.is_read = true;
      delta -= 1;
    }
  });

  if (this.state.selectedMessage && baseIds.includes(this.state.selectedMessage.id) && !this.state.selectedMessage.is_read) {
    this.state.selectedMessage.is_read = true;
    delta -= 1;
  }

  if (delta && this.state.currentFolderId) {
    const changed = this._bumpFolderUnread(this.state.currentFolderId, delta);
    if (changed) {
      const accId = this.state.currentAccount;
      const tree = this.state.foldersByAccount[accId] || [];
      this.state.foldersByAccount = { ...this.state.foldersByAccount, [accId]: [...tree] };
    }
  }
};


markSelectedAsUnread = async (msg = null) => {
  const ids = msg?.id
    ? [msg.id]
    : this.state.selectedIds.length
    ? this.state.selectedIds
    : this.state.selectedMessage?.id
    ? [this.state.selectedMessage.id]
    : [];
  if (!ids.length) return;

  await this.orm.call("mailbox.sync", "set_flags", [ids], {
    is_read: false,
    folder_id: this.state.currentFolderId || null,
  });

  let delta = 0;

  this.state.messages.forEach((m) => {
    if (ids.includes(m.id) && m.is_read) {
      m.is_read = false;
      delta += 1;
    }
  });

  if (this.state.selectedMessage && ids.includes(this.state.selectedMessage.id) && this.state.selectedMessage.is_read) {
    this.state.selectedMessage.is_read = false;
    delta += 1;
  }

  if (delta && this.state.currentFolderId) {
    const changed = this._bumpFolderUnread(this.state.currentFolderId, delta);
    if (changed) {
      const accId = this.state.currentAccount;
      const tree = this.state.foldersByAccount[accId] || [];
      this.state.foldersByAccount = { ...this.state.foldersByAccount, [accId]: [...tree] };
    }
  }

};

toggleSelectMode = () => {
  this.state.selectMode = !this.state.selectMode;
  if (!this.state.selectMode) this.clearSelection();
};

toggleSelection(id) {
  const idx = this.state.selectedIds.indexOf(id);
  if (idx === -1) this.state.selectedIds.push(id);
  else this.state.selectedIds.splice(idx, 1);
  this.state.allSelected = this.state.selectedIds.length === this.state.messages.length;
}

toggleAllSelection() {
  this.state.allSelected ? this.clearSelection() : this.selectAll();
}

clearSelection() {
  this.state.selectedIds = [];
  this.state.allSelected = false;
}

selectAll() {
  this.state.selectedIds = this.state.messages.map((m) => m.id);
  this.state.allSelected = true;
}

archiveSelected = (msg = null) => this.moveMessagesToFolder("is_archive", msg);

isExclusiveFolderCode(code) {
  return ["inbox", "trash", "archive"].includes((code || "").toLowerCase());
}

deleteSelected = async (msg = null) => {
  const ids = msg?.id
    ? [msg.id]
    : this.state.selectedIds.length
    ? this.state.selectedIds
    : this.state.selectedMessage?.id
    ? [this.state.selectedMessage.id]
    : [];
  if (!ids.length) return;

  this.state.hiddenMessageIds.push(...ids);
  await this.showUndoableTrashNotification(ids);
};

async showUndoableTrashNotification(ids) {
  const textMoved = _t("Moved to Trash");
  const textUndo = _t("Undo");

  const toast = document.createElement("div");
  toast.className = "maildesk-toast-wrapper";
  toast.innerHTML = `
      <div class="toast fade-in">
          <div class="toast-content">
              <span>${textMoved}</span>
              <button type="button" class="undo-btn">${textUndo}</button>
          </div>
          <div class="toast-progress"></div>
      </div>
  `;
  document.body.appendChild(toast);

  const toastBox = toast.querySelector(".toast");
  const undoBtn = toast.querySelector(".undo-btn");
  let undone = false;

  const closeToast = () => {
    toastBox.classList.remove("fade-in");
    toastBox.classList.add("fade-out");
    setTimeout(() => toast.remove(), 300);
  };

  undoBtn.addEventListener("click", () => {
    undone = true;
    this.state.hiddenMessageIds = this.state.hiddenMessageIds.filter((id) => !ids.includes(id));
    closeToast();
  });

  setTimeout(async () => {
  if (!undone) {
    try {
      await this.orm.call("mailbox.sync", "delete_messages", [], {
        ids,
        folder_id: this.state.currentFolderId || null,
      });
    } catch (e) {
      console.error("[MailDesk] delete_messages RPC failed", e);
    }

    let delta = 0;
    this.state.messages.forEach((m) => {
      if (ids.includes(m.id) && !m.is_read) {
        delta -= 1;
      }
    });

    if (delta && this.state.currentFolderId) {
      const changed = this._bumpFolderUnread(this.state.currentFolderId, delta);
      if (changed) {
        const accId = this.state.currentAccount;
        const tree = this.state.foldersByAccount[accId] || [];
        this.state.foldersByAccount = { ...this.state.foldersByAccount, [accId]: [...tree] };
      }
    }

    this.state.messages = this.state.messages.filter((msg) => !ids.includes(msg.id));
    this.state.hiddenMessageIds = this.state.hiddenMessageIds.filter((id) => !ids.includes(id));
  }

  closeToast();
}, 5000);

}

async moveMessagesToFolder(folderType, msgOrIds = null) {
  let ids = [];
  if (Array.isArray(msgOrIds)) ids = msgOrIds;
  else if (msgOrIds?.ids) ids = msgOrIds.ids;
  else if (msgOrIds?.id) ids = [msgOrIds.id];
  else if (this.state.selectedIds.length) ids = this.state.selectedIds;
  else if (this.state.selectedMessage?.id) ids = [this.state.selectedMessage.id];
  if (!ids.length) return;

  const targets = [];
  for (const msg of this.state.messages) {
    if (!ids.includes(msg.id)) continue;
    const accountId = msg.account_id?.[0];
    const folders = this.state.foldersByAccount[accountId] || [];
    const folder = folders.find((f) => f[folderType]);
    if (folder) targets.push(folder.id);
  }
  const uniqTargetId = [...new Set(targets)][0] || null;
  if (!uniqTargetId) return;

  await this.orm.call("mailbox.sync", "move_messages_to_folder", [ids, uniqTargetId]);

  this.clearSelection();
  await this.refreshFolderTree();
  await this.showListSkeletonWhile(async () => {
    await this.refreshMessages();
    setTimeout(() => this._fetchUnreadCounters(), 100);
  });
}

toggleStarForSelected = async (msg = null) => {
  const ids = msg?.id
    ? [msg.id]
    : this.state.selectedIds.length
    ? this.state.selectedIds
    : this.state.selectedMessage?.id
    ? [this.state.selectedMessage.id]
    : [];
  if (!ids.length) return;

  const currentValues = ids.map((id) => {
    const m =
      this.state.messages.find((x) => x.id === id) ||
      (this.state.selectedMessage?.id === id ? this.state.selectedMessage : null);
    return m?.is_starred || false;
  });
  const newValue = !currentValues.every((v) => v);

  this.state.messages = this.state.messages.map((m) =>
    ids.includes(m.id) ? { ...m, is_starred: newValue } : m
  );
  if (this.state.selectedMessage && ids.includes(this.state.selectedMessage.id)) {
    this.state.selectedMessage.is_starred = newValue;
    if (Array.isArray(this.state.selectedMessage.parent_chain)) {
      this.state.selectedMessage.parent_chain = this.state.selectedMessage.parent_chain.map((m) =>
        ids.includes(m.id) ? { ...m, is_starred: newValue } : m
      );
    }
  }

  await this.orm.call("mailbox.sync", "set_flags", [ids], {
    is_starred: newValue,
    folder_id: this.state.currentFolderId || null,
  });
};

  onFilterButtonClick(ev) {
    ev.preventDefault();
    ev.stopPropagation();

    this.contextMenu?.remove();

    const items = [
      {id: "filter_contact", label: _t("By Contact")},
      {id: "filter_incoming", label: _t("Incoming")},
      {id: "filter_outgoing", label: _t("Outgoing")},
      {id: "filter_unread", label: _t("Only Unread")},
      {id: "filter_starred", label: _t("Only Starred")},
      {id: "reset_filters", label: _t("Reset")},
    ];

    const menu = document.createElement("div");
    menu.className = "custom-context-menu";
    const ul = document.createElement("ul");
    items.forEach(({id, label}) => {
      const li = document.createElement("li");
      li.dataset.action = id;
      li.textContent = label;
      ul.appendChild(li);
    });
    menu.appendChild(ul);
    document.body.appendChild(menu);

    const r = ev.currentTarget.getBoundingClientRect();
    requestAnimationFrame(() => {
      const w = menu.offsetWidth,
        h = menu.offsetHeight,
        l = Math.max(0, Math.min(r.left, innerWidth - w - 8)),
        t = Math.max(0, Math.min(r.bottom + 6, innerHeight - h - 8));
      menu.style.left = l + "px";
      menu.style.top = t + "px";
    });

    this.contextMenu = menu;

    const handler = (e) => {
      const act = e.target?.dataset?.action;
      if (!act) return;
      switch (act) {
        case "filter_contact":
          this.openContactSelector();
          break;
        case "filter_incoming":
          this.filterBy("incoming");
          break;
        case "filter_outgoing":
          this.filterBy("outgoing");
          break;
        case "filter_unread":
          this.filterBy("unread");
          break;
        case "filter_starred":
          this.filterBy("starred");
          break;
        case "reset_filters":
          this.resetFilters(true);
          break;
      }
      menu.remove();
      this.contextMenu = null;
      document.removeEventListener("click", outside);
    };

    const outside = (e) => {
      if (!menu.contains(e.target)) {
        menu.remove();
        this.contextMenu = null;
        document.removeEventListener("click", outside);
      }
    };

    menu.addEventListener("click", handler);
    setTimeout(() => document.addEventListener("click", outside), 0);
  }

  _getIndexById(id) {
    for (let i = 0; i < this.state.messages.length; i++) {
      if (this.state.messages[i].id === id) return i;
    }
    return -1;
  }

  _insertOrUpdateSorted(newMsgs) {
    const list = this.state.messages;
    const seen = new Set(list.map(m => this._msgKey(m)));
    const nowTs = Date.now();

    for (const nm of newMsgs) {
      if (nm.avatar_html) nm.avatar_html = markup(nm.avatar_html);
      if (nm.uid != null) nm.uid = Number(nm.uid);
      const key = this._msgKey(nm);

      const hasValidDate = nm.date && !isNaN(new Date(nm.date).getTime());
      nm._sort_ts = hasValidDate ? new Date(nm.date).getTime() : nowTs;

      const idx = this._getIndexByKey(key);
      if (idx !== -1) {
        Object.assign(list[idx], nm);
      } else if (!seen.has(key)) {
        list.push(nm);
        seen.add(key);
      }
    }

    list.sort((a, b) => {
      const aTs = a._sort_ts ?? (a.date ? new Date(a.date).getTime() : 0);
      const bTs = b._sort_ts ?? (b.date ? new Date(b.date).getTime() : 0);
      return bTs - aTs;
    });

    const MAX_ROWS = 500;
    if (list.length > MAX_ROWS) list.length = MAX_ROWS;
  }

  _removeByIds(ids) {
    if (!ids?.length) return;
    const idset = new Set(ids);
    for (const id of ids) if (!this.state.hiddenMessageIds.includes(id)) this.state.hiddenMessageIds.push(id);

    setTimeout(() => {
      this.state.messages = this.state.messages.filter(m => !idset.has(m.id));
      this.state.hiddenMessageIds = this.state.hiddenMessageIds.filter(id => !idset.has(id));
      if (this.state.selectedMessage && idset.has(this.state.selectedMessage.id)) {
        this.state.selectedMessage = null;
      }
    }, 150);
  }

  _removeByKeys(keys) {
    if (!keys?.length) return;
    const kset = new Set(keys);
    for (const m of this.state.messages) {
      if (kset.has(this._msgKey(m)) && !this.state.hiddenMessageIds.includes(m.id)) {
        this.state.hiddenMessageIds.push(m.id);
      }
    }
    setTimeout(() => {
      this.state.messages = this.state.messages.filter(m => !kset.has(this._msgKey(m)));
      this.state.hiddenMessageIds = this.state.hiddenMessageIds.filter(id =>
        this.state.messages.some(m => m.id === id)
      );
      if (this.state.selectedMessage && kset.has(this._msgKey(this.state.selectedMessage))) {
        this.state.selectedMessage = null;
      }
    }, 150);
  }

  _updateFlagsByKey(flagsByKey) {
    if (!flagsByKey) return;
    for (const m of this.state.messages) {
      const f = flagsByKey[this._msgKey(m)];
      if (!f) continue;
      if (typeof f.seen === "boolean") m.is_read = f.seen;
      if (typeof f.starred === "boolean") m.is_starred = f.starred;
    }
    if (this.state.selectedMessage) {
      const f = flagsByKey[this._msgKey(this.state.selectedMessage)];
      if (f) {
        if (typeof f.seen === "boolean") this.state.selectedMessage.is_read = f.seen;
        if (typeof f.starred === "boolean") this.state.selectedMessage.is_starred = f.starred;
      }
    }
  }

  _buildUidIndex() {
    const idx = new Map();
    this.state.messages.forEach((m, i) => {
      const uid = m.uid ?? null;
      if (!uid) return;
      const arr = idx.get(uid) || [];
      arr.push(i);
      idx.set(uid, arr);
    });
    return idx;
  }

  _updateFlagsByKey(flagsByKey) {
    if (!flagsByKey) return;
    const uidIdx = this._buildUidIndex();
    for (const m of this.state.messages) {
      const k = this._msgKey(m);
      const f = flagsByKey[k];
      if (!f) continue;
      if (typeof f.seen === "boolean") m.is_read = f.seen;
      if (typeof f.starred === "boolean") m.is_starred = f.starred;
    }
    for (const [k, f] of Object.entries(flagsByKey)) {
      const parts = k.split("|");
      const uid = parts[2] ? Number(parts[2]) : null;
      if (!uid || !uidIdx.has(uid)) continue;
      for (const i of uidIdx.get(uid)) {
        if (typeof f.seen === "boolean") this.state.messages[i].is_read = f.seen;
        if (typeof f.starred === "boolean") this.state.messages[i].is_starred = f.starred;
      }
    }
    if (this.state.selectedMessage) {
      const sk = this._msgKey(this.state.selectedMessage);
      const sf = flagsByKey[sk];
      if (sf) {
        if (typeof sf.seen === "boolean") this.state.selectedMessage.is_read = sf.seen;
        if (typeof sf.starred === "boolean") this.state.selectedMessage.is_starred = sf.starred;
      }
    }
  }
}

MailDesk.template = "maildesk_mail_client.MailDesk";
MailDesk.components = {
  AttachmentList,
  ComposeMail,
  ContactPickerDialog,
  AssignTagsDialog,
  MoveToFolderDialog,
};
registry.category("actions").add("maildesk_mail_client.maildesk", MailDesk);
