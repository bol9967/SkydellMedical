# -*- coding: utf-8 -*-

from odoo import models, api

_logger = models.logging.getLogger(__name__)


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    def write(self, vals):
        """Trigger recomputation of team_member_user_ids when team structure changes"""
        result = super().write(vals)
        if 'user_id' in vals or 'crm_team_member_ids' in vals:
            # Invalidate team_member_user_ids for the team leader
            if self.user_id:
                self.env['res.users'].browse(self.user_id.id).invalidate_recordset(['team_member_user_ids'])
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Trigger recomputation when new team is created"""
        teams = super().create(vals_list)
        for team in teams:
            if team.user_id:
                self.env['res.users'].browse(team.user_id.id).invalidate_recordset(['team_member_user_ids'])
        return teams
