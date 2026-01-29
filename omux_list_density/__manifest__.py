# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux List Density',
    'category': 'Hidden',
    'version': '1.0.0',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'data': [
        'data/asset_data.xml',
    ],
    'assets': {
            'web._assets_backend_helpers': [
            (
                'before',
                'web/static/src/scss/bootstrap_overridden.scss',
                'omux_list_density/static/src/bs_backend_overridden.scss',
            ),
        ],
    }
}
