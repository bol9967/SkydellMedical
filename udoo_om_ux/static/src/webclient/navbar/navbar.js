import { NavBar } from '@web/webclient/navbar/navbar';

import { user } from '@web/core/user';
import { browser } from '@web/core/browser/browser';
import { localization } from '@web/core/l10n/localization';
import { loadLanguages, _t } from '@web/core/l10n/translation';
import { cookie } from '@web/core/browser/cookie';
import { isBrowserChrome, isMobileOS } from '@web/core/browser/feature_detection';
import { useSortable } from '@web/core/utils/sortable_owl';
import { useCommand } from '@web/core/commands/command_hook';
import { usePopover } from '@web/core/popover/popover_hook';
import { useAutofocus, useService, useBus } from '@web/core/utils/hooks';
import { computeAppsAndMenuItems, reorderApps } from '@web/webclient/menus/menu_helpers';
import { DropdownItem } from '@web/core/dropdown/dropdown_item';
import { Component, EventBus, onWillStart, onMounted, onPatched, useExternalListener, useState, useRef } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

import { bookmarkCurrentView, bookmarkPalette, bookmarkProvider } from '../bookm/provider';
import { BookmarkPalette } from '../bookm/palette';
import { VIEW_IMAP } from '../action_utils';

export const MIN_SNW = 142;
const MAX_RECENTS = 50;

export function ghostForSidenav() {
    const el = document.querySelector('.o_sidenav');
    if (el && !document.querySelector('.island.o_wdl')) {
        el.classList.remove('opacity-0');
    } else {
        requestAnimationFrame(ghostForSidenav);
    }
}

export class OmuxNavBar extends NavBar {
    static template = 'udoo_om_ux.OmuxNavBar';
    static components = { ...NavBar.components, BookmarkPalette }

    setup() {
        super.setup();

        this.cmd = useService('command');
        this.pwa = useService('pwa');
        this.orm = useService('orm');
        this.ui = useService('ui');
        this.uo = useUdooStore();
        this.ue = useUdooLocalStore();

        this.isMobileOS = isMobileOS();
        this.user = user;

        this.view_imap = VIEW_IMAP;

        const menuOrder = JSON.parse(user.settings?.ps_menu_orders || 'null');
        this.menuApps = computeAppsAndMenuItems(this.menuService.getMenuAsTree('root')).apps;
        this.originApps = Array.of(...this.menuApps);

        if (menuOrder)
            reorderApps(this.menuApps, menuOrder);

        this.uo.orderedApps = this.menuApps;

        this.uState = useState({
            focusix: null,
            ui_view: 'app',
            languages: [],
        });

        this.mapop = usePopover(MenuAppContextMenu, {
            setActiveElement: false,
            closeOnClickAway: true,
            animation: false,
        });

        this.mipop = usePopover(SideNavSub, {
            arrow: false,
            animation: false,
            closeOnClickAway: true,
            setActiveElement: false,
            position: 'right',
            popoverClass: 'sidenav_2nd fs-6',
            onPositioned: (subNav, xPos) => {
                if (this.blockAutoSubnav) {
                    this.mipop.close();
                    return;
                }
                this.computeSubnavPos(subNav);
            },
        });

        /* Favorites sortable */
        this.favDragRoot = useRef('fav_drag_root');
        useSortable({
            ref: this.favDragRoot,
            elements: '.u_draggable',
            applyChangeOnDrop: true,
            cursor: 'move',
            delay: 500,
            onWillStartDrag: (params) => this._sortFavStart(params),
            onDrop: (params) => this._sortFavDrop(params),
        });

        this.searchInput = useAutofocus();
        this.bmkBus = new EventBus();

        this.bmkConfig = bookmarkPalette;
        this.bmkConfig.providers = [
            { provide: (e) => bookmarkProvider(e, { recents: this.uo.recents }) }
        ];

        /* Bookmark command */
        useCommand(
            _t('Bookmark current view'),
            () => { bookmarkCurrentView(this); },
            {
                category: 'smart_action',
                isAvailable: () => this.actionService.currentController,
            }
        );

        useExternalListener(window, 'beforeunload', () => {
            /* Recents post process */
            this.uo.recents.forEach(el => {
                el._x = el._x || objectHash.MD5(el);
            });
            const uniqueArray = [];
            for (let index = this.uo.recents.length - 1; index >= 0; index--) {
                const el = this.uo.recents[index];
                if (uniqueArray.findIndex(o => o._x === el._x) == -1) {
                    uniqueArray.push(el);
                }
            }
            // Save to local context
            if (uniqueArray.length > MAX_RECENTS) {
                uniqueArray.length = MAX_RECENTS;
            }
            this.ue.recents = uniqueArray.reverse();

            /* Bookmark post process */
            if (this.ui.bookmarks.length == 0) {
                return;
            }
            const bookms = [];
            for (let index = this.ui.bookmarks.length - 1; index >= 0; index--) {
                const el = this.ui.bookmarks[index];
                if (bookms.findIndex(o => o._x === el._x) === -1) {
                    bookms.push(el);
                }
            }
            user.setUserSettings('up_bookmarks', JSON.stringify(bookms.reverse()));
        });

        onWillStart(async () => {
            this.uo.fav_menus = JSON.parse(user.settings?.ps_fav_menus) || [];
            this.uState.ui_view = this._getSuiView();
            this.ui.color_scheme = cookie.get('color_scheme');
        });

        onMounted(() => {
            setTimeout(() => { ghostForSidenav(); }, 98);
        });

        useBus(this.env.bus, 'ACTION_MANAGER:UI-UPDATED', (mode) => {
            setTimeout(() => {
                let scrollEl = document.querySelector(`.nav-link.on[data-section="${this.currentApp?.id}"]`);
                scrollEl = scrollEl?.closest('.sidenav_group') || scrollEl;
                scrollEl?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'nearest',
                });
            }, 235);
        });

        useBus(this.env.bus, 'ISLAND:HM', ({ detail }) => {
            if (detail === false) {
                this.toggleLaunchpad();
                return;
            }
            this.uState.ui_view = this._getSuiView();
            this.toggleLaunchpad();
        });

        useBus(this.env.bus, 'SUBNAV:PS', ({ detail }) => {
            if (detail) {
                this.computeSubnavPos(detail, true);
            }
        });

        useBus(this.env.bus, 'UDOO:BMK', () => {
            bookmarkCurrentView(this);
        });

        useBus(this.env.bus, 'UDOO:FRC', ({ detail }) => {
            const obj = {
                res_model: detail.resModel,
                name: detail.displayName,
                res_id: detail.resId,
            }
            if (detail.viewId) obj.view_id = detail.viewId;
            if (this.currentApp?.name) obj._p = this.currentApp.name;

            this.uo.recents.push(obj);
            if (this.uo.recents.length > MAX_RECENTS) {
                this.uo.recents.shift();
            }
        });
    }

    computeSubnavPos(subNav, anim = false) {
        const currentRect = this.lastSubnavEl.getBoundingClientRect();

        const tPadding = 50;
        const bPadding = 10;

        const oSubNavCssText = subNav.style.cssText;
        subNav.style.visibility = 'hidden';
        subNav.style.display = 'block';
        const hPanel = subNav.offsetHeight;
        subNav.style.cssText = oSubNavCssText;

        const vBalance = (hPanel - currentRect.height) / 2;
        let alignedTop = currentRect.top - vBalance;

        if (alignedTop <= tPadding) {
            alignedTop = tPadding;
        } else if ((alignedTop + hPanel) >= (window.innerHeight - tPadding)) {
            alignedTop = 0;
        }

        const finalTop = alignedTop ? `${alignedTop}px` : null;
        const finalBottom = alignedTop ? null : `${bPadding}px`;
        const finalLeft = localization.direction == 'rtl' ? 'auto' : `${this.ue.sidenavWidth + 8}px`;
        const finalRight = localization.direction == 'rtl' ? `${this.ue.sidenavWidth + 8}px` : 'auto';

        Object.assign(subNav.style, { left: finalLeft, right: finalRight, top: finalTop, bottom: finalBottom });

        // Firefox has inconsistent column layout behavior when using `column-width`:
        // It renders multiple columns visually, but doesn't expand the container width correctly,
        // causing layout clipping unless explicitly fixed.
        //
        // This logic detects when multiple vertical columns are rendered by checking
        // the unique `.x` positions of `.subnav_section` elements.
        //
        // For each unique column (by `rect.x`), we add its actual width,
        // along with a fixed column gap and total wrapper padding.
        //
        // Padding = 15px (left) + 15px (right) + 1px (border-left) + 1px (border-right) = 32px
        if (!isBrowserChrome()) {
            const wrapper = subNav.querySelector('.subnav_wrapper');
            const sections = wrapper?.querySelectorAll('.subnav_section');
            if (!sections?.length) return;

            const xMap = new Map();
            for (const el of sections) {
                const rect = el.getBoundingClientRect();
                if (!xMap.has(rect.x)) xMap.set(rect.x, rect.width);
            }
            if (xMap.size > 1) {
                requestAnimationFrame(() => {
                    subNav.style.width = `${[...xMap.values()].reduce((s, w) => s + w, (xMap.size - 1) * 10 + 32)}px`;
                });
            } else {
                subNav.style.width = null;
            }
        }
    }

    get currentApp() {
        if (this.monkeyApp)
            return this.menuService.getMenu(this.monkeyApp);
        else
            return super.currentApp;
    }

    /**
     * @override
     */
    onAllAppsBtnClick() {
        super.onAllAppsBtnClick();
        this.toggleLaunchpad();
        this._closeAppMenuSidebar();
    }

    initIsland() {
        // Hack: Force a re-render to update the useRef for the dropdown workaround
        this.uState.ui_view = '';
        if (this.forceUiView) {
            this.uState.ui_view = this.forceUiView;
            delete this.forceUiView;
        } else {
            this.uState.ui_view = this._getSuiView();
        }

        // Hack: force fullscreen island mode without reactive mess
        if (this.ui.onceFullIsland) {
            this.uState.fullIsland = true;
            this.ui.onceFullIsland = false;
        } else {
            this.uState.fullIsland = false;
        }
    }

    intoIsland() {
        setTimeout(() => { this.searchInput.el?.focus(); }, 200);
    }

    endoIsland(state) {
        if (!state && this.forceUiView) {
            this.uState.ui_view = this.forceUiView;
            this.forceUiView = undefined;
        }
    }

    toggleLaunchpad() {
        this.__owl__.bdom.el.querySelector('#island_toggler').click();
    }

    switchSpace(ev) {
        const el = ev.target.closest('.nav-link');
        if (this.uState.ui_view !== el.dataset.tab) {
            let uiView = el.dataset.tab;
            if (el.dataset.tab == 'pick') {
                uiView = this.uo.fav_menus.length ? 'app' : 'all_app';
            }
            this.uState.ui_view = uiView;
        }
        setTimeout(() => { this.searchInput.el?.focus(); }, 200);
    }

    onIslandContext(ev) {
        const el = ev.target.closest('a');
        this.uState.currentMenuXmlid = el.dataset.menuXmlid;
        this.mapop.open(el, { widget: this });
    }

    async lazoLang() {
        if (!this.uState.languages.length && user.userId) {
            this.uState.languages = await loadLanguages(this.orm);
        }
    }

    async switchLang(lang) {
        if (lang === user.lang) return;

        await this.orm.write('res.users', [user.userId], { lang });
        this.ui.block();
        this.actionService.doAction('reload_context');
    }

    switchColorScheme(ev) {
        const target = this.ui.color_scheme === 'dark' ? 'light' : 'dark';
        cookie.set('color_scheme', target);
        this.ui.block();
        browser.location.reload();
    }

    onSearchExec() {
        if (this.uState.ui_view == 'space') {
            this.env.bus.trigger('BMK:SEARCH', this.searchInput.el.value);
        } else {
            const searchValue = `/${this.searchInput.el.value.trim()}`;
            this.searchInput.el.value = '';

            this.cmd.openMainPalette({ searchValue });
        }
    }

    isCurrentApp(app) {
        if (this.currentApp && app) return this.currentApp.id === app.id;
        return false;
    }

    onSelectMenu(app) {
        this.mipop.close();

        this.blockAutoSubnav = true;
        setTimeout(() => {
            this.blockAutoSubnav = false;
        }, 1200);

        this.onNavBarDropdownItemSelection(app);
    }

    openActivityHub() {
        this.actionService.doAction({
            name: _t('Activity Hub'),
            type: 'ir.actions.act_window',
            res_model: 'mail.activity',
            view_mode: 'kanban,list',
            views: [
                [false, 'kanban'],
                [false, 'list'],
            ],
            context: {
                'search_default_filter_user_id_uid': 1,
                'search_default_filter_date_deadline_past': 1,
                'search_default_filter_date_deadline_today': 1,
                'search_default_group_by_res_model_id': 1,
            }
        });
    }

    preSubnavTiming(ev, appsub) {
        ev.preventDefault();
        if (this.blockAutoSubnav) {
            return;
        }
        if (this.autoSubTimer) {
            clearTimeout(this.autoSubTimer);
            this.autoSubTimer = null;
        }

        const evTarget = ev.target.closest('.nav-item');
        const secondNav = document.querySelector('.sidenav_2nd');
        if (secondNav && this.lastSubnavEl === evTarget) {
            return;
        }

        if (secondNav) {
            const isRTL = localization.direction == 'rtl';
            const relativeX = isRTL ? (window.innerWidth - ev.x) : ev.x;
            if (relativeX > 0.7 * this.ue.sidenavWidth) {
                return; // in the skip zone (30%)
            }
            this.autoSubTimer = setTimeout(() => {
                this.lastSubnavEl = evTarget;
                this.onShowSubnav(this.lastSubnavEl, appsub);
            }, 10);
        } else {
            const onCurrentApp = evTarget.firstChild.classList.contains('on');
            this.autoSubTimer = setTimeout(() => {
                const k = appsub.map(n => n.id).join('');
                if (evTarget.matches(':hover') && !document.querySelector(`.sidenav_2nd>._${k}`))
                    this.onShowSubnav(this.lastSubnavEl = evTarget, appsub);
            }, onCurrentApp ? 300 : 600);
        }
    }

    onMouseLeaveNavItem(ev) {
        if (this.autoSubTimer) {
            clearTimeout(this.autoSubTimer);
            this.autoSubTimer = null;
        }
    }

    onShowSubnav(ev, appsub, isCtx = false) {
        const subuid = '_' + appsub.map(node => node.id).join('');
        let el = ev;
        if (ev instanceof PointerEvent) {
            ev.preventDefault();
            ev.stopPropagation();
            el = ev.target;
        }
        if (this.blockAutoSubnav || (isCtx && document.querySelector(`.sidenav_2nd > .${subuid}`))) {
            return;
        }
        this.lastSubnavEl = el.closest('.nav-item');
        if (this.mipop.isOpen) {
            Object.assign(this.mipop.instance.props, { subuid, appsub });
            this.mipop.instance.render();
            return;
        }
        this.mipop.open(this.lastSubnavEl, {
            getMenuItemHref: (payload) => this.getMenuItemHref(payload),
            onSelectMenu: (menu) => {
                this.onSelectMenu(menu);
                queueMicrotask(() => { this.mipop.close(); });
            },
            self: this.mipop,
            subuid,
            appsub,
            _evicon: this._evicon,
            _esymbl: this._esymbl,
        });
    }

    async openRecentAction(action) {
        this.ui.block_recent = true;
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            view_mode: 'form',
            views: [[false, 'form']],
            ...action,
        });
    }

    getAppSections(id) {
        this.monkeyApp = id;
        const monkeySections = this.currentAppSections;
        this.monkeyApp = false;
        return monkeySections;
    }

    revealAcion(app) {
        let webIcon = app.webIcon;
        if (app.webIcon && typeof app.webIcon == 'string') {
            webIcon = this._esymbl(app.webIcon);
        }
        return { ...app, webIcon };
    }

    _getSuiView() {
        return this.uo.fav_menus?.length && !this.ue.sidenav ? 'app' : 'all_app';
    }

    _sortFavStart({ element, addClass }) {
        addClass(element.children[0], 'u_dragged_app');
    }

    async _sortFavDrop({ element, previous }) {
        const order = this.uo.orderedApps.map((app) => app.xmlid);
        const xmlId = element.children[0].dataset.menuXmlid;
        const xmlIdIndex = order.indexOf(xmlId);

        order.splice(xmlIdIndex, 1);
        if (previous) {
            const prevIndex = order.indexOf(previous.children[0].dataset.menuXmlid);
            order.splice(prevIndex + 1, 0, xmlId);
        } else {
            order.splice(0, 0, xmlId);
        }

        // apply new order and sync
        reorderApps(this.uo.orderedApps, order);
        await user.setUserSettings('ps_menu_orders', JSON.stringify(order));
    }

    _evicon(webIconData) {
        const prefix = webIconData.startsWith('P')
            ? 'data:image/svg+xml;base64,'
            : 'data:image/png;base64,';
        return webIconData.startsWith('data:image')
            ? webIconData
            : prefix + webIconData.replace(/\s/g, '');
    }

    _esymbl(webIconStr) {
        const [iconClass, color, backgroundColor] = webIconStr.split(',');
        return {
            iconClass: iconClass || null,
            color: color || null,
            backgroundColor: backgroundColor || null,
        };
    }
}

export class MenuAppContextMenu extends Component {
    static template = 'wub.MenuAppContextMenu';
    static props = { '*': true };

    contextPinStart() {
        const { uState, uo } = this.props.widget;
        return uo.fav_menus.includes(uState.currentMenuXmlid);
    }

    appinNewTab() {
        this.props.close();

        setTimeout(() => {
            const { uState, originApps, getMenuItemHref } = this.props.widget;
            const cApp = originApps.find((el) => el.xmlid === uState.currentMenuXmlid);
            if (cApp) window.open(getMenuItemHref(cApp), '_blank').focus();
        }, 77);
    }

    async pinToStart() {
        this.props.close();

        const { uState, uo } = this.props.widget;
        uo.fav_menus.push(uState.currentMenuXmlid);
        user.setUserSettings('ps_fav_menus', JSON.stringify(uo.fav_menus));

        this.props.widget.uState.ui_view = 'app';
    }

    async unpinFromStart() {
        this.props.close();

        const { uState, uo } = this.props.widget;
        const newFavs = uo.fav_menus.filter((o) => o !== uState.currentMenuXmlid);
        uo.fav_menus = newFavs;
        user.setUserSettings('ps_fav_menus', JSON.stringify(newFavs));
    }

    async setHomeAction() {
        this.props.close();

        const { uState, env } = this.props.widget;
        await user.setUserSettings('ps_start_xmlid', uState.currentMenuXmlid);
        env.services.notification.add(
            _t('Home action has been set!'),
            {
                title: _t('Notification'),
                type: 'success',
            }
        );
    }

    async pinThemAllStart() {
        this.props.close();

        const { uState, uo, originApps } = this.props.widget;
        const newFavs = originApps.map((app) => app.xmlid);
        uo.fav_menus = newFavs;
        await user.setUserSettings('ps_fav_menus', JSON.stringify(newFavs));
        uState.ui_view = 'app';
    }
}

export class SideNavSub extends Component {
    static components = { DropdownItem };
    static template = 'wub.Sidenav.2nd';
    static props = { '*': true };

    setup() {
        this.props.self.instance = this.__owl__.component;

        onPatched(() => {
            this.env.bus.trigger('SUBNAV:PS', this.__owl__.bdom?.parentEl);
        });
    }
}