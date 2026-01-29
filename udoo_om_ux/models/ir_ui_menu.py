# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import fields, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    bk_web_icon = fields.Char(readonly=True)

    ex_users = fields.Many2many(
        'res.users',
        'ir_ui_menu_ex_users_rel',
        'menu_id',
        'user_id',
        string='Excluded Users',
        help='Users listed here will not see this menu, regardless of group settings.',
    )

    def u_open_detail(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ir.ui.menu',
            'view_mode': 'form',
            'res_id': self.id,
            'views': [[self.env.ref('udoo_om_ux.om_edit_menu_form').id, 'form']],
        }

    def u_reset_icon(self):
        for rec in self:
            if rec.bk_web_icon:
                rec.write({'web_icon': rec.bk_web_icon, 'bk_web_icon': False})

    # -------------------------------------------------------------------------
    # LOW-LEVEL METHODS
    # -------------------------------------------------------------------------

    def _visible_menu_ids(self, debug=False):
        Menu = self.with_context(active_test=False).sudo()

        visible_ids = super()._visible_menu_ids(debug)
        return visible_ids - set(Menu._search([('ex_users', 'in', self.env.uid)]))

    def write(self, values):
        if 'web_icon' in values and 'bk_web_icon' not in values:
            for rec in self:
                if rec.web_icon and not rec.bk_web_icon:
                    rec.bk_web_icon = rec.web_icon
        return super().write(values)
