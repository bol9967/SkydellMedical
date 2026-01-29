# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Lavend Backend (Community Edition)',
    'category': 'Themes/Backend',
    'summary': 'Premium Odoo Backend with modern layout, dual sidebar, app categorization, list view manager, advanced data filter, theme editor, theme designer, pixel-accurate list view, remember resized column width, refined Kanban, dynamic form sizing, flexible chatter, batch creation, RTL & multilingual, fullscreen toggle, prebuilt theme presets, advanced color editor, mobile responsive, drag-drop menu, fast global search, user wise menu sorting, WCAG 2.2 support, smart refresher, recent drawer, dark/light mode, Google Fonts, vibrant contrast.',
    'version': '1.3.1',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'live_test_url': 'https://lavend.sveltware.com/web/login',
    'support': 'jupetern24@gmail.com',
    'sequence': 776,
    'images': [
        'static/description/banner.png',
        'static/description/theme_screenshot.png',
    ],
    'depends': [
        'udoo_om_ux',
        'svn_filter_base',
        'omux_color_scheme',
    ],
    'excludes': [
        'omux_data_filter',
        'omux_list_controller',
        'udoo_web_filter_bar',
        'udoo_web_list_view',
        'udoo_om_ux_filter_bar',
    ],
    'data': [
        'data/asset_data.xml',
        'security/ir.model.access.csv',
        'security/res_groups.xml',
        'views/ir_ui_menu.xml',
    ],
    'assets': {
        'omux_filter_navbar': [
            (
                'before',
                'web/static/src/views/list/list_renderer.js',
                'udoo_lavend_ux/static/src/cmfb/editor/*',
            ),
            (
                'after',
                'web/static/src/views/list/list_renderer.js',
                'udoo_lavend_ux/static/src/cmfb/patch/list_renderer.js',
            ),
            (
                'after',
                'web/static/src/views/form/form_controller.js',
                'udoo_lavend_ux/static/src/cmfb/patch/form_controller.js',
            ),
            (
                'after',
                'web/static/src/model/relational_model/dynamic_list.js',
                'udoo_lavend_ux/static/src/cmfb/patch/model/dynamic_list.js',
            ),
            (
                'after',
                'web/static/src/model/relational_model/static_list.js',
                'udoo_lavend_ux/static/src/cmfb/patch/model/static_list.js',
            ),
            (
                'after',
                'web/static/src/search/search_model.js',
                'udoo_lavend_ux/static/src/cmfb/patch/search/search_model.js',
            ),
            (
                'after',
                'web/static/src/search/search_bar/search_bar.xml',
                'udoo_lavend_ux/static/src/cmfb/search/search_bar.xml',
            ),
            (
                'after',
                'web/static/src/search/search_bar/search_bar.xml',
                'udoo_lavend_ux/static/src/cmfb/search/search_bar.js',
            ),
            (
                'after',
                'web/static/src/views/list/list_renderer.xml',
                'udoo_lavend_ux/static/src/cmfb/patch/list_renderer.xml',
            ),
            (
                'after',
                'omux_view_action/static/src/control_panel.xml',
                'udoo_lavend_ux/static/src/cmfb/search/control_panel.js',
            ),
            (
                'after',
                'omux_view_action/static/src/control_panel.xml',
                'udoo_lavend_ux/static/src/cmfb/search/control_panel.xml',
            ),
            'udoo_lavend_ux/static/src/cmfb/list_renderer.scss',
        ],
        'omux_list_controler': [
            (
                'after',
                'web/static/src/views/list/list_renderer.xml',
                'udoo_lavend_ux/static/src/cman/list/renderer.xml',
            ),
            (
                'after',
                'web/static/src/views/list/list_controller.xml',
                'udoo_lavend_ux/static/src/cman/list/controller.xml',
            ),
            'udoo_lavend_ux/static/src/cman/list/controller.js',
            'udoo_lavend_ux/static/src/cman/list/renderer.js',
            'udoo_lavend_ux/static/src/cman/list/controller.scss',
        ],
        'omux_list_controler.mod': [
            'udoo_lavend_ux/static/src/cman/mod/*.js',
            'udoo_lavend_ux/static/src/cman/mod/*.xml',
            'udoo_lavend_ux/static/src/cman/mod/*.scss',
        ],
        'omux_list_colwidth': [
            (
                'after',
                'web/static/src/views/list/list_renderer.xml',
                'udoo_lavend_ux/static/src/olcm/list_renderer.xml',
            ),
            'udoo_lavend_ux/static/src/olcm/*.js',
            'udoo_lavend_ux/static/src/olcm/*.scss',
        ],
        'web._assets_primary_variables': {
            (
                'after',
                'udoo_om_ux/static/src/scss/primary_variables.scss',
                'udoo_lavend_ux/static/src/**/*.variables.scss',
            ),
            (
                'before',
                'udoo_om_ux/static/src/scss/primary_variables.scss',
                'udoo_lavend_ux/static/src/scss/primary_variables.scss',
            ),
        },
        'web.assets_backend': [
            'udoo_lavend_ux/static/src/views/list/list_controller.scss',
            'udoo_lavend_ux/static/src/views/list/list_renderer.xml',
            'udoo_lavend_ux/static/src/scss/style_backend.scss',
            'udoo_lavend_ux/static/src/webclient/navbar/*',
            ('include', 'omux_filter_navbar'),
            ('include', 'omux_list_controler'),
            ('include', 'omux_list_colwidth'),
        ],
        'web.dark_mode_variables': [
            (
                'before',
                'udoo_lavend_ux/static/src/scss/primary_variables.scss',
                'udoo_lavend_ux/static/src/scss/primary_variables_dark.scss',
            ),
            (
                'before',
                'udoo_lavend_ux/static/src/**/*.variables.scss',
                'udoo_lavend_ux/static/src/**/*.variables.dark.scss',
            ),
        ],
        'web.assets_web_dark': [
            'udoo_lavend_ux/static/src/**/*.dark.scss',
            'udoo_lavend_ux/static/src/scss/style_backend_dark.scss',
        ],
        'omux.conf': [
            'udoo_lavend_ux/static/src/conf/*.js',
            'udoo_lavend_ux/static/src/conf/*.xml',
        ],
    },
    'price': 194,
    'currency': 'EUR',
}
