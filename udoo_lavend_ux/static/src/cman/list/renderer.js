import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { isMobileOS } from '@web/core/browser/feature_detection';
import { user } from '@web/core/user';
import { Component, onWillStart, onWillDestroy, useState, xml } from '@odoo/owl';

import { LazyComponent } from '@web/core/assets';
import { ListRenderer } from '@web/views/list/list_renderer';


export const olvListRenderer = () => ({
    setup() {
        super.setup(...arguments);

        this.actionService = useService('action');
        const list = this.props.list;

        const { actionId, actionType } = this.env.config || {};

        const isPotentiallyEditable =
            !isMobileOS() &&
            !this.env.inDialog &&
            list === list.model.root &&
            actionId &&
            actionType === 'ir.actions.act_window';

        this.udooEditable = useState({
            value: isPotentiallyEditable,
        });

        if (isPotentiallyEditable) {
            const OmuxEditable = (action) => {
                if (!action.xml_id) {
                    return false;
                }
                return Boolean(action.res_model);
            };
            const onUiUpdated = () => {
                const action = this.actionService.currentController.action;
                if (action.id === actionId) {
                    this.udooEditable.value = OmuxEditable(action);
                }
                stopListening();
            };
            const stopListening = () => this.env.bus.removeEventListener('ACTION_MANAGER:UI-UPDATED', onUiUpdated);
            this.env.bus.addEventListener('ACTION_MANAGER:UI-UPDATED', onUiUpdated);

            onWillStart(async () => {
                this.hasGroupLvm = await user.hasGroup('udoo_lavend_ux.group_lvm');
            });

            onWillDestroy(stopListening);
        }
    },

    isUdooEditable() {
        return this.udooEditable.value && this.hasGroupLvm;
    },

    get displayOptionalFields() {
        return this.isUdooEditable() || super.displayOptionalFields;
    },

    openColumnManager() {
        const { archInfo, list } = this.props;
        const state = this.actionService.currentController.getLocalState();

        this.env.services.dialog.add(ColumnManagerPanel, {
            viewId: this.env.config.viewId,
            resModel: list.resModel,
            fields: state.modelState.config.fields,
            fieldNodes: archInfo.fieldNodes,
        });
    },

    /**
     * @override
     */
    isSortable(column) {
        const { options } = column;
        return super.isSortable(column) && options?.unsortable != true;
    },
});

export const unpatchListRenderer = patch(ListRenderer.prototype, olvListRenderer());

export class ColumnManagerPanel extends Component {
    static template = xml`<LazyComponent bundle="'omux_list_controler.mod'" Component="'ColumnManager'" props="props"/>`;
    static components = { LazyComponent };
    static props = { '*': true };
}