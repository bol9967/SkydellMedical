# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import models


class ScssEditor(models.AbstractModel):
    _inherit = 'web_editor.assets'

    def _omux_asset_paths(self, dark):
        return [
            'udoo_lavend_ux/static/src/webclient/scheme/start_menu.variables.dark.scss'
            if dark
            else 'udoo_lavend_ux/static/src/webclient/scheme/start_menu.variables.scss',
            'udoo_lavend_ux/static/src/scss/primary_variables_dark.scss'
            if dark
            else 'udoo_lavend_ux/static/src/scss/primary_variables.scss',
            'udoo_om_ux/static/src/scss/primary_variables_dark.scss'
            if dark
            else 'udoo_om_ux/static/src/scss/primary_variables.scss',
            'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.dark.scss'
            if dark
            else 'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.scss',
            'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.scss',
        ]
