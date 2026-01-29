# -*- coding: utf-8 -*-

import logging
from odoo import api, models
from odoo.exceptions import AccessError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """Extend search to include team member records for team leaders
        
        Aligns with Odoo 18: override _search to extend behavior.
        Standard search applies record rules first, then we add team member records.
        """
        _logger.info(f"[crm.lead._search] User {self.env.user.id} ({self.env.user.name}) - Domain: {domain}")
        
        # Standard search with record rules applied
        result_query = super()._search(domain, offset=0, limit=0, order=False)
        # Convert Query to list of IDs - Query objects are iterable and yield IDs
        result_ids = list(result_query) if result_query else []
        _logger.info(f"[crm.lead._search] Base search found {len(result_ids)} records: {result_ids[:10]}")
        
        # Only extend for team leaders (not managers who can see all)
        user = self.env.user
        is_salesman = user.has_group('sales_team.group_sale_salesman')
        has_all_leads = user.has_group('sales_team.group_sale_salesman_all_leads')
        is_team_leader = user.has_group('ox_sales_team_hierarchy.group_team_leader')
        
        _logger.info(f"[crm.lead._search] User groups - Salesman: {is_salesman}, All Leads: {has_all_leads}, Team Leader: {is_team_leader}")
        
        if (is_salesman and not has_all_leads and is_team_leader):
            # Check if user is a team leader
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            _logger.info(f"[crm.lead._search] User is team leader of {len(teams)} teams: {teams.mapped('name')}")
            
            if teams:
                # Get team member user IDs
                member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id').ids
                _logger.info(f"[crm.lead._search] Team member user IDs: {member_user_ids}")
                
                if member_user_ids:
                    # Build domain for team member records
                    # Simply add user_id condition to the original domain
                    # Odoo will handle any existing user_id conditions
                    team_domain = expression.AND([
                        domain,
                        [('user_id', 'in', member_user_ids)]
                    ])
                    _logger.info(f"[crm.lead._search] Searching team member records with domain: {team_domain}")
                    
                    # Search team member records using parent's _search to avoid recursion
                    # Use sudo() environment but call parent _search directly
                    team_result_query = super(CrmLead, self.sudo())._search(
                        team_domain, offset=0, limit=0, order=False
                    )
                    # Convert Query to recordset, then get IDs (more reliable than direct iteration)
                    team_result_ids = self.browse(team_result_query).ids if team_result_query else []
                    _logger.info(f"[crm.lead._search] Found {len(team_result_ids)} team member records: {team_result_ids[:10]}")
                    
                    # Union with original results (combine ID lists)
                    result_ids = list(set(result_ids) | set(team_result_ids))
                    _logger.info(f"[crm.lead._search] Combined results: {len(result_ids)} total records")
        
        # Return Query object - Odoo will handle offset, limit, and order
        # _search should return a Query object, which we get by calling _as_query on the recordset
        return self.browse(result_ids)._as_query(order or self._order)
    
    def check_access_rule(self, operation):
        """Override to allow team leaders to read team member records
        
        This bypasses record rules for team leaders when reading team member records.
        Aligns with Odoo 18: override check_access_rule to extend access control.
        """
        _logger.info(f"[crm.lead.check_access_rule] START - User {self.env.user.id} ({self.env.user.name}) - Operation: {operation}, Record IDs: {self.ids}")
        
        # Check if user is team leader and operation is read
        if operation == 'read':
            user = self.env.user
            is_salesman = user.has_group('sales_team.group_sale_salesman')
            has_all_leads = user.has_group('sales_team.group_sale_salesman_all_leads')
            is_team_leader = user.has_group('ox_sales_team_hierarchy.group_team_leader')
            
            _logger.info(f"[crm.lead.check_access_rule] User groups - Salesman: {is_salesman}, All Leads: {has_all_leads}, Team Leader: {is_team_leader}")
            
            if (is_salesman and not has_all_leads and is_team_leader):
                # Check if user is a team leader
                teams = self.env['crm.team'].search([('user_id', '=', user.id)])
                _logger.info(f"[crm.lead.check_access_rule] User is team leader of {len(teams)} teams: {teams.mapped('name') if teams else []}")
                
                if teams:
                    # Get team member user IDs
                    member_user_ids = teams.mapped('crm_team_member_ids').filtered('active').mapped('user_id').ids
                    _logger.info(f"[crm.lead.check_access_rule] Team member user IDs: {member_user_ids}")
                    
                    if member_user_ids:
                        # Separate team member records from others
                        # Need to read user_id field first to filter
                        team_member_records = self.filtered(lambda r: r.user_id and r.user_id.id in member_user_ids)
                        other_records = self - team_member_records
                        
                        _logger.info(f"[crm.lead.check_access_rule] Team member records: {len(team_member_records)} IDs: {team_member_records.ids}")
                        _logger.info(f"[crm.lead.check_access_rule] Other records: {len(other_records)} IDs: {other_records.ids}")
                        
                        # If ALL records are team member records, bypass check completely
                        if not other_records and team_member_records:
                            _logger.info(f"[crm.lead.check_access_rule] ALL records are team member records - bypassing access check")
                            return
                        
                        # If we have mixed records, check other records first
                        if other_records:
                            try:
                                _logger.info(f"[crm.lead.check_access_rule] Checking access for {len(other_records)} other records")
                                super(CrmLead, other_records).check_access_rule(operation)
                                _logger.info(f"[crm.lead.check_access_rule] Other records passed access check")
                            except AccessError as e:
                                _logger.warning(f"[crm.lead.check_access_rule] Other records failed access check: {e}")
                                # If we have team member records, we'll allow those but the error will still be raised
                                # unless ALL records are team member records
                                if not team_member_records:
                                    _logger.error(f"[crm.lead.check_access_rule] No team member records, raising AccessError")
                                    raise
                                _logger.info(f"[crm.lead.check_access_rule] Will allow team member records, but error from other records will propagate")
                        
                        # Team member records are allowed (bypass record rules)
                        if team_member_records:
                            _logger.info(f"[crm.lead.check_access_rule] Allowing access to {len(team_member_records)} team member records")
                            # Only return if ALL records are team member records
                            if not other_records:
                                return
        
        # For non-read operations or non-team-leaders, use standard check
        _logger.info(f"[crm.lead.check_access_rule] Using standard access check for all records")
        try:
            super().check_access_rule(operation)
            _logger.info(f"[crm.lead.check_access_rule] Standard check passed")
        except AccessError as e:
            _logger.warning(f"[crm.lead.check_access_rule] Standard check failed: {e}")
            raise
