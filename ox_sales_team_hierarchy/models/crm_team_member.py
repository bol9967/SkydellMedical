# -*- coding: utf-8 -*-

from odoo import api, models


class CrmTeamMember(models.Model):
    _inherit = 'crm.team.member'

    def write(self, vals):
        """When team membership changes, recompute team_member_user_ids for the leader"""
        result = super().write(vals)
        if 'user_id' in vals or 'crm_team_id' in vals or 'active' in vals:
            # Recompute for both old and new team leaders
            old_leaders = self._origin.mapped('crm_team_id.user_id')
            new_leaders = self.mapped('crm_team_id.user_id')
            leaders = old_leaders | new_leaders
            if leaders:
                leaders._compute_team_member_user_ids()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """When a team member is created, recompute team_member_user_ids for the leader"""
        members = super().create(vals_list)
        leaders = members.mapped('crm_team_id.user_id')
        if leaders:
            leaders._compute_team_member_user_ids()
        return members

    def unlink(self):
        """When a team member is deleted, recompute team_member_user_ids for the leader"""
        leaders = self.mapped('crm_team_id.user_id')
        result = super().unlink()
        if leaders:
            leaders._compute_team_member_user_ids()
        return result
