import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';
import { ListRenderer } from '@web/views/list/list_renderer';

import { useOmuxColumnWidths } from './column_width_hook';


patch(ListRenderer.prototype, {
    setup() {
        ListRenderer.useMagicColumnWidths = 0;

        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();

        super.setup();
        if (ListRenderer.useMagicColumnWidths === false) {
            return;
        }
        ListRenderer.useOmuxColumnWidths = true;
        this.columnWidths = useOmuxColumnWidths(this.tableRef, () => ({
            columns: this.columns,
            isEmpty: !this.props.list.records.length || this.props.list.model.useSampleModel,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            hasActionsColumn: this.hasActionsColumn,
        }));
    }
});
