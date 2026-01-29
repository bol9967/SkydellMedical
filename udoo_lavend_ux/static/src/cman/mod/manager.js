import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';
import { useSortable } from '@web/core/utils/sortable_owl';
import { useAutofocus, useService } from '@web/core/utils/hooks';
import { usePopover } from '@web/core/popover/popover_hook';
import { resetViewCompilerCache } from '@web/views/view_compiler';
import { registry } from '@web/core/registry';

import { Record } from '@web/model/record';
import { Dialog } from '@web/core/dialog/dialog';
import { DropdownItem } from '@web/core/dropdown/dropdown_item';
import { SelectMenu } from '@web/core/select_menu/select_menu';
import { CheckBox } from '@web/core/checkbox/checkbox';
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { MultiRecordSelector } from '@web/core/record_selectors/multi_record_selector';
import { Component, useRef, useState } from '@odoo/owl';


export class ManagerDialog extends Dialog {
    static template = 'omux_list_explorer.ManagerDialog';
    static props = {
        ...Dialog.props, slots: {
            type: Object,
            shape: {
                default: Object, // Content is not optional
                overview: { type: Object, optional: true },
                header: { type: Object, optional: true },
                footer: { type: Object, optional: true },
            },
        }
    }
}

export class ColumnModifer extends Component {
    static components = {
        DropdownItem,
        SelectMenu,
        Record,
        MultiRecordSelector,
    };
    static template = 'omux_list_explorer.ColumnModifer';
    static props = {
        widget: { type: Object },
        className: { type: String },
        fieldNode: { type: Object, optional: true },
        userGroup: { type: Object, optional: true },
        remove: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.state = useState({
            widget: this.props.widget,
        });
    }

    get allowGroupsProps() {
        return {
            resModel: 'res.groups',
            resIds: this.state.widget.allow_group_ids || [],
            update: (resIds) => {
                this.state.widget.allow_group_ids = resIds;
            },
        };
    }

    get forbidGroupsProps() {
        return {
            resModel: 'res.groups',
            resIds: this.state.widget.forbid_group_ids || [],
            domain: [['id', 'not in', this.props.userGroup]],
            update: (resIds) => {
                this.state.widget.forbid_group_ids = resIds;
            },
        };
    }

    get optionalVisibilityChoices() {
        return [
            { label: _t('Show by default'), value: 'show' },
            { label: _t('Hide by default'), value: 'hide' },
        ]
    }

    onSelectOptional(value) {
        this.state.widget.attrs.optional = value;
    }
}

export class ColumnManager extends Component {
    static template = 'omux_list_explorer.ColumnManager';
    static components = {
        Dialog: ManagerDialog,
        CheckBox,
    };
    static props = {
        viewId: { type: Number },
        resModel: { type: String },
        fields: { type: Object },
        fieldNodes: { type: Object },
        close: { type: Function },
    };

    setup() {
        this.ui = useService('ui');
        this.dialog = useService('dialog');

        this.state = useState({
            searchValue: '',
            isSmall: this.env.isSmall,
        });

        this.resetVisibleColumns();

        this.draggableRef = useRef('draggable');
        this.btnCancel = useAutofocus();

        this.dropover = usePopover(ColumnModifer, {
            closeOnClickAway: false,
            popoverClass: 'u_column_attrs fs-6',
            position: 'left-middle',
        });

        useSortable({
            // Params
            ref: this.draggableRef,
            elements: '.o_cman_field',
            enable: !this.state.isSmall,
            cursor: 'grabbing',
            // Hooks
            onDrop: async ({ element, previous, next }) => {

                const order = this.state.visibleColumns.map((col) => col.uid);
                const colId = element.dataset.uid;
                const colNm = element.dataset.col;
                const colKey = colNm + '_0';
                const colIndex = order.indexOf(colId);

                this.demKeepTrack(colNm);

                order.splice(colIndex, 1);
                if (previous) {
                    const prevIndex = order.indexOf(previous.dataset.uid);
                    order.splice(prevIndex + 1, 0, colId);

                    if (this.props.fieldNodes[colKey]) {
                        this.keepTrack[colNm].prev_node = { id: previous.dataset.col, move: true };
                    } else {
                        this.keepTrack[colNm].prev_node = previous.dataset.col;
                    }

                    delete this.keepTrack[colNm].next_node;

                } else {
                    order.splice(0, 0, colId);

                    if (this.props.fieldNodes[colKey]) {
                        this.keepTrack[colNm].next_node = { id: next.dataset.col, move: true };
                    } else {
                        this.keepTrack[colNm].next_node = next.dataset.col;
                    }

                    delete this.keepTrack[colNm].prev_node;
                }

                const newVisibleColumns = order.map(o => this.state.visibleColumns.find(bm => bm.uid === o));
                this.state.visibleColumns = newVisibleColumns;
            },
        });
    }

    isMatchingSearch(column) {
        if (!this.state.searchValue) {
            return true;
        }
        const search = this.state.searchValue.toLowerCase();
        let matches = column.string.toLowerCase().includes(search);
        if (!matches && this.env.debug && column.name) {
            matches = column.name.toLowerCase().includes(search);
        }
        return matches;
    }

    get isDebug() {
        return Boolean(odoo.debug);
    }

    get existingColumns() {
        const resModel = this.props.resModel;
        const filtered = Object.entries(this.props.fields).filter(([fName, field]) => {
            if (resModel === 'res.users' && (fName.startsWith('in_group_') || fName.startsWith('sel_groups_'))) {
                // These fields are virtual and represent res.groups hierarchy.
                // If the hierarchy changes, the field is replaced by another one and the view will be
                // broken, so, here we prevent adding them.
                return false;
            }
            if (!this.isMatchingSearch(field) || this.props.filterFields && this.props.fieldNodes[fName + '_0']) {
                return false;
            }
            return true;
        });

        return filtered.map(([fName, field]) => {
            return {
                ...field,
                name: fName,
                classType: field.type,
                dropData: JSON.stringify({ fieldName: fName }),
            };
        }).sort((a, b) => a.string.localeCompare(b.string));
    }

    get nextTrackIndex() {
        let max = 0;
        for (const k of Object.values(this.keepTrack)) {
            if (max < k.order) max = k.order;
        }
        return max + 1;
    }

    isColSelected(column) {
        return this.state.visibleColumns.some(el => el.name === column);
    }

    async openColModifer(ev, column) {
        this.demKeepTrack(column.name);

        const widget = this.keepTrack[column.name];
        const fieldNode = this.props.fieldNodes && this.props.fieldNodes[column.uid];

        const { allow, forbid, ugroup } = await rpc('/omux/lcrv_parser', { view_id: this.props.viewId, field: column.name });

        if (!widget.allow_group_ids && allow)
            widget.allow_group_ids = allow;
        if (!widget.forbid_group_ids && forbid)
            widget.forbid_group_ids = forbid;

        if (!this.keepTrack[column.name].attrs.string) {
            this.keepTrack[column.name].attrs.string = fieldNode?.string || '';
        }
        this.dropover.open(ev.target.closest('.o_opt_field'), {
            widget,
            fieldNode,
            userGroup: ugroup,
            className: 'u_col_modifer px-4 py-3',
            remove: () => {
                this.onRemoveColumn(column.name);
                this.dropover.close();
            },
        });
    }

    demKeepTrack(columnId) {
        const columnKey = columnId + '_0';
        if (!this.keepTrack[columnId]) {
            const fieldNode = this.props.fieldNodes[columnKey];
            this.keepTrack[columnId] = {
                order: this.nextTrackIndex,
                attrs: {
                    name: columnId,
                    optional: fieldNode.attrs?.optional,
                },
            };
        }
    }

    onAddColumn(columnId) {
        const columnKey = columnId + '_0';
        const fieldNode = this.props.fieldNodes[columnKey] || {
            string: this.props.fields[columnId].string,
            required: this.props.fields[columnId].required,
            readonly: this.props.fields[columnId].readonly,
        };

        let nextColumn;
        const lenCols = this.state.visibleColumns.length;
        for (let idx = 0; idx < lenCols; idx++) {
            const elem = this.state.visibleColumns[idx];
            if (elem.column_invisible != 'True') {
                nextColumn = elem;
                break;
            }
        }
        nextColumn = nextColumn || this.state.visibleColumns[0];

        this.keepTrack[columnId] = {
            order: this.nextTrackIndex,
            next_node: nextColumn.name,
            attrs: {
                name: columnId,
                optional: fieldNode.attrs?.optional,
            },
        }

        // #001
        this.state.visibleColumns.unshift({
            name: columnId,
            label: fieldNode.string,
            column_invisible: fieldNode.column_invisible,
            required: fieldNode.required,
            readonly: fieldNode.readonly,
            optional: fieldNode.optional,
            uid: columnKey,
        });
    }

    onRemoveColumn(columnId) {
        const columnKey = columnId + '_0';

        // TODO: There are cases that appear more than once
        if (this.props.fieldNodes[columnKey]) {
            this.keepTrack[columnId] = {
                order: this.nextTrackIndex,
                replace: true,
                attrs: {
                    name: columnId,
                },
            };
        } else {
            let prevNode, nextNode;
            for (let idx = 0; idx < this.state.visibleColumns.length; idx++) {
                const vcol = this.state.visibleColumns[idx];
                if (vcol.name == columnId) {
                    if (idx > 0) {
                        prevNode = this.state.visibleColumns[idx - 1].name;
                    } else if (idx + 1 <= this.state.visibleColumns.length) {
                        nextNode = this.state.visibleColumns[idx + 1].name;
                    } else {
                        prevNode = this.state.visibleColumns[0].name;
                    }

                    // Update nodes whose node links have been removed
                    for (const key in this.keepTrack) {
                        const kcol = this.keepTrack[key];
                        if (kcol.prev_node == columnId) {
                            if (prevNode)
                                kcol.prev_node = prevNode;
                            else if (nextNode) {
                                delete kcol.prev_node;
                                kcol.next_node = nextNode;
                            }
                        } else if (kcol.next_node == columnId) {
                            if (nextNode)
                                kcol.next_node = nextNode;
                        }
                    }
                    break;
                }
            }

            delete this.keepTrack[columnId];
        }

        this.state.visibleColumns = this.state.visibleColumns.filter((el) => el.name != columnId);
    }

    resetVisibleColumns() {
        const visibleColumns = [];
        for (const key in this.props.fieldNodes) {
            const node = this.props.fieldNodes[key];

            // #001
            visibleColumns.push({
                name: node.name,
                label: node.string,
                column_invisible: node.column_invisible,
                required: node.required,
                readonly: node.readonly,
                optional: node.optional,
                uid: key,
            })
        }

        this.state.visibleColumns = visibleColumns;
        this.keepTrack = {};
    }

    // =========================================================================================

    async restore() {
        return new Promise((resolve) => {
            const confirm = async () => {
                const res = await rpc('/omux/restore_default_list_view', {
                    view_id: this.props.viewId,
                });
                this.done();
                resolve(res);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t(
                    'Are you sure you want to restore the default view?\r\nAll columns customization on this view will be lost.'
                ),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    async confirm() {
        await rpc('/omux/edit_list_view', {
            view_id: this.props.viewId,
            operations: this.keepTrack,
        });
        this.done();
    }

    async done() {
        resetViewCompilerCache();

        this.env.bus.trigger('CLEAR-CACHES');
        this.env.services.action.loadState();
        this.props.close();
    }
}

registry.category('lazy_components').add('ColumnManager', ColumnManager);
