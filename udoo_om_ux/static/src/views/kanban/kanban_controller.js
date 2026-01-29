import { patch } from '@web/core/utils/patch';
import { router } from '@web/core/browser/router';
import { useService } from '@web/core/utils/hooks';
import { onWillStart, onWillUnmount } from '@odoo/owl';
import { KanbanController } from '@web/views/kanban/kanban_controller';
import { FormViewDialog } from '@web/views/view_dialogs/form_view_dialog';

import { encodeRecordUrl } from '../../webclient/action_utils';


patch(KanbanController.prototype, {
    setup() {
        super.setup();

        this.ui = useService('ui');

        onWillStart(async () => {
            const { ui, props } = this;
            if (props.context.ux_props?.dropin_kanban) {
                ui.dropinUid = `${props.resModel}`;
                ui.dropinMode = props.context.ux_props.dropin_kanban;
            }
        });

        onWillUnmount(() => {
            if (this.ui.dropinMode) {
                delete this.ui.dropinMode;
                delete this.ui.dropinUid;
            }
        });
    },

    async openRecord(record, mode) {
        const { actionService, env, ui } = this;
        if (env.isSmall || env.inDialog || (!ui.dropinMode && !ui.ctrlKey && !ui.shiftKey)) {
            await this.open2stRecord(record, mode); return;
        }
        const controller = actionService.currentController;
        const hasFormView = controller.views?.some((view) => view.type === 'form');

        if (!hasFormView) {
            await super.openRecord(record, mode); return;
        }
        if (ui.ctrlKey) {
            const act = encodeRecordUrl(record, controller.action);
            await actionService.doAction(act);
            return;
        } else if (ui.shiftKey) {
            ui.dropinMode = ui.dropinMode ? false : true;
        }
        if (ui.dropinMode) {
            record.model.dialog.add(FormViewDialog, this.composeDropinProps(record));
        } else {
            this.open2stRecord(record, mode);
        }
    },

    composeDropinProps(record) {
        const sheetName = record._textValues.display_name || record._textValues.name;
        return {
            title: sheetName || router.current.actionStack[router.current.actionStack.length - 1].displayName,
            resModel: record.resModel,
            resId: record.resId,
            context: {},
            onRecordSaved: async () => {
                await this.model.load();
            },
        }
    },

    async open2stRecord(record, mode) {
        super.openRecord(record, mode);
    }
});