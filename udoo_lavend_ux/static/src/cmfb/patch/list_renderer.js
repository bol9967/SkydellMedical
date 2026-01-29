import { _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { rpc } from '@web/core/network/rpc';
import { patch } from '@web/core/utils/patch';
import { useBus, useService } from '@web/core/utils/hooks';
import { localization } from '@web/core/l10n/localization';
import { usePopover } from '@web/core/popover/popover_hook';
import { condition, domainFromTree, treeFromDomain } from '@web/core/tree_editor/condition_tree';
import { getValueEditorInfo, getDefaultValue } from '@web/core/tree_editor/tree_editor_value_editors';
import { useLoadFieldInfo } from '@web/core/model_field_selector/utils';

import { Domain } from '@web/core/domain';
import { ListRenderer } from '@web/views/list/list_renderer';
import { Dropdown } from '@web/core/dropdown/dropdown';
import { DropdownItem } from '@web/core/dropdown/dropdown_item';
import { DomainSelectorDialog } from '@web/core/domain_selector_dialog/domain_selector_dialog';
import { Component, onWillStart, useState, toRaw } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

import { FieldFilterPopup } from '../editor/data_filter';
import { getDomainDisplayedOperators } from '../editor/domain_selector_operator_editor';


export class QuickColumnFilterPopOver extends Component {
    static components = { DropdownItem }
    static template = 'wub.QuickColumnFilterPopOver';
    static props = { '*': true };
}


ListRenderer.components = { ...ListRenderer.components, Uropdown: Dropdown }

patch(ListRenderer.prototype, {
    setup() {
        super.setup();

        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();
        this.uState = useState({});

        this.ui = useService('ui');
        this.orm = useService('orm');
        this.notification = useService('notification');

        const fieldService = useService('field');
        this.loadFieldInfo = useLoadFieldInfo(fieldService);

        const direction = localization.direction === 'rtl' ? 'bottom' : 'right';
        this.fbpop = usePopover(QuickColumnFilterPopOver, {
            position: direction,
            closeOnClickAway: true,
            fixedPosition: true,
            popoverClass: 'fs-6',
            animation: false,
        });
        this.ffpop = usePopover(FieldFilterPopup, {
            arrow: true,
            position: 'bottom',
            popoverClass: 'fs-6',
            onClose: () => this.onFiltoverClose?.(),
        });

        useBus(this.env.bus, 'CTL:USEFBR', async () => {
            this.uo.useFilterBar = true;
            if (!this.uLoadingFieldDefs && this.columns.length) {
                this.uState.fieldDefsLocked = false;
            }
        });

        useBus(this.env.bus, 'LSF:RESET', () => {
            if (this.isX2Many) {
                this._clearX2ManyFilter();
                this.uo.filterValues = { '_FK_': this.uftKey };
            }
        });

        onWillStart(async () => {
            const {
                fb_class = '',
                fb_portal = '',
                fb_btn_class = 'ms-auto'
            } = this.props.list.context || {};

            const CLASSES = {
                filter: 'u_filter_panel',
                button: 'btn btn-secondary px-2',
                layout: 'd-flex flex-wrap column-gap-1 row-gap-2 align-items-center'
            };

            const padding = this.isX2Many ? (fb_class ? '' : 'pb-4') : 'p-3';

            this.x2mFilterPortalPath = fb_portal;
            this.x2mFilterClass = `${CLASSES.filter} ${padding} ${fb_class || CLASSES.layout}`.trim();
            this.x2mFilterClearClass = `${CLASSES.button} ${fb_btn_class}`.trim();

            // Filter domain initial
            if (!this.uo.filterValues) {
                this.uo.filterValues = { '_FK_': this.uftKey };
            } else if (this.uo.filterValues['_FK_'] !== this.uftKey) {
                this.uo.filterValues = { '_FK_': this.uftKey };
            } else if (this.isX2Many && this.uo.filterValues['_FK_'] === this.uftKey) {
                await this._execX2ManyFilter();
            }
        });
    },

    get uftKey() {
        return this.props.list.config.resModel + '_' + this.env.config.viewId;
    },

    async loadColumnFieldDefs(columns, list) {
        const { resModel } = list.config;
        const paths = columns.map(column => column.name);

        const promises = [];
        const fieldDefs = {};
        for (const path of paths) {
            if (typeof path === 'string') {
                promises.push(
                    this.loadFieldInfo(resModel, path).then(({ fieldDef }) => {
                        fieldDefs[path] = fieldDef;
                    })
                );
            }
        }
        await Promise.all(promises);

        this.uFieldDefs = fieldDefs;
        this.uState.fieldDefsLocked = true;
    },

    getColumnEditorInfo(column) {
        const fieldDef = this.uFieldDefs[column.name];
        const operator = getDomainDisplayedOperators(fieldDef)[0];
        const inf = getValueEditorInfo(fieldDef, operator, { addBlankOption: true });

        inf.mutGetter = () => {
            if (inf.component.name == 'DateTimeInput') {
                return false;
            } else if (inf.defaultValue() == 1) {
                return '';
            } else {
                if (this.isX2Many && inf.component.name == 'DomainSelectorAutocomplete') {
                    const domain = this.uo.filterValues[column.name];
                    if (domain) {
                        const tree = treeFromDomain(domain);
                        if (tree.value.length)
                            return tree.value;
                        else {
                            this._clearColumnFilter(column.name);
                            return;
                        }
                    }
                }
                return inf.defaultValue();
            }
        }

        inf.valueSetter = async (value) => {
            const domain = await this._validateFilterDomain(column.name, operator, value);
            const isEmpty = Array.isArray(value) && value.length === 0;

            if (isEmpty && this.isX2Many) {
                this._clearX2ManyFilter(column.name);
            } else if (domain) {
                this._applyColumnFilter(column.name, domain);
            }
        }

        return inf;
    },

    uIsStorable(column) {
        const fnfo = this.fields[column.name];
        if (!fnfo) {
            return false;
        }
        return fnfo.store || fnfo.relatedPropertyField || (fnfo.related && fnfo.sortable);
    },

    uQuickFilterPop(column) {
        const targetEl = document.querySelector(`.elvf_${this._normCls(column.name)}`);
        this.fbpop.open(targetEl, {
            widget: this,
            items: this.uSearchFilter(column),
            itemClass: 'py-1 ps-4 pe-3',
            emptyMsg: _t('No column filters found.'),
            popAction: (item) => this.uQuisToggleSearchItem(item),
        });
    },

    uQuisToggleSearchItem(searchItem) {
        this.closeCurrentPop('d-ufover');
        this.env.searchModel.toggleSearchItem(searchItem.id);
    },

    uSortAscending(column) {
        this.props.list.uSortBy(column.name, true);
    },

    uSortDescending(column) {
        this.props.list.uSortBy(column.name, false);
    },

    uResetSort(column) {
        this.props.list.uSortReset(column.name);
    },

    uToggleGroupPop(column) {
        const targetEl = document.querySelector(`.elvg_${this._normCls(column.name)}`);
        this.fbpop.open(targetEl, {
            widget: this,
            items: [
                { description: _t('Year'), id: 'year' },
                { description: _t('Quarter'), id: 'quarter' },
                { description: _t('Month'), id: 'month' },
                { description: _t('Week'), id: 'week' },
                { description: _t('Day'), id: 'day' },
            ],
            itemClass: 'py-1 ps-4 pe-3',
            popAction: (item) => {
                this.closeCurrentPop('d-ufover');
                this.uToggleGroup(column, false, item.id);
            },
        });
    },

    uToggleGroup(column, revert = false, interval = 'day') {
        function groupMacher(item) {
            return item.fieldName == column.name && ['groupBy', 'dateGroupBy'].includes(item.type);
        }

        let searchItem = this.env.searchModel.getSearchItems(
            (searchItem) => groupMacher(searchItem)
        );

        if (revert) {
            if (searchItem.length) {
                this.env.searchModel.uToggleSearchItem(searchItem[0].id, true);
            }
            return;
        }

        if (!searchItem.length) {
            let config = { interval, label: column.label };
            this.env.searchModel.uCreateNewGroupBy(column.name, config);
            return;
        } else {
            let { options, id: itemId } = searchItem[0];
            if (options) {
                // TODO: Support multi interval on toggle menu
                this.env.searchModel.toggleDateGroupBy(itemId, interval);
            } else {
                this.env.searchModel.toggleSearchItem(itemId);
            }
        }
    },

    uSearchFilter(column) {
        function filterMacher(item) {
            return item.type == 'filter' && item.domain.includes(column.name);
        }
        return this.env.searchModel.getSearchItems(
            (searchItem) => filterMacher(searchItem)
        );
    },

    uResetFilter(column) {
        function filterMacher(item) {
            return item.type == 'filter' && item.domain.includes(column.name);
        }
        const filterItems = this.env.searchModel.uGetSearchItems(
            (searchItem) => filterMacher(searchItem)
        );
        this.env.searchModel.uFilterReset(filterItems);
    },

    uAddCustomFilter(column) {
        const { domainEvalContext: context, resModel } = this.props.list.config;

        const supportedTypes = column.field.supportedTypes;
        let ope = 'in', opv = '[]';
        if (supportedTypes?.length) {
            if (supportedTypes.includes('char') && !supportedTypes.includes('selection')) {
                ope = 'ilike'; opv = `''`;
            } else if (supportedTypes.includes('date')) {
                const nowStr = luxon.DateTime.utc().toFormat('yyyy-MM-dd HH:mm:ss');
                ope = 'between'; opv = `['${nowStr}', '${nowStr}']`;
            } else if (supportedTypes.includes('float') || supportedTypes.includes('integer')) {
                ope = '=';
            }
        }

        const domain = `[('${column.name}', '${ope}', ${opv})]`;
        this.env.services.dialog.add(DomainSelectorDialog, {
            resModel,
            defaultConnector: '|',
            domain,
            context,
            onConfirm: (domain) => this._applyColumnFilter(column.name, domain),
            disableConfirmButton: (domain) => domain === `[]`,
            title: _t('Filter by ' + column.label),
            confirmButtonText: _t('Apply'),
            discardButtonText: _t('Cancel'),
            isDebugMode: this.env.searchModel.isDebugMode,
        });
    },

    triggerColPop(column) {
        const targetEl = this.rootRef.el.querySelector(`.elvc_${this._normCls(column.name)}`);
        if (targetEl) {
            targetEl.click();
        }
    },

    openInlaceFilter(ev, column) {
        if (this.ffpop.isOpen) {
            this.ffpop.close();
            return;
        }
        const { isDebugMode } = this.env.searchModel;
        const { resModel } = this.props.list.config;

        let defCondition = false;
        if (!this.uo.filterValues[column.name] || this.uo.filterValues[column.name] === '[]') {
            const fieldDef = this.uFieldDefs[column.name];

            // Note: Patch for Property column
            fieldDef.name = column.name;

            const ope = getDomainDisplayedOperators(fieldDef)[0];
            const val = getDefaultValue(fieldDef, ope);
            defCondition = condition(fieldDef.name, ope, val);

            this.uo.filterValues[column.name] = domainFromTree(defCondition);
        }
        this.ffpop.open(ev.target.closest('.form-control'), {
            widget: this,
            className: 'u_field_filter px-4 py-3',
            readonly: false,
            resModel,
            isDebugMode,
            defaultConnector: '|',
            forceFieldPath: column.name,
            defCondition: defCondition,
            domain: this.uo.filterValues[column.name],
            update: (domain, path) => {
                this.uo.filterValues[path] = domain;
            },
            applyDomain: (path) => {
                this.onFiltoverClose = null;
                this._applyColumnFilter(column.name, this.uo.filterValues[path]);
            }
        });
        this.onFiltoverClose = () => {
            const groupKey = '_GID_' + column.name;
            const currentGroup = this.uo.filterValues[groupKey];
            if (!currentGroup)
                delete this.uo.filterValues[column.name];
        }
    },

    closeCurrentPop(popClass) {
        this.fbpop.close();
        const currentPop = document.querySelector(`.${popClass}.show`);
        if (currentPop) {

            // NOTE: Manual closing of dropdown, make it auto
            currentPop.click();
        }
    },

    async uClearAllFilter() {
        if (this.isX2Many) {
            this._clearX2ManyFilter();
        } else {
            const filterNode = toRaw(this.uo.filterValues);
            for (const path in filterNode) {
                if (!path.startsWith('_GID_')) continue;
                if (filterNode[path]) {
                    this.env.searchModel.deactivateGroup(filterNode[path]);
                }
            }
        }
        // Note: Keep it last
        this.uo.filterValues = { '_FK_': this.uftKey };
    },

    // -------------------------------------------------------------------------
    // Private
    // -------------------------------------------------------------------------

    _normCls(input) {
        // Replace all non-word characters (except dash) with dashes
        let cls = input.trim()
            .toLowerCase()
            .replace(/[^a-z0-9\-_]/g, '-');

        // Ensure it doesn't start with a digit (prefix with underscore if so)
        if (/^[0-9]/.test(cls)) {
            cls = '_' + cls;
        }

        return cls;
    },

    async _clearColumnFilter(path) {
        const groupKey = '_GID_' + path;
        const currentGroup = this.uo.filterValues[groupKey];

        delete this.uo.filterValues[path];
        delete this.uo.filterValues[groupKey];

        if (this.isX2Many) {
            await this._clearX2ManyFilter(path);
        } else if (currentGroup) {
            this.env.searchModel.deactivateGroup(currentGroup);
        }
    },

    async _execX2ManyFilter() {
        const { _initialCurrentIds, config } = this.props.list;
        const domainNode = [];
        const filterNode = toRaw(this.uo.filterValues);

        // Extract filter nodes and mark X2Many filtered paths
        for (const path in filterNode) {
            if (path.startsWith('_')) {
                continue;
            }
            domainNode.push(filterNode[path]);
            this.uo.filterValues[`_GID_${path}`] = 'X2';
        }

        if (!domainNode.length) return;

        // Apply filter using ORM call
        const x2ManyFilteredIds = await this.orm.call(
            config.resModel,
            'uweb_filter_x2',
            [_initialCurrentIds, domainNode]
        );

        this.uState.x2ManyFds = x2ManyFilteredIds;
    },

    _clearX2ManyFilter(path = false) {
        if (path) {
            delete this.uo.filterValues[path];
        }
        delete this.uState.x2ManyFds;
    },

    async _applyColumnFilter(path, domain) {
        this.uo.filterValues[path] = domain;

        if (this.isX2Many) {
            await this._execX2ManyFilter();
        } else {
            const callback = (groupId) => { this.uo.filterValues['_GID_' + path] = groupId; }
            const currentGroup = this.uo.filterValues['_GID_' + path];
            await this.env.searchModel.uSplitAndAddDomain(domain, currentGroup, callback);
        }
    },

    async _validateFilterDomain(path, operator, value) {
        const { resModel } = this.props.list.config;

        let domain, domainStr, isValid;
        try {
            const evalContext = { ...user.context, ...this.env.searchModel.domainEvalContext };
            domainStr = domainFromTree(condition(path, operator, value));
            domain = new Domain(domainStr).toList(evalContext);
        } catch {
            isValid = false;
        }
        if (isValid === undefined) {
            isValid = await rpc('/web/domain/validate', {
                model: resModel,
                domain,
            });
        }
        if (!isValid) {
            this.notification.add(_t('Domain is invalid. Please correct it!'), {
                type: 'danger',
            });
            return isValid;
        }
        return domainStr;
    },

    // -------------------------------------------------------------------------
    // Overridle
    // -------------------------------------------------------------------------
    async toggleOptionalField(fieldName) {
        super.toggleOptionalField(fieldName);
        this.uState.fieldDefsLocked = false;
    },

    getColumnClass(column) {
        let classes = super.getColumnClass(column);
        if (this.uIsStorable(column)) {
            classes += ' o_column_storeable'
        }
        return classes;
    },

    getActiveColumns(list) {
        const res = super.getActiveColumns(list);

        // NOTE: Incompatible AccountReportListRenderer: it does not call the setup method
        if (!this.uState || !this.uo) return res;

        this.uState.hasXColumnFilter = this.allColumns.some(el => el.options?.filterable == true);

        if (!this.uState.fieldDefsLocked && (this.uState.hasXColumnFilter || (this.uo.useFilterBar || this.uo.useFilterBarPop))) {
            this.uLoadingFieldDefs = true;
            this.loadColumnFieldDefs(this.uState.hasXColumnFilter ? this.allColumns : res, list);
        }
        return res;
    },
});
