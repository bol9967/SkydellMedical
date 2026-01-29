import { patch } from '@web/core/utils/patch';
import { makeContext } from '@web/core/context';
import { evaluateExpr } from '@web/core/py_js/py';
import { domainFromTree, treeFromDomain } from '@web/core/tree_editor/condition_tree';
import { DEFAULT_INTERVAL } from '@web/search/utils/dates';
import { SearchModel } from '@web/search/search_model';


patch(SearchModel.prototype, {
    /**
     * Activate or deactivate the simple filter with given filterId, i.e.
     * add or remove a corresponding query element.
     */
    uToggleSearchItem(searchItemId, revert = false) {
        const searchItem = this.searchItems[searchItemId];

        switch (searchItem.type) {
            case 'dateFilter':
            case 'field_property':
            case 'field': {
                return;
            }
        }

        const index = this.query.findIndex((queryElem) => queryElem.searchItemId == searchItemId);
        if (index >= 0) {
            this.query.splice(index, 1);
        } else if (!revert) {
            if (searchItem.type === 'favorite') {
                this.query = [];
            } else if (searchItem.type === 'comparison') {
                // make sure only one comparison can be active
                this.query = this.query.filter((queryElem) => {
                    const { type } = this.searchItems[queryElem.searchItemId];
                    return type !== 'comparison';
                });
            }
            this.query.push({ searchItemId });
        }
        this._notify();
    },

    /**
     * Create a new filter of type 'groupBy' or 'dateGroupBy' and activate it.
     * It is added to the unique group of groupbys.
     * @param {string} fieldName
     * @param {Object} [param]
     * @param {string} [param.interval=DEFAULT_INTERVAL]
     * @param {boolean} [param.invisible=false]
     */
    uCreateNewGroupBy(fieldName, { label, interval, invisible } = {}) {
        const field = this.searchViewFields[fieldName];
        const { string, type: fieldType } = field;
        const firstGroupBy = Object.values(this.searchItems).find((f) => f.type === 'groupBy');
        const preSearchItem = {
            description: label || string || fieldName,
            fieldName,
            fieldType,
            groupId: firstGroupBy ? firstGroupBy.groupId : this.nextGroupId++,
            groupNumber: this.nextGroupNumber,
            id: this.nextId,
            custom: true,
        };
        if (invisible) {
            preSearchItem.invisible = 'True';
        }
        if (['date', 'datetime'].includes(fieldType)) {
            this.searchItems[this.nextId] = Object.assign(
                { type: 'dateGroupBy', defaultIntervalId: interval || DEFAULT_INTERVAL },
                preSearchItem
            );
            this.toggleDateGroupBy(this.nextId);
        } else {
            this.searchItems[this.nextId] = Object.assign({ type: 'groupBy' }, preSearchItem);
            this.toggleSearchItem(this.nextId);
        }
        this.nextGroupNumber++; // FIXME: with this, all subsequent added groups are in different groups (visually)
        this.nextId++;
        this._notify();
    },

    /**
     * Return an array containing enriched copies of all searchElements or of those
     * satifying the given predicate if any
     * @param {Function} [predicate]
     * @returns {Object[]}
     */
    uGetSearchItems(predicate) {
        const searchItems = [];
        Object.values(this.searchItems).forEach((searchItem) => {
            const isInvisible =
                'invisible' in searchItem && evaluateExpr(searchItem.invisible, this.globalContext);
            if (isInvisible || (!predicate || predicate(searchItem))) {
                const enrichedSearchitem = this._enrichItem(searchItem);
                if (enrichedSearchitem) {
                    searchItems.push(enrichedSearchitem);
                }
            }
        });
        if (searchItems.some((f) => f.type === 'favorite')) {
            searchItems.sort((f1, f2) => f1.groupNumber - f2.groupNumber);
        }
        return searchItems;
    },

    uFilterReset(filterItems) {
        this.query = this.query.filter((queryElem) => {
            for (let index = 0; index < filterItems.length; index++) {
                const element = filterItems[index];
                if (element.isActive && element.id == queryElem.searchItemId) {
                    return false;
                }
            }
            return true;
        });
        this._notify();
    },

    async uSplitAndAddDomain(domain, groupId, callback) {
        const group = groupId ? this._getGroups().find((g) => g.id === groupId) : null;
        let context;
        if (group) {
            const contexts = [];
            for (const activeItem of group.activeItems) {
                const context = this._getSearchItemContext(activeItem);
                if (context) {
                    contexts.push(context);
                }
            }
            context = makeContext(contexts);
        }

        const tree = treeFromDomain(domain, { distributeNot: !this.isDebugMode });
        const trees = !tree.negate && tree.value === '&' ? tree.children : [tree];
        const promises = trees.map(async (tree) => {
            const description = await this.getDomainTreeDescription(this.resModel, tree);
            const preFilter = {
                description,
                domain: domainFromTree(tree),
                invisible: 'True',
                type: 'filter',
            };
            if (context) {
                preFilter.context = context;
            }
            return preFilter;
        });

        const preFilters = await Promise.all(promises);

        this.blockNotification = true;

        if (group) {
            const firstActiveItem = group.activeItems[0];
            const firstSearchItem = this.searchItems[firstActiveItem.searchItemId];
            const { type } = firstSearchItem;
            if (type === 'favorite') {
                const activeItemGroupBys = this._getSearchItemGroupBys(firstActiveItem);
                for (const activeItemGroupBy of activeItemGroupBys) {
                    const [fieldName, interval] = activeItemGroupBy.split(':');
                    this.createNewGroupBy(fieldName, { interval, invisible: true });
                }
                const index = this.query.length - activeItemGroupBys.length;
                this.query = [...this.query.slice(index), ...this.query.slice(0, index)];
            }
            this.deactivateGroup(groupId);
        }

        for (const preFilter of preFilters) {
            callback(this.nextGroupId);
            this.createNewFilters([preFilter]);
        }

        this.blockNotification = false;

        this._notify();
    }
});