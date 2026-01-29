# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux Color Scheme',
    'category': 'Hidden',
    'summary': 'Minimal color customization for Odoo backend UI. Customize your Odoo backend with soft, elegant background tones that give each user the ability to personalize their workspace without altering the layout or dark/light mode. Omux backend, lavend backend, colors, customize your odoo colors, backend ui, odoo theme customization, odoo branding, colors in the backend, custom css/less, custom color palette, background colors, metronic, dark mode.',
    'version': '1.0.1',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'images': [
        'static/description/banner.png',
    ],
    'depends': [
        'omux_config_base',
    ],
    'data': [
        'views/ir_module_views.xml',
    ],
    'uninstall_hook': 'uninstall_hook',
    'assets': {
        'web.assets_backend': [
            'omux_color_scheme/static/src/main/view.js',
        ],
        'omux_color_scheme.conf': [
            'omux_color_scheme/static/src/conf/**/*.js',
            'omux_color_scheme/static/src/conf/**/*.xml',
            'omux_color_scheme/static/src/conf/**/*.scss',
        ],
    },
}