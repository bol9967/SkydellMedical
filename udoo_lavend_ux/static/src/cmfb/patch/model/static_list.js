/* @odoo-module */

import { patch } from '@web/core/utils/patch';
import { StaticList } from '@web/model/relational_model/static_list';


patch(StaticList.prototype, {
    uSortBy(fieldName, ascending) {
        return this.model.mutex.exec(() => {
            let orderBy = [...this.orderBy];
            if (orderBy.length && orderBy[0].name === fieldName) {
                orderBy[0] = { name: orderBy[0].name, asc: ascending };
            } else {
                orderBy = orderBy.filter((o) => o.name !== fieldName);
                orderBy.unshift({
                    name: fieldName,
                    asc: ascending,
                });
            }
            return this._sort(this._currentIds, orderBy);
        });
    },

    uSortReset(fieldName) {
        return this.model.mutex.exec(() => {
            let orderBy = this.orderBy.filter((o) => o.name !== fieldName);
            return this._sort(this._currentIds, orderBy);
        });
    }
});
