# -*- coding: utf-8 -*-

import logging
from odoo import api, models
from odoo.exceptions import AccessError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """
        Extend search to include team member records for team leaders (4th Tier)
        
        Native Odoo Hierarchy:
        1. Administrator - Bypasses all rules (self.env.su check in ir_rule.py)
        2. All Documents - Rule: [(1,'=',1)] (sees everything)
        3. Team Leader Access - Rule: Own + Team members (THIS - 4th tier)
        4. Own Documents Only - Rule: ['|',('user_id','=',user.id),('user_id','=',False)]
        
        This override extends the "Own Documents Only" domain to include team member records
        when the user is a team leader with team members.
        """
        # Check if we're being called from read_group context
        # If so, we should return a domain-based Query, not one from IDs (to avoid WITH ORDINALITY)
        is_read_group_context = self.env.context.get('_read_group_mode', False)
        
        # Also detect if domain already has extended pattern (OR with user_id conditions)
        # This happens when read_group calls _search with the extended domain
        # Pattern: ['|', '&', ..., ('user_id', '=', user.id), '&', ..., ('user_id', 'in', [...])]
        domain_has_extended_pattern = (
            isinstance(domain, list) and len(domain) > 0 and domain[0] == '|' and
            any(isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == 'user_id' and term[1] == 'in' 
                for term in domain if isinstance(term, (list, tuple)))
        )
        
        is_read_group_mode = is_read_group_context or domain_has_extended_pattern
        
        _logger.info(f"[sale.order._search] User {self.env.user.id} ({self.env.user.name}) - Domain: {domain}, read_group_mode: {is_read_group_mode}")
        
        # Check user groups for 4th tier (Team Leader Access)
        # IMPORTANT: When called from read_group with sudo(), self.env.user becomes superuser
        # We need to check the ORIGINAL user's permissions, not the sudo environment
        # Use self.env.uid to get the original user ID, or check context for uid
        original_uid = self.env.context.get('uid') or self.env.uid
        if original_uid and original_uid != self.env.user.id:
            # We're in a sudo environment, get the original user
            original_user = self.env['res.users'].browse(original_uid)
        else:
            original_user = self.env.user
        
        user = original_user
        is_salesman = user.has_group('sales_team.group_sale_salesman')
        has_all_leads = user.has_group('sales_team.group_sale_salesman_all_leads')
        is_team_leader = user.has_group('ox_sales_team_hierarchy.group_team_leader')
        
        _logger.info(f"[sale.order._search] Original user: {user.id} ({user.name}), env.user: {self.env.user.id}, env.su: {self.env.su}")
        _logger.info(f"[sale.order._search] User groups - Salesman: {is_salesman}, All Leads: {has_all_leads}, Team Leader: {is_team_leader}")
        
        # IMPORTANT: If ORIGINAL user has "All Documents" access, bypass our override
        # Note: We don't check self.env.su because when called from read_group with sudo(),
        # self.env.su will be True but we still want to apply our team leader logic
        if has_all_leads:
            _logger.info(f"[sale.order._search] Original user has 'All Documents' - using standard search")
            return super()._search(domain, offset=offset, limit=limit, order=order)
        
        # Team Leader Access logic (4th tier)
        # Only applies if: Salesman + NOT All Documents + IS Team Leader
        # This ensures hierarchy: Administrator > All Documents > Team Leader > Own Documents Only
        if (is_salesman and not has_all_leads and is_team_leader):
            # Check if user is a team leader
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            _logger.info(f"[sale.order._search] User is team leader of {len(teams)} teams: {teams.mapped('name')}")
            
            if teams:
                # Get team member user IDs - include all active members from all teams
                member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
                # Filter out False/None values and get IDs
                member_user_ids = member_user_ids.filtered(lambda u: u).ids
                _logger.info(f"[sale.order._search] Team member user IDs: {member_user_ids}")
                
                if member_user_ids:
                    # If in read_group context, extend domain and return domain-based Query
                    # This avoids the WITH ORDINALITY issue in aggregations
                    if is_read_group_mode:
                        # If domain already has extended pattern, use it as-is
                        # Otherwise, extend it
                        if domain_has_extended_pattern:
                            _logger.info(f"[sale.order._search] read_group mode: domain already extended, using as-is")
                            search_domain = domain
                        else:
                            extended_domain = expression.OR([
                                expression.AND([domain, [('user_id', '=', user.id)]]),  # Own records
                                expression.AND([domain, [('user_id', 'in', member_user_ids)]])  # Team member records
                            ])
                            _logger.info(f"[sale.order._search] read_group mode: extending domain")
                            search_domain = extended_domain
                        # Return domain-based search result (no WITH ORDINALITY)
                        return super(SaleOrder, self.sudo())._search(search_domain, offset=offset, limit=limit, order=order)
                    
                    # For regular search, combine IDs from two searches
                    own_query = super()._search(expression.AND([domain, [('user_id', '=', user.id)]]), offset=0, limit=0, order=False)
                    team_query = super(SaleOrder, self.sudo())._search(expression.AND([domain, [('user_id', 'in', member_user_ids)]]), offset=0, limit=0, order=False)
                    
                    own_ids = list(own_query) if own_query else []
                    team_ids = list(team_query) if team_query else []
                    result_ids = list(set(own_ids) | set(team_ids))
                    _logger.info(f"[sale.order._search] Found {len(own_ids)} own + {len(team_ids)} team member = {len(result_ids)} total records")
                    
                    # Return Query object - Odoo will handle offset, limit, and order
                    if result_ids:
                        return self.browse(result_ids)._as_query(order or self._order)
                    else:
                        return self.browse([])._as_query(order or self._order)
                # If no team members, use standard search (own records only)
                else:
                    _logger.info(f"[sale.order._search] No team members - using standard search (Own Documents Only)")
                    return super()._search(domain, offset=offset, limit=limit, order=order)
            else:
                # Not a team leader, use standard search
                return super()._search(domain, offset=offset, limit=limit, order=order)
        else:
            # Not a team leader or has "All Documents", use standard search
            return super()._search(domain, offset=offset, limit=limit, order=order)
        
        # This code should never be reached, but kept for safety
        # Return Query object - Odoo will handle offset, limit, and order
        return super()._search(domain, offset=offset, limit=limit, order=order)
    
    def read(self, fields=None, load='_classic_read'):
        """
        Override read to bypass record rules for team member records
        
        This allows team leaders to read team member records even though
        the native "Personal Orders" rule would normally block them.
        """
        _logger.info(f"[sale.order.read] START - User {self.env.user.id} ({self.env.user.name}) - Record IDs: {self.ids}")
        
        # Check if user is team leader (4th tier)
        user = self.env.user
        is_salesman = user.has_group('sales_team.group_sale_salesman')
        has_all_leads = user.has_group('sales_team.group_sale_salesman_all_leads')
        is_team_leader = user.has_group('ox_sales_team_hierarchy.group_team_leader')
        
        if (is_salesman and not has_all_leads and is_team_leader):
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            if teams:
                # Get team member user IDs
                member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
                member_user_ids = member_user_ids.filtered(lambda u: u and u.id).ids
                _logger.info(f"[sale.order.read] Team member user IDs: {member_user_ids}")
                
                # Use SQL to read user_id values directly (avoids recursion)
                if self.ids:
                    self.env.cr.execute(
                        "SELECT id, user_id FROM sale_order WHERE id = ANY(%s)",
                        (self.ids,)
                    )
                    user_id_map = {row[0]: row[1] for row in self.env.cr.fetchall()}
                    
                    # Separate records: team member records vs own records
                    team_member_record_ids = [rid for rid in self.ids if member_user_ids and user_id_map.get(rid) in member_user_ids]
                    own_record_ids = [rid for rid in self.ids if user_id_map.get(rid) == user.id]
                    other_record_ids = [rid for rid in self.ids if rid not in team_member_record_ids and rid not in own_record_ids]
                    
                    _logger.info(f"[sale.order.read] Team member records: {len(team_member_record_ids)}, Own: {len(own_record_ids)}, Other: {len(other_record_ids)}")
                    
                    # Read all accessible records with sudo (bypass record rules)
                    # We've already verified ownership via SQL, so it's safe to use sudo
                    result = []
                    if team_member_record_ids:
                        team_member_records = self.browse(team_member_record_ids)
                        _logger.info(f"[sale.order.read] Reading {len(team_member_record_ids)} team member records with sudo")
                        result.extend(super(SaleOrder, team_member_records.sudo()).read(fields, load))
                    
                    # Read own records with sudo (we've verified they're own records via SQL)
                    if own_record_ids:
                        own_records = self.browse(own_record_ids)
                        _logger.info(f"[sale.order.read] Reading {len(own_record_ids)} own records with sudo")
                        result.extend(super(SaleOrder, own_records.sudo()).read(fields, load))
                    
                    # Don't read other records - they shouldn't be accessible to team leaders
                    if other_record_ids:
                        _logger.info(f"[sale.order.read] Skipping {len(other_record_ids)} other records (not accessible)")
                    
                    # Maintain original order
                    if result:
                        id_order = {r['id']: i for i, r in enumerate(result)}
                        return sorted(result, key=lambda r: self.ids.index(r['id']) if r['id'] in self.ids else len(self.ids))
                    return result
        
        # For non-team-leaders, use standard read
        _logger.info(f"[sale.order.read] Using standard read for all records")
        return super().read(fields, load)
    
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
        Override read_group to handle aggregations for team leaders
        
        The issue: When _search returns a Query from _as_query() with IDs,
        read_group fails with GroupingError because of WITH ORDINALITY.
        This override ensures team leader logic works with aggregations by
        using a context flag to tell _search() to return a domain-based Query.
        """
        # Check if user is team leader (4th tier)
        user = self.env.user
        is_salesman = user.has_group('sales_team.group_sale_salesman')
        has_all_leads = user.has_group('sales_team.group_sale_salesman_all_leads')
        is_team_leader = user.has_group('ox_sales_team_hierarchy.group_team_leader')
        
        # IMPORTANT: If user has "All Documents" access, bypass our override
        # They should use standard Odoo read_group which handles aggregations correctly
        # Note: We don't check self.env.su here because we might be called with sudo() but still want team leader logic
        if has_all_leads:
            _logger.info(f"[sale.order.read_group] User has 'All Documents' - using standard read_group")
            return super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        
        if (is_salesman and not has_all_leads and is_team_leader):
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            if teams:
                member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id')
                member_user_ids = member_user_ids.filtered(lambda u: u and u.id).ids
                
                if member_user_ids:
                    # Extend domain to include own + team member records
                    # Use domain-based approach which works with aggregations
                    extended_domain = expression.OR([
                        expression.AND([domain, [('user_id', '=', user.id)]]),  # Own records
                        expression.AND([domain, [('user_id', 'in', member_user_ids)]])  # Team member records
                    ])
                    _logger.info(f"[sale.order.read_group] Using extended domain for team leader aggregations")
                    # Call parent's read_group with sudo and context flag
                    # This bypasses our override to avoid recursion, and the context flag tells _search() to use domain-based Query
                    # Use sudo to bypass record rules for team members, but domain ensures we only get own + team members
                    return super(SaleOrder, self.sudo().with_context(_read_group_mode=True)).read_group(
                        extended_domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy
                    )
        
        # For non-team-leaders, use standard read_group
        return super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
