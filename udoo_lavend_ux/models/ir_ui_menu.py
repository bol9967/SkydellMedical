# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import api, fields, models, tools


class IrUiMenuGroup(models.Model):
    _name = 'ir.ui.menu.group'
    _description = 'Menu Group'
    _order = 'sequence, name'

    name = fields.Char(string='Group Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description', translate=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one('res.company', string='Company')

    items = fields.Many2many(
        comodel_name='ir.ui.menu',
        relation='ir_ui_menu_group_menu_rel',
        column1='group_id',
        column2='menu_id',
        domain=[('parent_id', '=', False)],
    )

    @api.model
    @tools.ormcache('self.env.company.id')
    def omux_data(self):
        return self.sudo().search_read(
            [
                ('active', '=', True),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.env.company.id),
            ],
            ['name', 'items'],
        )

    @api.model_create_multi
    def create(self, vals_list):
        self.env.registry.clear_cache()  # omux_data
        return super(IrUiMenuGroup, self).create(vals_list)

    def write(self, vals):
        self.env.registry.clear_cache()  # omux_data
        return super(IrUiMenuGroup, self).write(vals)

    def unlink(self):
        self.env.registry.clear_cache()  # omux_data
        return super(IrUiMenuGroup, self).unlink()
