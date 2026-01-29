// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component, useState} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";

export class EmailInputField extends Component {
  static template = "maildesk.EmailInputField";
  static props = {
    field: String,
    state: Object,
    addEmail: Function,
    remove: Function,
    toggleCc: Function,
    toggleBcc: Function,
  };

  setup() {
    this.orm = useService("orm");
    this.state = useState({
      inputValue: "",
      suggestions: [],
      showSuggestions: false,
    });
  }

  async onInput(ev) {
    this.state.inputValue = ev.target.value;
    if (this.state.inputValue.length > 1) {
      const result = await this.orm.searchRead(
        "res.partner",
        [
          ["email", "!=", false],
          "|",
          ["name", "ilike", this.state.inputValue],
          ["email", "ilike", this.state.inputValue],
        ],
        ["id", "name", "email"]
      );

      const allSelected = [
        ...this.props.state.To,
        ...this.props.state.Cc,
        ...this.props.state.Bcc,
      ].map((e) => e.email);

      this.state.suggestions = result.filter((r) => !allSelected.includes(r.email));
      this.state.showSuggestions = this.state.suggestions.length > 0;
    } else {
      this.state.showSuggestions = false;
    }
  }

  onBlur(ev) {
    setTimeout(() => {
      const val = this.state.inputValue.trim();
      if (val && val.includes("@")) {
        this.props.addEmail({email: val}, this.props.field);
      }
      this.state.inputValue = "";
      this.state.suggestions = [];
      this.state.showSuggestions = false;
    }, 200);
  }

  onKeydown(ev) {
    if (ev.key === "Enter" || ev.key === "Tab") {
      const val = this.state.inputValue.trim();
      if (val && val.includes("@")) {
        this.props.addEmail({email: val}, this.props.field);
        this.state.inputValue = "";
        this.state.suggestions = [];
        this.state.showSuggestions = false;
      }
    }
  }

  addEmailHandler = (ev, entry) => {
    ev.preventDefault();
    if (entry.email) {
      this.props.addEmail(entry, this.props.field);
      this.state.inputValue = "";
      this.state.suggestions = [];
      this.state.showSuggestions = false;
    }
  };
}
