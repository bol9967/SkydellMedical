// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component, onWillStart, onWillUnmount, useState} from "@odoo/owl";
import {Wysiwyg} from "@html_editor/wysiwyg";
import {FileInput} from "@web/core/file_input/file_input";
import {_t} from "@web/core/l10n/translation";
import {localization} from "@web/core/l10n/localization";
import {useService} from "@web/core/utils/hooks";
import {EmailInputField} from "./email_input_field.esm.js";
import { HtmlMailField } from "@mail/views/web/fields/html_mail_field/html_mail_field";
import { markup } from "@odoo/owl";
import {user} from "@web/core/user";

export class ComposeMail extends Component {
  static components = {
    FileInput,
    EmailInputField,
    Wysiwyg,
  };
  static props = {
    to: {type: Array, optional: true},
    cc: {type: Array, optional: true},
    bcc: {type: Array, optional: true},
    accounts: {type: Array, optional: true},
    msgID: {type: String, optional: true},
    draft: {type: Boolean, optional: true},
    reply: {type: Boolean, optional: true},
    account_id: {type: Number, optional: true},
    replyAll: {type: Boolean, optional: true},
    forward: {type: Boolean, optional: true},
    close: {type: Function, optional: true},
  };

  setup() {
    this.componentId = Date.now() + Math.floor(Math.random() * 1000);
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.notification = useService("notification");
    this.lastSavedState = null;
    this.toggleCc = this.toggleCc.bind(this);
    this.toggleBcc = this.toggleBcc.bind(this);

    this.state = useState({
      subject: "",
      body: "",
      To: [],
      Cc: [],
      Bcc: [],
      inputTo: "",
      inputCc: "",
      inputBcc: "",
      showSuggestionsTo: false,
      showSuggestionsCc: false,
      showSuggestionsBcc: false,
      account_id: null,
      from_display: "",
      accounts: [],
      sending: false,
      attachments: [],
      showCc: false,
      showBcc: false,
      key: 0,
      wysiwygEditors: {},
      draftMessageId: null,
      reply_to_msg: null,
      request_read_receipt: false,
      request_delivery_receipt: false,
    });
    this.uiState = useState({
      isFull: false,
      isMinimized: false,
      position: {top: null, left: null},
      offset: {x: 0, y: 0},
      dragging: false,
      savedPosition: null,
    });

    onWillStart(async () => {
      if (this.props.draft) {
        await this.loadDraft();
      } else if (this.props.msgID) {
        await this.loadMessageForReplyOrForward();
      }

      const accounts = await this.orm.searchRead(
        "mailbox.account",
        [["access_user_ids", "in", [user.userId]]],
        ["id","name","email","sender_name"]
      );
      this.state.accounts = accounts;

      if (accounts.length) {
        const accFromData = accounts.find(a => a.id === this.state.account_id);
        const acc = accFromData || accounts[0];
        this.state.account_id = acc.id;
        this.setFromDisplay(acc);
      }
    });

    this.autoSaveInterval = setInterval(this.saveDraft.bind(this), 60000);
    onWillUnmount(() => {
      clearInterval(this.autoSaveInterval);
      window.removeEventListener("beforeunload", this.saveDraftBeforeUnload);
    });
  }

  setBody(html) {
    this.state.body = html || "";
    const wysiwygKey = `${this.componentId}_${this.state.key}`;
    const ed = this.state.wysiwygEditors[wysiwygKey];
    if (ed) {
      const el = ed.getElContent();
      if (el) ed.editable.innerHTML = this.state.body;
    }
  }

  async _lazyLoadAttachments(meta) {
    if (!meta || !meta.has_attachments || !meta.account_id || !meta.folder || !meta.uid) return;
    try {
      const atts = await this.orm.call("mailbox.sync", "get_message_attachments", [], {
        account_id: meta.account_id,
        folder: meta.folder,
        uid: meta.uid,
      });
      if (Array.isArray(atts) && atts.length) {
        this.state.attachments = atts.map(a => ({ id:a.id, name:a.name, mimetype:a.mimetype }));
      }
    } catch {}
  }

  async loadMessageForReplyOrForward() {
    const method = this.props.forward ? "prepare_forward" : "prepare_reply";
    const args = [this.props.msgID];
    const kwargs = this.props.forward ? {} : { reply_all: !!this.props.replyAll };
    const data = await this.orm.call("maildesk.message_cache", method, args, kwargs);

    this.state.subject = data.subject || "";
    this.state.body = data.body_html || "";
    this.state.To = (data.to || []).map(e => ({ email: e }));
    this.state.Cc = (data.cc || []).map(e => ({ email: e }));
    this.state.Bcc = (data.bcc || []).map(e => ({ email: e }));
    this.state.showCc = !!this.state.Cc.length;
    this.state.showBcc = !!this.state.Bcc.length;
    this.state.attachments = (data.attachments || []).map(a => ({ id:a.id, name:a.name, mimetype:a.mimetype }));
    this.state.account_id = data.account_id;
    this.state.reply_to_msg = this.props.msgID;

    if (data.has_attachments && (!data.attachments || !data.attachments.length)) {
      this._lazyLoadAttachments({ account_id: data.account_id, folder: data.folder, uid: data.uid, has_attachments: true });
    }
  }

  async loadDraft() {
    const data = await this.orm.call("mailbox.sync", "load_draft", [this.props.msgID]);

    this.state.subject = data.subject || "";
    this.state.body = data.body_html || "";
    this.state.To = (data.to || []).map((e) => ({ email: e }));
    this.state.Cc = (data.cc || []).map((e) => ({ email: e }));
    this.state.Bcc = (data.bcc || []).map((e) => ({ email: e }));
    this.state.showCc = !!this.state.Cc.length;
    this.state.showBcc = !!this.state.Bcc.length;

    this.state.attachments = (data.attachments || []).map((a) => ({
      id: a.id,
      name: a.name,
      mimetype: a.mimetype,
    }));

    this.state.account_id = data.account_id;
    this.state.draftMessageId = this.props.msgID;

    this.state.request_read_receipt = !!data.request_read_receipt;
    this.state.request_delivery_receipt = !!data.request_delivery_receipt;
    this.state.from_display = data.from_display || "";
  }

  async insertMessageFromChatGPT(content) {
    const wysiwygKey = `${this.componentId}_${this.state.key}`;
    const editor = this.state.wysiwygEditors[wysiwygKey];

    if (content instanceof DocumentFragment) {
      const div = document.createElement("div");
      div.appendChild(content);
      const contentHTML = div.innerHTML;
      if (editor) {
        const currentContent = await editor.getElContent().innerHTML;
        const newContent = currentContent + contentHTML;
        editor.editable.innerHTML = newContent;
      }
    } else {
      console.error("Expected DocumentFragment, but received:", content);
    }
  }

  addEmail(entry, field) {
    if (field === "To" && !this.state.To.includes(entry)) {
      this.state.To.push(entry);
    } else if (field === "Cc" && !this.state.Cc.includes(entry)) {
      this.state.Cc.push(entry);
    } else if (field === "Bcc" && !this.state.Bcc.includes(entry)) {
      this.state.Bcc.push(entry);
    }
  }

  async saveDraft(manual = false) {
    const wysiwygKey = `${this.componentId}_${this.state.key}`;
    const htmlBody = await this.getEditorContent(wysiwygKey);

    const isEmpty =
      !htmlBody?.trim() &&
      !this.state.subject?.trim() &&
      !this.state.To.length &&
      !this.state.Cc.length &&
      !this.state.Bcc.length &&
      !this.state.attachments.length;

    if (isEmpty) {
      return false;
    }

    const attachmentIds = (this.state.attachments || [])
      .filter((a) => a.id)
      .map((a) => a.id);

    const payload = {
      draft_id: this.state.draftMessageId || null,
      account_id: this.state.account_id,
      subject: this.state.subject?.trim() || "",
      body_html: htmlBody || "",
      to: this.state.To.map((e) => e.email),
      cc: this.state.Cc.map((e) => e.email),
      bcc: this.state.Bcc.map((e) => e.email),
      attachment_ids: attachmentIds,
      request_read_receipt: !!this.state.request_read_receipt,
      request_delivery_receipt: !!this.state.request_delivery_receipt,
      from_display: this.state.from_display || "",
      model: this.props.model || null,
      res_id: this.props.resId || null,
    };

    const currentState = JSON.stringify(payload);
    if (!manual && this.lastSavedState === currentState) {
      return false;
    }

    try {
      const draftId = await this.orm.call(
        "mailbox.sync",
        "save_draft",
        [],
        payload
      );
      if (draftId) {
        this.state.draftMessageId = draftId;
      } else {
        return false;
      }

      this.lastSavedState = currentState;
      return true;
    } catch (error) {
      console.error("Failed to save draft:", error);
      if (manual) {
        this.notification.add("Failed to save draft", { type: "danger" });
      }
      return false;
    }
  }

  async saveDraftBeforeUnload(event) {
    const saved = await this.saveDraft();
    if (saved) {
      event.preventDefault();
      event.returnValue = "";
    }
  }

  async sendMail() {
    if (this.state.sending) {
      return;
    }

    const hasRecipients =
      (this.state.To && this.state.To.length) ||
      (this.state.Cc && this.state.Cc.length) ||
      (this.state.Bcc && this.state.Bcc.length);

    if (!hasRecipients) {
      this.notification.add(_t("Please add at least one recipient."), {
        type: "warning",
      });
      return;
    }

    if (!this.state.account_id) {
      this.notification.add(_t("Please choose the sending account."), {
        type: "warning",
      });
      return;
    }

    this.state.sending = true;

    try {
      const wysiwygKey = `${this.componentId}_${this.state.key}`;
      const htmlBody = await this.getEditorContent(wysiwygKey);

      const clean = (arr) =>
        (arr || [])
          .map((e) => (typeof e === "string" ? e : e?.email))
          .filter((v) => !!v)
          .map((v) => v.trim());

      const payload = {
        account_id: this.state.account_id,
        subject: (this.state.subject || "").trim(),
        body_html: htmlBody || "",
        to_emails: clean(this.state.To),
        cc_emails: clean(this.state.Cc),
        bcc_emails: clean(this.state.Bcc),
        attachment_ids: (this.state.attachments || []).map((a) => a.id),
        request_read_receipt: !!this.state.request_read_receipt,
        request_delivery_receipt: !!this.state.request_delivery_receipt,
        from_display: this.state.from_display || "",
        draft_id: this.state.draftMessageId || null,
        model: this.props.model || null,
        res_id: this.props.resId || null,
      };

      await this.saveDraft(true);

      const result = await this.orm.call(
        "mailbox.sync",
        "send_email",
        [],
        payload
      );

      this.state.draftMessageId = null;

      if (this.props.close) {
        this.props.close(result);
      }
    } catch (e) {
      console.error("Failed to send:", e);
      const msg =
        (e && e.data && e.data.message) ||
        e.message ||
        _t("Failed to send email.");
      this.notification.add(msg, { type: "danger" });
    } finally {
      this.state.sending = false;
    }
  }


  startDrag(ev) {
    this.uiState.dragging = true;
    this.uiState.offset = {
      x: ev.clientX - ev.target.closest(".composer-wrapper").offsetLeft,
      y: ev.clientY - ev.target.closest(".composer-wrapper").offsetTop,
    };
    document.addEventListener("mousemove", this.onDrag);
    document.addEventListener("mouseup", this.endDrag);
  }

  onDrag = (ev) => {
    if (!this.uiState.dragging) return;
    this.uiState.position = {
      top: ev.clientY - this.uiState.offset.y,
      left: ev.clientX - this.uiState.offset.x,
    };
  };

  endDrag = () => {
    this.uiState.dragging = false;
    document.removeEventListener("mousemove", this.onDrag);
    document.removeEventListener("mouseup", this.endDrag);
  };

  remove(email, field) {
    const list = this.state[field];
    const index = list.findIndex((e) => e.email === email);
    if (index !== -1) {
      list.splice(index, 1);
    }
  }

  toggleFull() {
    if (this.uiState.isFull) {
      this.uiState.isFull = false;
      if (this.uiState.savedPosition) {
        this.uiState.position = {...this.uiState.savedPosition};
        this.uiState.savedPosition = null;
      }
    } else {
      if (this.uiState.position.top !== null) {
        this.uiState.savedPosition = {...this.uiState.position};
      }
      this.uiState.isFull = true;
      this.uiState.isMinimized = false;
      this.uiState.position = {top: null, left: null};
    }
  }

  toggleMinimize() {
    this.uiState.isMinimized = !this.uiState.isMinimized;
    this.uiState.isFull = false;
  }

  toggleCc() {
    this.state.showCc = !this.state.showCc;
    if (!this.state.showCc) {
      this.state.Cc = [];
    }
  }

  toggleBcc() {
    this.state.showBcc = !this.state.showBcc;
    if (!this.state.showBcc) {
      this.state.Bcc = [];
    }
  }

  getStyle() {
    const base = `z-index: 1050; position: fixed; resize: both; overflow: auto; min-width: 400px; max-height: 92vh; border-radius: 18px;`;
    if (this.uiState.isFull) {
      return `${base} top: 5vh; left: 5vw; width: 90vw; height: 90vh;`;
    }
    if (this.uiState.isMinimized) {
      return `${base} bottom: 0; right: 0; width: 500px; height: auto;`;
    }
    if (this.uiState.position.top !== null) {
      return `${base} top: ${this.uiState.position.top}px; left: ${this.uiState.position.left}px; width: 500px;`;
    }
    return `${base} bottom: 0; right: 0; width: 500px;`;
  }

  onFileUploaded(files) {
    for (const file of files) {
      if (file.error) {
        this.notification.add(file.error, {
          title: _t("Uploading error"),
          type: "danger",
        });
        continue;
      }
      this.state.attachments.push({
        id: file.id,
        name: file.filename,
        mimetype: file.mimetype,
      });
    }
  }

  onFileRemove(id) {
    this.state.attachments = this.state.attachments.filter((a) => a.id !== id);
  }

  getUrl(id) {
    return `/web/content/${id}?download=true`;
  }

  async saveDraftClick() {
    const saved = await this.saveDraft(true);
    if (saved) {
      this.notification.add("Draft saved successfully.", {
        title: "Success",
        type: "success",
      });
    }
  }

  async insertSignature() {
    try {
      const result = await this.orm.searchRead(
        "mailbox.account",
        [["id", "=", this.state.account_id]],
        ["signature"]
      );
      if (!result || !result[0].signature) return;

      const signature = result[0].signature || "";
      const wysiwygKey = `${this.componentId}_${this.state.key}`;
      const editor = this.state.wysiwygEditors[wysiwygKey];
      if (!editor) return;

      const el = await editor.getElContent();
      if (!el) return;

      el.querySelectorAll(".o-maildesk-signature").forEach((node) => {
        if (!node.closest("blockquote")) {
          node.remove();
        }
      });

      const currentContent = el.innerHTML || "";
      let newContent = currentContent;

      if (this.props.reply || this.props.replyAll || this.props.forward) {
        const blockquote = el.querySelector("blockquote");
        if (blockquote) {
          const hasSigInQuote = !!blockquote.querySelector(".o-maildesk-signature");
          if (!hasSigInQuote) {
            newContent = currentContent.replace(
              /(<blockquote[\s\S]*<\/blockquote>)/i,
              `<div class="o-maildesk-signature">${signature}</div><br/>$1`
            );
          }
        } else {
          newContent = currentContent + `<br/><div class="o-maildesk-signature">${signature}</div>`;
        }
      } else {
        newContent = currentContent + `<br/><div class="o-maildesk-signature">${signature}</div>`;
      }

      editor.editable.innerHTML = newContent;
    } catch (err) {
      console.error("Signature insert failed:", err);
    }
  }

  setFromDisplay(account) {
    this.state.from_display = account.sender_name || account.name || "";
  }

  async onAccountChange(ev) {
    const newAccountId = parseInt(ev.target.value);
    if (!newAccountId) return;

    this.state.account_id = newAccountId;
    const acc = this.state.accounts.find(a => a.id === newAccountId);
    if (acc) {
      this.setFromDisplay(acc);
    }
    await this.insertSignature();
  }

  onEditorLoad = (editor) => {
    const wysiwygKey = `${this.componentId}_${this.state.key}`;
    this.state.wysiwygEditors[wysiwygKey] = editor;

    setTimeout(async () => {
      await this.insertSignature();
    }, 200);
  };

  getEditorContent(wysiwygKey) {
      const editor = this.state.wysiwygEditors[wysiwygKey];
      try {
          if (editor && typeof editor.getElContent === "function") {
              const el = editor.getElContent();
              return HtmlMailField.getInlinedEditorContent(new WeakMap(), editor, el)
                  .then(() => el.outerHTML)
                  .catch((err) => {
                      console.error("Inlining failed:", err);
                      return el.outerHTML;
                  });
          }
      } catch (e) {
          console.error("getEditorContent failed:", e);
      }
      return "";
  }

  getWysiwygConfig() {
    return {
      content: markup(this.state.body),
      dropImageAsAttachment: true,
      classList: ["o_wysiwyg_content"],
      direction: localization.direction || "ltr",
      dynamicPlaceholder: true,
      disableFloatingToolbar: false,
    };
  }

  close() {
    this.props.close();
  }
}

ComposeMail.template = "maildesk.ComposeMail";
