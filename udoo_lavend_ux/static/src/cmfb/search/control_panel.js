import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useBus, useService } from '@web/core/utils/hooks';
import { usePopover } from '@web/core/popover/popover_hook';
import { onWillStart, toRaw } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

import { ControlPanel } from '@web/search/control_panel/control_panel';
import { QuickColumnFilterPopOver } from '../patch/list_renderer';


patch(ControlPanel.prototype, {
    setup() {
        super.setup();

        this.ui = useService('ui');
        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();

        this.filterTabPop = usePopover(QuickColumnFilterPopOver, {
            arrow: false,
        });

        onWillStart(async () => {
            const { config, searchModel } = this.env;
            const actionId = config.actionId;

            if (searchModel) {
                this.uFilterBarItems = searchModel.getSearchItems(o => ['filter', 'favorite'].includes(o.type) && !o.isDefault);
            }

            if (actionId) {
                // Initialize actionAdvs if needed
                if (typeof this.ue.actionAdvs != 'object') {
                    this.ue.actionAdvs = {};
                }
                const actionAdvs = toRaw(this.ue).actionAdvs;

                // Handle list filter bar
                const useListFilterBarCtx = this.useGlobalColFilterBar || this.env.searchModel?.context?.use_list_filter_bar;
                if ((useListFilterBarCtx !== undefined && useListFilterBarCtx)) {
                    this.ue.actionAdvs[actionId] = 1;
                }
                this.uo.useFilterBar = actionAdvs[actionId];

                // Handle filter tab bar
                const useFilterNavBarCtx = this.useGlobalFilterBar || this.env.searchModel?.context?.use_filter_nav_bar;
                if (!actionAdvs['FTB_' + actionId] && (useFilterNavBarCtx !== undefined && useFilterNavBarCtx)) {
                    this.uToggleFilterTabBar(null, this.useGlobalFilterBar);
                } else {
                    this.uo.useFilterTabBar = actionAdvs['FTB_' + actionId];
                }
            }

            // Set popup states
            this.uo.useFilterTabBarPop = this.uo.useFilterTabBar;
            this.uo.useFilterBarPop = this.uo.useFilterBar;
        });

        useBus(this.env.bus, 'ACTION_MANAGER:UI-UPDATED', () => {
            const { env, uo, ue } = this;
            const actionAdvs = toRaw(ue).actionAdvs;
            if (!actionAdvs) return;

            const actionId = env.config.actionId;
            if (env.config.viewType == 'list' && actionAdvs[actionId]) {
                env.bus.trigger('CTL:USEFBR');
            }
            uo.useFilterTabBar = actionAdvs['FTB_' + actionId];
        });
    },

    get uFilterPinnedTabs() {
        const { config, searchModel } = this.env;

        if (searchModel) {
            if (config.actionId) {
                const rawAdvs = toRaw(this.ue).actionAdvs['FTS_' + config.actionId];

                if (!rawAdvs) return [];

                if (rawAdvs === 1) {
                    return this.uFilterBarItems;
                } else {
                    return searchModel.getSearchItems((o) => {
                        return ['filter', 'favorite'].includes(o.type) && rawAdvs[o.id]
                    });
                }
            } else {
                return this.uFilterBarItems;
            }
        }
        return []
    },

    uFilterTabBarSetter(ev) {
        const { env, ue } = this;
        const actionId = env.config.actionId;

        this.filterTabPop.open(ev.target, {
            widget: this,
            items: this.uFilterBarItems,
            itemClass: 'py-1 ps-4 pe-3',
            emptyMsg: _t('No filters found.'),
            popAction: (item, pop) => {
                if (!ue.actionAdvs['FTS_' + actionId]) {
                    ue.actionAdvs['FTS_' + actionId] = {};

                } else if (1 === ue.actionAdvs['FTS_' + actionId]) {
                    const initOpts = {};
                    this.uFilterBarItems.forEach(item => {
                        initOpts[item.id] = 1;
                    });
                    ue.actionAdvs['FTS_' + actionId] = initOpts;
                }
                ue.actionAdvs['FTS_' + actionId][item.id] = !ue.actionAdvs['FTS_' + actionId][item.id];
                pop.render();
            },
            isel: (item) => {
                const itemState = toRaw(ue).actionAdvs['FTS_' + actionId];
                if (itemState === 1) return true;
                else if (itemState) return itemState[item.id];
                return false;
            }
        });
    },

    uToggleFilterTabBar(ev, global = false) {
        const { env, uo, ue } = this;
        const actionId = env.config.actionId;

        if (actionId) {
            this.uo.useFilterTabBarPop = false; // Reset

            uo.useFilterTabBar = global || !uo.useFilterTabBar;
            if (uo.useFilterTabBar) {
                ue.actionAdvs['FTB_' + actionId] = 1;

                const rawAdvs = toRaw(ue).actionAdvs['FTS_' + actionId];

                if (!rawAdvs) {
                    ue.actionAdvs['FTS_' + actionId] = 1;
                }
            } else {
                delete ue.actionAdvs['FTB_' + actionId];
                delete ue.actionAdvs['FTS_' + actionId];
            }
        } else if (env.searchModel) {
            uo.useFilterTabBarPop = !uo.useFilterTabBarPop;
        }
    },

    uToggleFilterTab(item) {
        const { isDefault, id: itemId } = item;
        const { searchModel } = this.env;

        if (isDefault && searchModel.query.find((o) => o.searchItemId == item.id)) {
            return;
        }
        if (this.state.filterTid && searchModel.query.find((o) => o.searchItemId == this.state.filterTid)) {
            searchModel.toggleSearchItem(this.state.filterTid);
        }
        if (!isDefault) {
            this.state.filterTid = itemId;
        }
        searchModel.toggleSearchItem(itemId);
    },
});
