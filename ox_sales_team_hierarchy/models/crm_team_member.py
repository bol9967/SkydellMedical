# -*- coding: utf-8 -*-

from odoo import models, api

_logger = models.logging.getLogger(__name__)


class CrmTeamMember(models.Model):
    _inherit = 'crm.team.member'

    def write(self, vals):
        """Trigger recomputation of team_member_user_ids when team membership changes"""
        result = super().write(vals)
        if 'user_id' in vals or 'active' in vals or 'crm_team_id' in vals:
            # Invalidate team_member_user_ids for affected team leaders
            for member in self:
                if member.crm_team_id and member.crm_team_id.user_id:
                    self.env['res.users'].browse(member.crm_team_id.user_id.id).invalidate_recordset(['team_member_user_ids'])
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Trigger recomputation when new team member is created"""
        members = super().create(vals_list)
        for member in members:
            if member.crm_team_id and member.crm_team_id.user_id:
                self.env['res.users'].browse(member.crm_team_id.user_id.id).invalidate_recordset(['team_member_user_ids'])
        return members

    def unlink(self):
        """Trigger recomputation when team member is removed"""
        team_leaders = self.mapped('crm_team_id.user_id')
        result = super().unlink()
        for leader in team_leaders:
            if leader:
                self.env['res.users'].browse(leader.id).invalidate_recordset(['team_member_user_ids'])
        return result
