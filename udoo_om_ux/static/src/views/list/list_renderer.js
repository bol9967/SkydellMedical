import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useState } from '@odoo/owl';
import { ListRenderer } from '@web/views/list/list_renderer';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';


patch(ListRenderer.prototype, {

    setup() {
        super.setup();
        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();
        this.uState = useState({});
    },

    getSortableIconClass(column) {
        const { orderBy } = this.props.list;
        const classNames = this.isSortable(column) ? ['text-dodger end-0 pe-1'] : ['d-none'];
        if (orderBy.length && orderBy[0].name === column.name) {
            classNames.push(orderBy[0].asc ? 'ri-arrow-down-long-fill' : 'ri-arrow-up-long-fill');
        } else {
            classNames.push('ri-arrow-up-down-fill', 'opacity-0', 'opacity-100-hover');
        }

        return classNames.join(' ');
    },
});