/* @odoo-module */

import { patch } from '@web/core/utils/patch';
import { DynamicList } from '@web/model/relational_model/dynamic_list';


patch(DynamicList.prototype, {
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
            return this._load(this.offset, this.limit, orderBy, this.domain);
        });
    },

    uSortReset(fieldName) {
        return this.model.mutex.exec(() => {
            let orderBy = this.orderBy.filter((o) => o.name !== fieldName);
            return this._load(this.offset, this.limit, orderBy, this.domain);
        });
    },
});
