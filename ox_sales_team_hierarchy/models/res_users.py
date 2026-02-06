# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    team_member_user_ids = fields.Many2many(
        'res.users',
        'res_users_team_member_rel',
        'leader_id',
        'member_id',
        string='Team Member User IDs',
        compute='_compute_team_member_user_ids',
        store=False,
        help='Users who are members of teams where this user is the leader'
    )
    
    team_member_user_ids_list = fields.Char(
        string='Team Member User IDs (for domain)',
        compute='_compute_team_member_user_ids_list',
        store=True,
        help='Comma-separated list of user IDs for use in record rule domains'
    )

    @api.depends()
    def _compute_team_member_user_ids(self):
        """Compute the user IDs of all team members for teams where this user is the leader"""
        for user in self:
            # Find all teams where this user is the leader (user_id field on crm.team)
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            # Get all active member user IDs from those teams
            member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
            user.team_member_user_ids = member_user_ids

    @api.depends()
    def _compute_team_member_user_ids_list(self):
        """Store team member user IDs as comma-separated string for record rules"""
        for user in self:
            # Find all teams where this user is the leader
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            # Get all active member user IDs from those teams
            member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
            if member_user_ids:
                # Store as comma-separated string: "1,2,3" or empty string
                user.team_member_user_ids_list = ','.join(str(uid) for uid in member_user_ids.ids)
            else:
                user.team_member_user_ids_list = ''
    
    def _get_team_member_user_ids_for_domain(self):
        """Get team member user IDs as a list for use in domains"""
        self.ensure_one()
        if self.team_member_user_ids_list:
            return [int(uid) for uid in self.team_member_user_ids_list.split(',') if uid.strip()]
        return []
    
    # Boolean field for Team Leader group (appears in Access Rights tab)
    # This field syncs with the Team Leader security group
    is_team_leader = fields.Boolean(
        string='Team Leader',
        compute='_compute_is_team_leader',
        inverse='_inverse_is_team_leader',
        store=False,
        help='Allow this user to view records of their team members'
    )
    
    @api.depends('groups_id')
    def _compute_is_team_leader(self):
        """Compute if user is in Team Leader group"""
        # Get group ID from XML ID
        group_data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'ox_sales_team_hierarchy'),
            ('name', '=', 'group_team_leader'),
            ('model', '=', 'res.groups')
        ], limit=1)
        
        if not group_data:
            # Group not found yet (during installation)
            self.is_team_leader = False
            return
        
        team_leader_group_id = group_data.res_id
        
        for user in self:
            user.is_team_leader = team_leader_group_id in user.groups_id.ids
    
    def _inverse_is_team_leader(self):
        """Update group membership when boolean is changed"""
        # Get group ID from XML ID
        group_data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'ox_sales_team_hierarchy'),
            ('name', '=', 'group_team_leader'),
            ('model', '=', 'res.groups')
        ], limit=1)
        
        if not group_data:
            return  # Group not found, can't update
        
        team_leader_group_id = group_data.res_id
        
        for user in self:
            if user.is_team_leader:
                if team_leader_group_id not in user.groups_id.ids:
                    user.groups_id = [(4, team_leader_group_id)]
            else:
                if team_leader_group_id in user.groups_id.ids:
                    user.groups_id = [(3, team_leader_group_id)]
