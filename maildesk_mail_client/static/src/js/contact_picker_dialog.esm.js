// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component, onWillStart, useState} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";
import {useDebounced} from "@web/core/utils/timing";
import {useService} from "@web/core/utils/hooks";

export class ContactPickerDialog extends Component {
  static template = "maildesk_mail_client.ContactPickerDialog";
  static components = {Dialog};
  static props = {onSelect: Function, close: Function};

  setup() {
    this.orm = useService("orm");

    this.state = useState({
      search: "",
      page: 0,
      pageSize: 15,
      total: 0,
      results: [],
      tagMap: {},
      get start() {
        return this.page * this.pageSize;
      },
      get end() {
        return Math.min(this.start + this.results.length, this.total);
      },
    });

    onWillStart(() => this.reload());
    this.reloadDebounced = useDebounced(this.reload.bind(this), 300);
  }

  clearFilter() {
    this.props.onSelect(null);
    this.props.close();
  }

  onSearchInput(ev) {
    this.state.search = ev.target.value;
    this.state.page = 0;
    this.reloadDebounced();
  }

  select(partnerId) {
    this.props.onSelect(partnerId);
    this.props.close();
  }

  async nextPage() {
    if (this.state.end < this.state.total) {
      this.state.page++;
      await this.reload();
    }
  }

  async prevPage() {
    if (this.state.page) {
      this.state.page--;
      await this.reload();
    }
  }

  async reload() {
    const domain = [["email", "!=", false]];
    if (this.state.search.trim()) {
      domain.push(
        "|",
        ["name", "ilike", this.state.search],
        ["email", "ilike", this.state.search]
      );
    }

    this.state.total = await this.orm.call(
      "res.partner",
      "count_partners_with_email_activity",
      [domain]
    );

    const partners = await this.orm.call(
      "res.partner",
      "get_partners_with_email_activity",
      [domain],
      {offset: this.state.start, limit: this.state.pageSize}
    );

    const tagIds = new Set(partners.flatMap((p) => p.category_id));
    if (tagIds.size) {
      const tags = await this.orm.read(
        "res.partner.category",
        [...tagIds],
        ["id", "name"]
      );
      tags.forEach((t) => {
        this.state.tagMap[t.id] = t.name;
      });
    }

    this.state.results = partners;
  }
}
