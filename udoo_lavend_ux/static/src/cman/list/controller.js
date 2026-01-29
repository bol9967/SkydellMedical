import { patch } from '@web/core/utils/patch';
import { registry } from '@web/core/registry';
import { Component, useState, xml } from '@odoo/owl';
import { LazyComponent } from '@web/core/assets';
import { ListController } from '@web/views/list/list_controller';

export class ModuleConfigLoader extends Component {
    static template = xml`<LazyComponent bundle="'omux_list_explorer.conf'" Component="'ListExplorerConfig'"/>`;
    static components = { LazyComponent };
    static props = { '*': true };
}

registry.category('actions').add('omux_list_explorer_config', ModuleConfigLoader);

patch(ListController.prototype, {
    setup() {
        super.setup();

        this.lvState = useState({
            isInlineEdit: this.editable,
            forceInlineEdit: false,
            skipInlineEdit: this.props.className?.includes('thoem') || !this.activeActions.edit,
        })
    },

    forceInlineEdit() {
        if (this.bkEditable === undefined) {
            this.bkEditable = this.editable;
        }

        // Toggling
        this.lvState.forceInlineEdit = !this.lvState.forceInlineEdit;
        if (this.lvState.forceInlineEdit) {
            this.editable = 'top';
        } else {
            this.editable = this.bkEditable;
            delete this.bkEditable;
        }

        this.render();
    }
});