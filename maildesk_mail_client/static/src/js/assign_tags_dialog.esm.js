// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component, useState} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {Dialog} from "@web/core/dialog/dialog";
import {useService} from "@web/core/utils/hooks";

export class AssignTagsDialog extends Component {
  static template = "maildesk_mail_client.AssignTagsDialog";
  static components = {Dialog};

  static props = {
    tags: Array,
    selectedTagIds: {type: Set, optional: true},
    onSelect: Function,
    close: Function,
    title: {type: String, optional: true},
  };

  static defaultProps = {
    selectedTagIds: new Set(),
    title: _t("Assign Tags"),
  };

  setup() {
    this.orm = useService("orm");

    this.state = useState({
      selectedTagIds: new Set(this.props.selectedTagIds || []),
      isSaving: false,
      newTagName: "",
      newTagColor: "#6CC1ED",
    });

    const selected = new Set(this.props.selectedTagIds || []);
    const sortedTags = [...this.props.tags].sort((a, b) => {
      const aSel = selected.has(a.id);
      const bSel = selected.has(b.id);
      if (aSel && !bSel) return -1;
      if (!aSel && bSel) return 1;
      return a.name.localeCompare(b.name);
    });

    this.localTags = useState(sortedTags);
  }

  toggleTag(tagId) {
    const set = this.state.selectedTagIds;
    if (set.has(tagId)) {
      set.delete(tagId);
    } else {
      set.add(tagId);
    }
  }

  isTagSelected(tag) {
    return this.state.selectedTagIds.has(tag.id);
  }

  getTagColor(tag) {
    return this.isTagSelected(tag) ? tag.color || "#6c757d" : "#d3d3d3";
  }

  async createNewTag() {
    const name = this.state.newTagName.trim();
    const color = this.state.newTagColor;

    if (!name || !color) return;

    const nameLower = name.toLowerCase();
    const exists = this.localTags.some((tag) => tag.name.toLowerCase() === nameLower);
    if (exists) {
      alert(_t("Tag with this name already exists."));
      return;
    }

    try {
      const tagId = await this.orm.call("mail.message.tag", "create", [{name, color}]);
      const [tag] = await this.orm.read(
        "mail.message.tag",
        [tagId],
        ["id", "name", "color"]
      );
      this.localTags = [...this.localTags, tag];
      this.state.selectedTagIds.add(tag.id);
      this.state.newTagName = "";
    } catch (e) {
      console.error("Failed to create tag:", e);
    }
  }

  async confirmSelection() {
    if (this.state.isSaving) return;
    this.state.isSaving = true;
    await this.props.onSelect([...this.state.selectedTagIds], {
      close: this.props.close,
    });
    this.state.isSaving = false;
  }
}
