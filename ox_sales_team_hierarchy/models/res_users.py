# -*- coding: utf-8 -*-

from odoo import api, fields, models

_logger = models.logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    team_member_user_ids = fields.Many2many(
        'res.users',
        string='Team Member Users',
        compute='_compute_team_member_user_ids',
        store=False,  # Not stored - computed on demand
        help='Users who are members of teams led by this user'
    )

    @api.depends()
    def _compute_team_member_user_ids(self):
        """Compute team member user IDs for this user (if they are a team leader)"""
        for user in self:
            if not user.id:
                user.team_member_user_ids = False
                continue
            
            # Find teams where this user is the leader
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            if teams:
                # Get all active team members from all teams
                member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
                # Filter out None/False values
                user.team_member_user_ids = member_user_ids.filtered(lambda u: u and u.id)
            else:
                user.team_member_user_ids = False
