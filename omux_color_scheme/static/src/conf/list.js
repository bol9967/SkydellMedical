import { _t } from '@web/core/l10n/translation';
import { browser } from '@web/core/browser/browser';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { Dialog } from '@web/core/dialog/dialog';
import { Component, onWillStart, useState } from '@odoo/owl';

export const assetDefinitions = {
    'preset_list': {
        metronic: {
            name: 'Metronic',
            description: _t('A professional palette inspired by Metronic design, featuring vibrant, high-contrast styling.'),
            grayscale: ['#F9F9F9', '#EBEBEF', '#DBDFE9', '#C4CADA', '#99A1B7', '#78829D', '#4A5573', '#252F4A'],
        },
        slate: {
            name: 'Slate',
            description: _t('A modern, dark-blue theme with subtle slate tones, providing an elegant, sophisticated look.'),
            grayscale: ['#F1F5F9', '#E2E8F0', '#CBD5E1', '#94A3B8', '#64748B', '#475569', '#334155', '#1E293B'],
        },
        haze: {
            name: 'Haze',
            description: _t('A subtle haze gray palette with smooth transitions, offering a clean and neutral interface.'),
            grayscale: ['#F3F4F6', '#E5E7EB', '#D1D5DB', '#9CA3AF', '#6B7280', '#4B5563', '#374151', '#1F2937'],
        },
        gray: {
            name: 'Gray',
            description: _t('A pure gray palette offering a balanced range from light to dark for a clean, neutral interface.'),
            grayscale: ['#FAFAFA', '#EDEDED', '#DEDEDE', '#B8B8B8', '#787878', '#606060', '#484848', '#2A2A2A'],
        },
        neutral: {
            name: 'Neutral',
            description: _t('A minimalist, low-contrast palette well-suited for sleek, understated interfaces and branding.'),
            grayscale: ['#F5F5F5', '#E5E5E5', '#D4D4D4', '#A3A3A3', '#737373', '#525252', '#404040', '#262626'],
        },
        sage: {
            name: 'Sage',
            description: _t('A calming, nature-inspired palette with soft green-gray tones that evoke tranquility and balance.'),
            grayscale: ['#F7F9F8', '#E6E9E8', '#D7DAD9', '#B8BCBA', '#7C8481', '#555F5C', '#444947', '#272A29'],
        },
        zinc: {
            name: 'Zinc',
            description: _t('A balanced gray scheme offering moderate contrast, perfect for crisp, refined interfaces.'),
            grayscale: ['#F4F4F5', '#E4E4E7', '#D4D4D8', '#A1A1AA', '#71717A', '#52525B', '#3F3F46', '#27272A'],
        },
        mauve: {
            name: 'Mauve',
            description: _t('A refined mauve palette with soft purple undertones and subtle gray contrasts for a vintage look.'),
            grayscale: ['#FAF9FB', '#EAE7EC', '#DBD8E0', '#BCBAC7', '#7C7A85', '#625F69', '#49474E', '#2B292D'],
        },
    },
    'ocoo_om_ux': {
        metronic: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                ],
                [
                    'before',
                    'ocoo_om_ux/static/src/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                ],
            ],
            'web._assets_backend_helpers': [
                [
                    'before',
                    'ocoo_om_ux/static/src/scss/bs_backend_overridden.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden.scss',
                ],
            ],
            'web.assets_backend': [
                'omux_color_scheme/static/set/web_metronic/scss/style_backend.scss',
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.dark.scss',
                ],
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables_dark.scss',
                ],
            ],
            'web.assets_web_dark': [
                [
                    'before',
                    'ocoo_om_ux/static/src/scss/bs_backend_overridden_dark.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden_dark.scss',
                ],
                'omux_color_scheme/static/set/web_metronic/**/*.dark.scss',
            ],
        },
        neutral: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss'
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables_dark.scss',
                ],
            ],
        },
        slate: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_slate/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables_dark.scss',
                ],
            ],
        },
        haze: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_haze/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables_dark.scss',
                ],
            ],
        },
        gray: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_gray/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables_dark.scss',
                ],
            ],
        },
        mauve: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables_dark.scss',
                ],
            ],
        },
        sage: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_sage/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables_dark.scss',
                ],
            ],
        },
        zinc: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'ocoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables_dark.scss',
                ],
            ],
        }
    },
    'udoo_om_ux': {
        metronic: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                ],
                [
                    'before',
                    'udoo_om_ux/static/src/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                ],
            ],
            'web._assets_backend_helpers': [
                [
                    'before',
                    'udoo_om_ux/static/src/scss/bs_backend_overridden.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden.scss',
                ],
            ],
            'web.assets_backend': [
                'omux_color_scheme/static/set/web_metronic/scss/style_backend.scss',
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.dark.scss',
                ],
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables_dark.scss',
                ],
            ],
            'web.assets_web_dark': [
                [
                    'before',
                    'udoo_om_ux/static/src/scss/bs_backend_overridden_dark.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden_dark.scss',
                ],
                'omux_color_scheme/static/set/web_metronic/**/*.dark.scss',
            ],
        },
        neutral: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss'
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables_dark.scss',
                ],
            ],
        },
        slate: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_slate/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables_dark.scss',
                ],
            ],
        },
        haze: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_haze/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables_dark.scss',
                ],
            ],
        },
        gray: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_gray/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables_dark.scss',
                ],
            ],
        },
        mauve: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables_dark.scss',
                ],
            ],
        },
        sage: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_sage/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables_dark.scss',
                ],
            ],
        },
        zinc: {
            'web._assets_primary_variables': [
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/patch/primary_variables.scss',
                ],
                [
                    'after',
                    'udoo_om_ux/static/src/scss/style_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables_dark.scss',
                ],
            ],
        }
    },
    'web_enterprise': {
        metronic: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                ],
                [
                    'before',
                    'web_enterprise/static/src/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                ],
            ],
            'web._assets_backend_helpers': [
                [
                    'before',
                    'web_enterprise/static/src/scss/bootstrap_overridden.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden.scss',
                ],
            ],
            'web.assets_backend': [
                'omux_color_scheme/static/set/web_metronic/scss/style_backend.scss',
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.dark.scss',
                ],
                [
                    'before',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables_dark.scss',
                ],
            ],
            'web.assets_web_dark': [
                [
                    'before',
                    'web_enterprise/static/src/scss/bootstrap_overridden.dark.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden_dark.scss',
                ],
                'omux_color_scheme/static/set/web_metronic/**/*.dark.scss',
            ],
        },
        neutral: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss'
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables_dark.scss',
                ],
            ],
        },
        slate: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables_dark.scss',
                ],
            ],
        },
        haze: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables_dark.scss',
                ],
            ],
        },
        gray: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables_dark.scss',
                ],
            ],
        },
        mauve: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables_dark.scss',
                ],
            ],
        },
        sage: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables_dark.scss',
                ],
            ],
        },
        zinc: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web_enterprise/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                ],
            ],
            'web.dark_mode_variables': [
                [
                    'before',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables_dark.scss',
                ],
            ],
        }
    },
    'web': {
        metronic: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/primary_variables.scss',
                ],
                [
                    'before',
                    'web/static/src/**/*.variables.scss',
                    'omux_color_scheme/static/set/web_metronic/**/*.variables.scss',
                ],
            ],
            'web._assets_backend_helpers': [
                [
                    'before',
                    'web/static/src/scss/bootstrap_overridden.scss',
                    'omux_color_scheme/static/set/web_metronic/scss/bs_backend_overridden.scss',
                ],
            ],
            'web.assets_backend': [
                'omux_color_scheme/static/set/web_metronic/scss/style_backend.scss',
            ],
        },
        neutral: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_neutral/scss/primary_variables.scss'
                ],
            ],
        },
        slate: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_slate/scss/primary_variables.scss',
                ],
            ],
        },
        haze: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_haze/scss/primary_variables.scss',
                ],
            ],
        },
        gray: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_gray/scss/primary_variables.scss',
                ],
            ],
        },
        mauve: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_mauve/scss/primary_variables.scss',
                ],
            ],
        },
        sage: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_sage/scss/primary_variables.scss',
                ],
            ],
        },
        zinc: {
            'web._assets_primary_variables': [
                [
                    'before',
                    'web/static/src/scss/primary_variables.scss',
                    'omux_color_scheme/static/set/web_zinc/scss/primary_variables.scss',
                ],
            ],
        }
    },
}

export class ColorPaletteConfig extends Component {
    static template = 'wub.ColorPaletteConfig';
    static components = { Dialog };
    static props = { '*': true };

    setup() {
        this.presets = assetDefinitions.preset_list;
        this.orm = useService('orm');
        this.state = useState({ preset: null });

        onWillStart(async () => {
        });
    }

    async reset(silent = false) {
        const toRemove = await this.orm.searchRead(
            'ir.asset',
            [['path', 'ilike', 'omux_color_scheme/static/set']],
            ['id'],
        );
        const ids = toRemove.map(rec => rec.id);
        if (ids.length) {
            await this.orm.unlink('ir.asset', ids);
        }
        if (!silent) {
            browser.location.reload();
        }
    }

    async apply() {
        const omuxNames = ['ocoo_om_ux', 'web_enterprise', 'udoo_om_ux', 'web'];
        const moduleState = await this.orm.searchRead(
            'ir.module.module',
            [['name', 'in', omuxNames]],
            ['name', 'state'],
        );
        for (const mod of omuxNames) {
            if (moduleState.some((o) => o.name == mod && o.state == 'installed')) {
                this.reset(true);
                await this.genStyleAssets(assetDefinitions[mod]);
                break;
            }
        }
        // Finally, reload to apply changes
        browser.location.reload();
    }

    async genStyleAssets(def) {
        const preset = this.state.preset;
        const presetDict = def[preset];

        for (const [clast, entries] of Object.entries(presetDict)) {
            // assetEntries could be a list of strings or [directive, base.scss, new.scss]
            for (const entry of entries) {
                if (typeof entry === 'string') {
                    // If it's just a string, it likely means "append that SCSS to the bundle"
                    const data = {
                        name: `[OMUX] ${entry}`,
                        bundle: clast,
                        path: entry,
                        sequence: 98,
                        active: true,
                    };
                    await this.orm.create('ir.asset', [data]);
                } else if (Array.isArray(entry)) {
                    // Format: [ 'before' | 'after', 'basePath.scss', 'myCustom.scss' ]
                    const [position, basePath, scssPath] = entry;
                    const data = {
                        name: `[OMUX] ${scssPath}`,
                        bundle: clast,
                        path: scssPath,
                        directive: position,
                        target: basePath,
                        sequence: 98,
                        active: true,
                    };
                    await this.orm.create('ir.asset', [data]);
                }
            }
        }
    }
}

registry.category('lazy_components').add('ColorPaletteConfig', ColorPaletteConfig);