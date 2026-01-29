# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions


def uninstall_hook(env):
    assets = env['ir.asset'].search([('path', 'ilike', 'omux_color_scheme/static/set')])
    assets.unlink()
