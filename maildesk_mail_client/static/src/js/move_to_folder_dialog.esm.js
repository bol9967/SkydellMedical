// # Copyright (C) 2025 Metzler IT GmbH
// # License Odoo Proprietary License v1.0 (OPL-1)
// # You may use this file only in accordance with the license terms.
// # For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license
//

/** @odoo-module **/

import {Component} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";

export class MoveToFolderDialog extends Component {
  static components = {Dialog};
  static template = "maildesk_mail_client.MoveToFolderDialog";
  static props = {
    accounts: {type: Array, optional: true},
    folders: {type: Array, optional: true},
    onSelect: Function,
    close: Function,
  };

  renderFolderTree(folder, level = 0) {
    return {
      folder,
      level,
      children: folder.children.map((child) => this.renderFolderTree(child, level + 1)),
    };
  }

  get foldersWithLevel() {
    return this.props.folders.map((f) => this.renderFolderTree(f));
  }
}
