// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license

/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

class MaildeskNotification {
    constructor(env, services) {
        this.bus = services.bus_service;
        this.multiTab = services.multi_tab;

        this.sound = new Audio("/mail/static/src/audio/ting.mp3");
        this.lang = user.lang || document.documentElement.getAttribute("lang");
        this.isMainTab = false;

        this._cb = (payload) => this.onMaildesk(payload);
    }

    async setup() {
        this.isMainTab = await this.multiTab.isOnMainTab();

        this.bus.subscribe("maildesk", this._cb);

        browser.setInterval(async () => {
            this.isMainTab = await this.multiTab.isOnMainTab();
        }, 1500);

        if (browser.Notification?.permission === "default") {
            browser.Notification.requestPermission();
        }
    }

    show(title, body) {
        if (!browser.Notification) return;
        if (browser.Notification.permission !== "granted") return;

        const n = new Notification(title, {
            body,
            icon: "/maildesk_mail_client/static/description/icon.png",
            badge: "/maildesk_mail_client/static/description/icon.png",
            lang: this.lang,
            timestamp: Date.now(),
        });

        n.onclick = () => {
            window.focus();
            window.open("/maildesk", "_blank");
            n.close();
        };
    }

    async playSound() {
        try { await this.sound.play(); } catch {}
    }

    async notifyMail(meta) {
        const subject = (meta.subject || meta.email_subject || meta.name || "").trim();
        if (!subject) return;

        const preview =
            (meta.preview ||
             meta.snippet ||
             meta.body_preview ||
             meta.body_plain ||
             _t("You have a new email. Click to read.")).trim();

        if (!preview) return;

        const title = `📬 ${subject}`;
        const body = `💬 ${preview.replace(/\s+/g, " ")}`;

        this.show(title, body);
        await this.playSound();
    }

    async onMaildesk(payload) {
        if (!this.isMainTab) return;
        if (!payload || payload.type !== "added") return;

        if (payload.server_kind === "outlook") return;

        const items = Array.isArray(payload.meta) ? payload.meta : [];
        if (!items.length) return;

        for (const meta of items) {
            await this.notifyMail(meta);
        }
    }

    destroy() {
        try { this.bus.unsubscribe("maildesk", this._cb); } catch {}
    }
}

export const maildeskNotificationService = {
    dependencies: ["bus_service", "multi_tab"],
    start(env, services) {
        const s = new MaildeskNotification(env, services);
        s.setup();
        return s;
    },
};

registry.category("services").add("maildesk_notification", maildeskNotificationService);
