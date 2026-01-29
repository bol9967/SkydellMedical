# -*- coding: utf-8 -*-

from . import models


def post_init_hook(env):
    """Ensure all Team Leaders have the salesperson group directly assigned"""
    team_leader_group = env.ref('ox_sales_team_hierarchy.group_team_leader', raise_if_not_found=False)
    salesperson_group = env.ref('sales_team.group_sale_salesman', raise_if_not_found=False)
    
    if team_leader_group and salesperson_group:
        # Find all users with Team Leader group
        team_leaders = env['res.users'].search([('groups_id', 'in', [team_leader_group.id])])
        for user in team_leaders:
            if salesperson_group.id not in user.groups_id.ids:
                user.sudo().write({'groups_id': [(4, salesperson_group.id)]})
