import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { onWillStart } from '@odoo/owl';
import { SearchBar } from '@web/search/search_bar/search_bar';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';


patch(SearchBar.prototype, {
    setup() {
        super.setup();

        this.uo = useUdooStore();
        this.ue = useUdooLocalStore();

        onWillStart(async () => {
        });
    },

    toggleFilterBar() {
        const { actionId, viewType } = this.env.config;
        if (viewType != 'list') return;

        if (actionId) {
            this.uo.useFilterBarPop = false; // Reset

            this.ue.actionAdvs[actionId] = !this.ue.actionAdvs[actionId];
            if (this.ue.actionAdvs[actionId]) {
                this.env.bus.trigger('CTL:USEFBR');
            } else {
                this.uo.useFilterBar = false;
            }
        } else {
            this.uo.useFilterBarPop = !this.uo.useFilterBarPop;
        }
    },
});
