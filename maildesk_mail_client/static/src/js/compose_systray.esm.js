// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component} from "@odoo/owl";
import {ComposeMail} from "./compose_mail.esm.js";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import { user } from "@web/core/user";

class ComposeSystray extends Component {
  static template = "maildesk_mail_client.ComposeSystray";
  static props = {};

  setup() {
    this.orm = useService("orm");
    this.dialog = useService("dialog");
  }

  async onClick() {
    this.dialog.add(ComposeMail, {
      to: [],
      cc: [],
      bcc: [],
    });
  }
}

user.hasGroup("maildesk_mail_client.group_mailbox_user").then((hasGroup) => {
    if (hasGroup) {
        registry.category("systray").add(
            "maildesk_mail_client.ComposeSystray",
            {
                Component: ComposeSystray,
            },
            { sequence: 99 }
        );
    }
}).catch(() => {
});