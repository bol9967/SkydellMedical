// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component, onWillStart} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";

export class PartnerCardPopover extends Component {
  static template = "maildesk_mail_client.PartnerCardPopover";

  static props = {
    id: {type: Number, required: true},
    close: {type: Function, required: true},
  };

  setup() {
    this.orm = useService("orm");
    this.actionService = useService("action");
    onWillStart(async () => {
      [this.partner] = await this.orm.read(
        "res.partner",
        [this.props.id],
        ["name", "email", "phone", "function", "company_name"]
      );
    });
  }

  async onClickViewProfile() {
    const action = {
      type: "ir.actions.act_window",
      res_model: "res.partner",
      res_id: this.partner.id,
      views: [[false, "form"]],
      view_mode: "form",
    };
    this.actionService.doAction(action);
    this.props.close();
  }
}
