# -*- coding: utf-8 -*-

from odoo import api, models


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    def write(self, vals):
        """When team leader or members change, recompute team_member_user_ids for the leader"""
        result = super().write(vals)
        if 'user_id' in vals or 'crm_team_member_ids' in vals:
            # Recompute team_member_user_ids for affected leaders
            leaders = self.mapped('user_id') | self._origin.mapped('user_id')
            if leaders:
                leaders._compute_team_member_user_ids()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """When a team is created, recompute team_member_user_ids for the leader"""
        teams = super().create(vals_list)
        leaders = teams.mapped('user_id')
        if leaders:
            leaders._compute_team_member_user_ids()
        return teams
