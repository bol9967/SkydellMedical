import { _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { cookie } from '@web/core/browser/cookie';
import { browser } from '@web/core/browser/browser';
import { loadCSS, loadJS } from '@web/core/assets';
import { registry } from '@web/core/registry';
import { utils } from '@web/core/ui/ui_service';
import { useService } from '@web/core/utils/hooks';
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { Component, markup, onWillStart, onWillDestroy, useState, useRef, useExternalListener } from '@odoo/owl';
import { CheckBox } from '@web/core/checkbox/checkbox';
import { Dialog } from '@web/core/dialog/dialog';
import { SelectMenu } from '@web/core/select_menu/select_menu';
import { View } from '@web/views/view';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

export const OM = {
    user_scheme: [
        { 'code': 'magenta', 'title': _t('Magenta'), 'color': '#714B67' },
        { 'code': 'rose', 'title': _t('Rose'), 'color': '#b25968' },
        { 'code': 'lime', 'title': _t('Lime'), 'color': '#66954f' },
        { 'code': 'green', 'title': _t('Green'), 'color': '#19876a' },
        { 'code': 'emerald', 'title': _t('Emerald'), 'color': '#0E837C' },
        { 'code': 'dodger', 'title': _t('Dodger'), 'color': '#2383af' },
        { 'code': 'sky', 'title': _t('Sky'), 'color': '#1e93c9' },
        { 'code': 'indigo', 'title': _t('Indigo'), 'color': '#665f99' },
        { 'code': 'pink', 'title': _t('Pink'), 'color': '#b16080' },
        { 'code': 'orange', 'title': _t('Orange'), 'color': '#ae6464' },
        { 'code': 'yellow', 'title': _t('Yellow'), 'color': '#a98357' },
    ],
    system_scheme: {
        // Brand
        'accent': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Primary'),
            pam: 'o-brand-primary',
        },
        'text_main': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Text Default'),
            pam: 'o-main-text-color',
        },
        'text_header': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Text Strong'),
            pam: 'o-main-headings-color',
        },
        'action': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Action'),
            pam: 'o-action',
        },
        'link': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Link'),
            pam: 'o-main-link-color',
        },

        // Sidebar Navigation
        'sidenav_text': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Text'),
            pam: 'u-sidenav',
        },
        'sidenav_bg': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Background'),
            pam: 'u-sidenav-bg',
        },
        'sidenav_sub': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Active'),
            pam: 'u-sidenav-accent',
        },

        // Navigation Item
        'u_menuitem_hover_bg': {
            nam: markup('<span class="fw-bold">Navigation Item</span>: Hover Background'),
            pam: 'u-menuitem-hover-bg',
        },
        'u_menuitem_hover': {
            nam: markup('<span class="fw-bold">Navigation Item</span>: Hover Text'),
            pam: 'u-menuitem-hover',
        },

        // Feedback (Indication)
        'o_text_success': {
            nam: markup('<span class="fw-bold">Feedback</span>: Success Text'),
            pam: 'u-text-success',
        },
        'o_text_info': {
            nam: markup('<span class="fw-bold">Feedback</span>: Info Text'),
            pam: 'u-text-info',
        },
        'o_text_warning': {
            nam: markup('<span class="fw-bold">Feedback</span>: Warning Text'),
            pam: 'u-text-warning',
        },
        'o_text_danger': {
            nam: markup('<span class="fw-bold">Feedback</span>: Danger Text'),
            pam: 'u-text-danger',
        },
        'o_success': {
            nam: markup('<span class="fw-bold">Feedback</span>: Success Background'),
            pam: 'o-success',
        },
        'o_info': {
            nam: markup('<span class="fw-bold">Feedback</span>: Info Background'),
            pam: 'o-info',
        },
        'o_warning': {
            nam: markup('<span class="fw-bold">Feedback</span>: Warning Background'),
            pam: 'o-warning',
        },
        'o_danger': {
            nam: markup('<span class="fw-bold">Feedback</span>: Danger Background'),
            pam: 'o-danger',
        },

        // Tag / Kanban Card Colors (indexed)
        'kolor_1': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 1'), pam: 'u-kolor-1' },
        'kolor_2': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 2'), pam: 'u-kolor-2' },
        'kolor_3': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 3'), pam: 'u-kolor-3' },
        'kolor_4': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 4'), pam: 'u-kolor-4' },
        'kolor_5': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 5'), pam: 'u-kolor-5' },
        'kolor_6': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 6'), pam: 'u-kolor-6' },
        'kolor_7': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 7'), pam: 'u-kolor-7' },
        'kolor_8': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 8'), pam: 'u-kolor-8' },
        'kolor_9': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 9'), pam: 'u-kolor-9' },
        'kolor_10': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 10'), pam: 'u-kolor-10' },
        'kolor_11': { nam: markup('<span class="fw-bold">Tag / Kanban Card Colors</span>: Color 11'), pam: 'u-kolor-11' },

        // Neutral Palette (Gray 100..900)
        'neutral_100': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 100'),
            pam: 'o-gray-100',
        },
        'neutral_200': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 200'),
            pam: 'o-gray-200',
        },
        'neutral_300': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 300'),
            pam: 'o-gray-300',
        },
        'neutral_400': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 400'),
            pam: 'o-gray-400',
        },
        'neutral_500': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 500'),
            pam: 'o-gray-500',
        },
        'neutral_600': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 600'),
            pam: 'o-gray-600',
        },
        'neutral_700': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 700'),
            pam: 'o-gray-700',
        },
        'neutral_800': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 800'),
            pam: 'o-gray-800',
        },
        'neutral_900': {
            nam: markup('<span class="fw-bold">Neutral Palette</span>: Gray 900'),
            pam: 'o-gray-900',
        },
    },
    extra_feat: [
        {
            k: 'dsy',
            n: _t('List Density'),
            d: {
                default: _t('Default'),
                cozy: _t('Cozy'),
                roomy: _t('Roomy'),
            }
        },
        {
            k: 'dsf',
            n: _t('Form Density'),
            d: {
                default: _t('Default'),
                cozy: _t('Cozy'),
                roomy: _t('Roomy'),
            }
        },
        {
            k: 'ips',
            n: _t('Input Style'),
            d: {
                default: _t('Default'),
                underlined: _t('Underlined'),
                filled: _t('Filled'),
            }
        },
        {
            k: 'brd',
            n: _t('Border Radius'),
            d: {
                default: _t('Default'),
                sharp: _t('Sharp'),
                subtle: _t('Subtle'),
                moderate: _t('Moderate'),
                soft: _t('Soft'),
            }
        },
    ],
    swatches: [
        '#0078FF',
        '#0085E0',
        '#0092C5',
        '#009FB0',
        '#00A99D',
        '#14A58A',
        '#29A383',
        '#39A072',
        '#518F6A',
        '#667F62',
        '#7B6AA4',
        '#8F5A87',
        '#A05A76',
        '#B25968',
        '#C4595A',

        '#0A1A2F',
        '#1A2A40',
        '#293548',
        '#2D3D4A',
        '#384556',
        '#464E59',
        '#53585F',
        '#5F5F5F',
        '#6A6560',
        '#766F66',
        '#816C60',
        '#89665C',
        '#744F52',
        '#5A4446',
        '#3D3D3D',
    ]
    ,
    uiz_desc: {
        VSM: _t('Underline input fields; Set default form list view to Kanban; Position Chatter at bottom; Hide Document Viewer by default'),
        SM: _t('Set default form list view to Kanban; Position Chatter at bottom; Hide Document Viewer by default'),
        MD: _t('Position Chatter at bottom; Hide Document Viewer by default'),
        LG: _t('Position Chatter at bottom; Hide Document Viewer by default'),
        XL: _t('Position Chatter at bottom; Document Viewer on right if present'),
        XXL: _t('Position Chatter and Document Viewer on right')
    },
    font_choices: [
        { label: _t('Default (System)'), value: 'default' },
        { label: 'Adobe Font: Source Sans Pro', value: 'Source+Sans+3:ital,wght@0,200..700%3B1,200..700&display=swap' },
        { label: 'Fiori Design: Font 72', value: 'Font+72' },
        { label: 'Google Font: Alegreya Sans', value: 'Alegreya+Sans:ital,wght@0,300%3B0,400%3B0,500%3B0,700%3B1,300%3B1,400%3B1,500%3B1,700&display=swap' },
        { label: 'Google Font: BVN Pro', value: 'Be+Vietnam+Pro:ital,wght@0,100%3B0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,100%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Font: Cairo', value: 'Cairo:wght@200..700&display=swap' },
        { label: 'Google Font: Cairo Play', value: 'Cairo+Play:wght@200..700&display=swap' },
        { label: 'Google Font: Dosis', value: 'Dosis:wght@200..700&display=swap' },
        { label: 'Google Font: Duru Sans', value: 'Duru+Sans:ital,wght@0,200..900%3B1,200..900&display=swap' },
        { label: 'Google Font: Encode Sans', value: 'Encode+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: Encode Sans Semi Expanded', value: 'Encode+Sans+Semi+Expanded:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: Exo', value: 'Exo:wght@200..700&display=swap' },
        { label: 'Google Font: Exo 2', value: 'Exo+2:wght@200..700&display=swap' },
        { label: 'Google Font: Glory', value: 'Glory:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Font: Gothic A1', value: 'Gothic+A1:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: IBM Plex Sans', value: 'IBM+Plex+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: IBM Plex Sans Arabic', value: 'IBM+Plex+Sans+Arabic:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: IBM Plex Sans Hebrew', value: 'IBM+Plex+Sans+Hebrew:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: IBM Plex Sans JP', value: 'IBM+Plex+Sans+JP:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: IBM Plex Sans KR', value: 'IBM+Plex+Sans+KR:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Font: Inter', value: 'Inter:wght@200..700&display=swap' },
        { label: 'Google Font: Josefin Sans', value: 'Josefin+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: Karla', value: 'Karla:wght@200..700&display=swap' },
        { label: 'Google Font: Lato', value: 'Lato:ital,wght@0,100%3B0,300%3B0,400%3B0,700%3B1,100%3B1,300%3B1,400%3B1,700&display=swap' },
        { label: 'Google Font: Mada', value: 'Mada:wght@200..700&display=swap' },
        { label: 'Google Font: Manrope', value: 'Manrope:wght@200..700&display=swap' },
        { label: 'Google Font: Merriweather Sans', value: 'Merriweather+Sans:wght@300..700&display=swap' },
        { label: 'Google Font: Montserrat', value: 'Montserrat:ital,wght@0,100..900%3B1,100..900&display=swap' },
        { label: 'Google Font: Mulish', value: 'Mulish:wght@200..700&display=swap' },
        { label: 'Google Font: Noto Kufi Arabic', value: 'Noto+Kufi+Arabic:wght@200..700&display=swap' },
        { label: 'Google Font: Noto Sans', value: 'Noto+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: Noto Sans Georgian', value: 'Noto+Sans+Georgian:wght@200..700&display=swap' },
        { label: 'Google Font: Noto Sans JP', value: 'Noto+Sans+JP:wght@200..700&display=swap' },
        { label: 'Google Font: Noto Sans SC', value: 'Noto+Sans+SC:wght@200..700&display=swap' },
        { label: 'Google Font: Nunito', value: 'Nunito:ital,wght@0,200..700%3B1,200..700&display=swap' },
        { label: 'Google Font: Nunito Sans', value: 'Nunito+Sans:ital,opsz,wght@0,6..12,200..700%3B1,6..12,200..700&display=swap' },
        { label: 'Google Font: Open Sans', value: 'Open+Sans:ital,wght@0,300..700%3B1,300..700&display=swap' },
        { label: 'Google Font: Oswald', value: 'Oswald:wght@200..700&display=swap' },
        { label: 'Google Font: Oxanium', value: 'Oxanium:wght@200..700&display=swap' },
        { label: 'Google Font: Plus Jakarta Sans', value: 'Plus+Jakarta+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: Poppins', value: 'Poppins:ital,wght@0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Font: Prompt', value: 'Prompt:ital,wght@0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Font: Quicksand', value: 'Quicksand:wght@500..700&display=swap' },
        { label: 'Google Font: Rajdhani', value: 'Rajdhani:wght@500%3B600%3B700&display=swap' },
        { label: 'Google Font: Raleway', value: 'Raleway:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Font: Roboto', value: 'Roboto:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Font: Roboto Condensed', value: 'Roboto+Condensed:wght@200..700&display=swap' },
        { label: 'Google Font: Roboto Flex', value: 'Roboto+Flex:opsz,wght@8..144,200..700&display=swap' },
        { label: 'Google Font: Roboto Slab', value: 'Roboto+Slab:wght@200..700&display=swap' },
        { label: 'Google Font: Rubik', value: 'Rubik:wght@300..700&display=swap' },
        { label: 'Google Font: Sen', value: 'Sen:ital,wght@400..800&display=swap' },
        { label: 'Google Font: Space Grotesk', value: 'Space+Grotesk:wght@300..700&display=swap' },
        { label: 'Google Font: Syne', value: 'Syne:wght@400..700&display=swap' },
        { label: 'Google Font: Tajawal', value: 'Tajawal:wght@300%3B400%3B500%3B700&display=swap' },
        { label: 'Google Font: Titillium Web', value: 'Titillium+Web:ital,wght@0,200%3B0,300%3B0,400%3B0,600%3B0,700%3B0,900%3B1,200%3B1,300%3B1,400%3B1,600%3B1,700&display=swap' },
        { label: 'Google Font: Ubuntu', value: 'Ubuntu:wght@400%3B500%3B700&display=swap' },
        { label: 'Google Font: Work Sans', value: 'Work+Sans:wght@200..700&display=swap' },
        { label: 'Google Font: Zen Kaku Gothic Antique', value: 'Zen+Kaku+Gothic+Antique:wght@300%3B400%3B500%3B700%3B900&display=swap' },
        { label: 'Google Font: Zen Kaku Gothic New', value: 'Zen+Kaku+Gothic+New:wght@300%3B400%3B500%3B700%3B900&display=swap' },
        { label: 'Google Font: Zen Maru Gothic', value: 'Zen+Maru+Gothic:wght@300%3B400%3B500%3B700%3B900&display=swap' },
    ],
    toggler: { 'on': true, 'off': false },
}

export class OmuxConf extends Component {
    static template = 'wub.OmuxConf';
    static components = { CheckBox, Dialog, SelectMenu, View };
    static props = { '*': true };

    setup() {
        this._t = _t;
        this.user = user;
        this.browser = browser;
        this.uiUtils = utils;

        this.ui = useService('ui');
        this.orm = useService('orm');
        this.dialog = useService('dialog');
        this.action = useService('action');
        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();

        this.o_accent = '#05869c';
        this.o_color_shade = cookie.get('color_shade');
        this.o_color_scheme = this.ui.color_scheme || 'light';
        this.o_ps_auto_hmenu = OM.toggler[user.settings?.ps_auto_hmenu];
        this.o_ps_full_iland = OM.toggler[user.settings?.ps_full_iland];

        this.state = useState({
            color_shade: this.o_color_shade,
            color_scheme: this.o_color_scheme,
            ctab: this.ui.omux_conf_ctab || 'sys',
        });

        delete this.ui.omux_conf_ctab;

        this.uiSizes = { VSM: 1, SM: 2, MD: 3, LG: 4, XL: 5, XXL: 6, Auto: 0 };
        this.uiTooltip = OM.uiz_desc;
        this.fontChoices = OM.font_choices;
        this.extraFeat = OM.extra_feat;

        this.defs = OM.system_scheme;
        for (const cl in OM.system_scheme) {
            this[`cp_${cl}`] = useRef(cl);
            this[`cp_dark_${cl}`] = useRef(`dark_${cl}`);
        }

        onWillStart(async () => {
            this.hasGroupOmux = await user.hasGroup('udoo_om_ux.group_omux');

            if (this.hasGroupOmux) {
                await this.sysOnInit();
            }
            this.schemeData = [
                { 'code': '', 'title': _t('Default'), 'color': this.o_accent },
                ...OM.user_scheme,
            ];
        });

        onWillDestroy(() => this._pickrs?.forEach(pickr => pickr.destroyAndRemove()));
        useExternalListener(document, 'pointerdown', this.onAdvMouseDown.bind(this));
    }

    async sysOnInit() {
        const otopKeys = ['g_ips', 'g_brd', 'g_dsy', 'g_dsf', 'g_fty'];
        const ipsState = await this.orm.searchRead(
            'ir.asset',
            [
                '|',
                ['path', 'ilike', 'omux_input_style'],
                '|',
                ['path', 'ilike', 'omux_border_radius'],
                '|',
                ['path', 'ilike', 'omux_list_density'],
                '|',
                ['path', 'ilike', 'feature/island_bg'],
                ['path', 'ilike', 'feature/sidenav_bg'],
            ],
            ['path', 'active'],
            { context: { active_test: false } }
        );

        otopKeys.forEach(key => this[key] = 'default');
        this.g_ftz = 14;
        this.g_wbg = false;
        this.g_snbg = false;

        for (const o of ipsState) {
            if (!o.active) {
                continue;
            }
            if (o.path.endsWith('filled.scss')) {
                this.g_ips = 'filled';
            }
            else if (o.path.endsWith('underlined.scss')) {
                this.g_ips = 'underlined';
            }
            else if (o.path.endsWith('sharp')) {
                this.g_brd = 'sharp';
            }
            else if (o.path.endsWith('subtle')) {
                this.g_brd = 'subtle';
            }
            else if (o.path.endsWith('moderate')) {
                this.g_brd = 'moderate';
            }
            else if (o.path.endsWith('soft')) {
                this.g_brd = 'soft';
            }
            else if (o.path.endsWith('dsfs/cozy.scss')) {
                this.g_dsf = 'cozy';
            }
            else if (o.path.endsWith('dsfs/roomy.scss')) {
                this.g_dsf = 'roomy';
            }
            else if (o.path.endsWith('cozy.scss')) {
                this.g_dsy = 'cozy';
            }
            else if (o.path.endsWith('roomy.scss')) {
                this.g_dsy = 'roomy';
            }
            else if (o.path.endsWith('island_bg.js')) {
                this.g_wbg = true;
            }
            else if (o.path.endsWith('sidenav_bg.js')) {
                this.g_snbg = true;
            }
        }

        let ffStates = await this.orm.searchRead('ir.asset', [['path', '=', '_omux-backend_font.scss']], ['name']);
        for (const rec of ffStates) {
            rec.name.replace(/Font:\s*([^|]+)/i, (_, val) => this.g_fty = val.trim());
            rec.name.replace(/Size:\s*([^|]+)/i, (_, val) => this.g_ftz = val.trim());
        }

        // Assign option state
        otopKeys.forEach(key => { this.state[key] = this[key]; });
        this.state.g_ftz = this.g_ftz;
        this.state.g_wbg = this.g_wbg;
        this.state.g_snbg = this.g_snbg;

        // Load Pickr assets
        await loadJS('/omux_shared_lib/static/lib/pickr/pickr.min.js');
        await loadCSS('/omux_shared_lib/static/lib/pickr/classic.min.css');

        const scVars = Object.values(OM.system_scheme).map(o => o.pam);
        const scMapd = await this.orm.call('web_editor.assets', 'extf_omux_scheme', [scVars]);
        for (const [cl, info] of Object.entries(OM.system_scheme)) {
            ['', 'dark_'].forEach((prefix, i) => {
                const key = `${prefix}${cl}`;
                this[`o_${key}`] = scMapd[i][info.pam];
                this.state[key] = this[`o_${key}`];
            });
        }

        const cuv = await this.orm.searchRead('ir.ui.view', [['name', '=', 'omux.config.base']], ['id']);
        this.lmisProps = {
            type: 'list',
            resModel: 'ir.asset',
            display: { controlPanel: false },
            domain: [
                ['name', 'ilike', '[OMUX]'],
                ['name', 'not ilike', '/%/'],
                ['name', 'not ilike', '[OMUX]%Font:%'],
                ['name', 'not ilike', '[OMUX]%Size:%'],
                ['name', 'not ilike', '[OMUX] Border Radius:%'],
                ['name', 'not ilike', '[OMUX] List Density:%'],
                ['name', 'not ilike', '[OMUX] Form Density:%'],
                ['name', 'not ilike', '[OMUX] Input Style:%'],
                ['name', 'not ilike', '[OMUX] Backend: Island%'],
                ['name', 'not ilike', '[OMUX] Remove Light in Dark%'],
                '|',
                ['active', '=', true],
                ['active', '=', false],
            ],
            allowSelectors: false,
            viewId: cuv[0].id,
            className: 'thoem',
        }
    }

    onAdvMouseDown(ev) {
        if (ev.target.closest('.o_field_boolean_toggle')) {
            this.hasAdvChanged = true;
        }
    }

    iniPickr(cl, ref) {
        const pickr = Pickr.create({
            el: this[ref].el,
            theme: 'classic',
            default: this.state[cl],
            position: 'top-end',
            useAsButton: true,
            padding: 10,

            swatches: OM.swatches,

            components: {

                // Main components
                preview: true,
                opacity: true,
                hue: true,

                // Input / output Options
                interaction: {
                    hex: true,
                    rgba: true,
                    hsla: true,
                    input: true,
                    save: true,
                }
            }
        });
        pickr.on('save', (color, instance) => {
            instance.hide();
            this.state[cl] = color.toHEXA().toString();
        });
        this._pickrs.push(pickr);
    }

    switchTab(ev) {
        if (this.hasGroupOmux && !this._pickrs) {
            this._pickrs = [];
            for (const cl in OM.system_scheme) {
                this.iniPickr(cl, `cp_${cl}`);
                this.iniPickr(`dark_${cl}`, `cp_dark_${cl}`);
            }
        }
        this.state.ctab = ev.target.dataset.tab;
    }

    onUoOptionChanged(key, val) {
        this.uo[key] = val;
    }

    onUiSize(size) {
        if (odoo.sett_uisize !== size) {
            if (size === 0) {
                delete odoo.sett_uisize;
                this.ui.size = utils.getSize();
            } else {
                odoo.sett_uisize = size;
                this.ui.size = size;

                document.body.classList.add('uup');
            }
            // Local saver
            this.ue.sett_uisize = size;
        }
    }

    triggerTopbar(value) {
        this.ui.bus.trigger('OMUX:TOPBAR', !value);
    }

    async assetActiv(basePath, targetPath, exPatern = false) {
        const assetModel = 'ir.asset';
        const dom = [['path', 'ilike', basePath]];
        if (exPatern) {
            dom.push(['path', 'not ilike', basePath + exPatern]);
        }

        // Disable all records matching the basePath
        let allRecords = await this.orm.searchRead(assetModel, dom, ['id']);
        await this.orm.write(assetModel, allRecords.map(o => o.id), { active: false });

        // Enable the records corresponding to the stateValue
        if (targetPath) {
            let targetRecords = await this.orm.searchRead(
                assetModel,
                [['path', 'ilike', targetPath]],
                ['id'],
                { context: { active_test: false } }
            );
            await this.orm.write(assetModel, targetRecords.map(o => o.id), { active: true });
        }

        // Reload assets
        this.ui.block();
    }

    openCompanySett() {
        if (!this.user.isSystem) {
            return this.env.services.notification.add(_t('Contact the administrator for access.'), { title: _t('Notification'), type: 'warning' });
        }
        this.action.doAction({
            name: _t('Company Branding'),
            type: 'ir.actions.act_window',
            res_model: 'res.company',
            res_id: this.ui.cpyId(),
            views: [[false, 'form']],
            target: 'new',
        });

        setTimeout(() => {
            document.querySelector('.modal-body.o_act_window div[name="logo_dui"]')?.scrollIntoView({
                behavior: 'smooth'
            });
        }, 320);
    }

    openAppMenuManager() {
        this.env.dialogData.close();
        this.action.doAction('udoo_om_ux.action_edit_menu');
    }

    clearBookmarks() {
        return new Promise((resolve) => {
            const confirm = async () => {
                this.ui.bookmarks = [];
                await user.setUserSettings('up_bookmarks', '[]');
                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    clearRecents() {
        return new Promise((resolve) => {
            const confirm = async () => {
                this.ue.recents = [];
                this.uo.recents = [];
                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    resetHomeAction() {
        return new Promise((resolve) => {
            const confirm = async () => {
                await user.setUserSettings('ps_start_xmlid', null);

                this.env.services.notification.add(
                    _t('Your home menu action has been restored.'),
                    {
                        title: _t('Notification'),
                        type: 'success',
                    }
                );

                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    resetHomeLayout() {
        return new Promise((resolve) => {
            const confirm = async () => {
                await user.setUserSettings('ps_menu_orders', null);
                await user.setUserSettings('ps_fav_menus', null);
                this.uo.fav_menus = [];

                this.env.services.notification.add(
                    _t('Your home menu layout has been restored.'),
                    {
                        title: _t('Notification'),
                        type: 'success',
                    }
                );

                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    async confirm() {
        if (this.state.color_shade !== this.o_color_shade) {
            cookie.set('color_shade', this.state.color_shade);
            this.ui.block();
        }

        // User
        if (this.uo.ps_auto_hmenu !== this.o_ps_auto_hmenu) {
            await user.setUserSettings('ps_auto_hmenu', this.uo.ps_auto_hmenu ? 'on' : 'off');
            this.ui.unblock();
        }
        if (this.uo.ps_full_iland !== this.o_ps_full_iland) {
            await user.setUserSettings('ps_full_iland', this.uo.ps_full_iland ? 'on' : 'off');
            this.ui.unblock();
        }

        // System
        if (this.hasGroupOmux) {
            if (this.g_ips !== this.state.g_ips) {
                await this.assetActiv('omux_input_style', `omux_input_style/static/src/${this.state.g_ips}`, '/static/src/dsfs/');
            }
            if (this.g_dsf !== this.state.g_dsf) {
                await this.assetActiv('omux_input_style/static/src/dsfs/', `omux_input_style/static/src/dsfs/${this.state.g_dsf}`);
            }
            if (this.g_brd !== this.state.g_brd) {
                await this.assetActiv('omux_border_radius', `omux_border_radius/${this.state.g_brd}`);
            }
            if (this.g_dsy !== this.state.g_dsy) {
                await this.assetActiv('omux_list_density', `omux_list_density/static/src/${this.state.g_dsy}`);
            }
            if (this.g_wbg !== this.state.g_wbg) {
                await this.assetActiv('feature/island_bg', this.state.g_wbg && 'feature/island_bg');
            }
            if (this.g_snbg !== this.state.g_snbg) {
                await this.assetActiv('feature/sidenav_bg', this.state.g_snbg && 'feature/sidenav_bg');
                if (this.state.g_snbg && this.state[`sidenav_bg`].startsWith('#FFF')) {
                    this.state[`sidenav_bg`] = '#071437';
                    this.state[`sidenav_text`] = '#FFF';
                    this.state[`sidenav_sub`] = '#D9F4F7';
                }
            }

            const lightDict = {};
            const darkDict = {};

            for (const [cl, info] of Object.entries(OM.system_scheme)) {

                if (this[`o_${cl}`] !== this.state[cl]) {
                    lightDict[cl] = [info.pam, this.state[cl]];
                }
                if (this[`o_dark_${cl}`] !== this.state[`dark_${cl}`]) {
                    darkDict[cl] = [info.pam, this.state[`dark_${cl}`]];
                }
            }

            if (Object.keys(lightDict).length || Object.keys(darkDict).length) {
                this.ui.block();
                try {
                    if (Object.keys(lightDict).length)
                        await this.orm.call('web_editor.assets', 'repr_omux_scheme', [lightDict]);
                    if (Object.keys(darkDict).length)
                        await this.orm.call('web_editor.assets', 'repr_omux_scheme', [darkDict, true]);
                } catch (error) {
                    console.error('Error saving SCSS changes:', error);
                }
            }

            let isNewFont = this.g_fty !== this.state.g_fty;
            let isNewFontSize = this.g_ftz !== this.state.g_ftz;
            if (isNewFont || isNewFontSize) {
                const params = {};
                if (isNewFont) {
                    params.fk = this.state.g_fty;
                }
                if (isNewFontSize) {
                    params.fs = this.state.g_ftz;
                }
                await this.orm.call('web_editor.assets', 'repr_omux_font', [params]);
                this.ui.block();
            }
        }

        if (this.hasAdvChanged) {
            this.ui.block();
        }

        if (this.ui.isBlocked) {
            browser.location.reload();
        } else {
            this.env.dialogData.close();
        }
    }

    async reset() {
        this.ui.block();
        const pattern = Object.entries(OM.system_scheme).map(([k, o]) => o.pam).join('|');
        await this.orm.call('web_editor.assets', 'reset_omux_light', [pattern]);
        await this.orm.call('web_editor.assets', 'reset_omux_dark', [pattern]);
        this.state.g_snbg = false;
        await this.confirm();
    }
}

registry.category('lazy_components').add('OmuxConf', OmuxConf);