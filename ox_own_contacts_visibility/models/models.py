# -*- coding: utf-8 -*-

import logging
from odoo import models, api, SUPERUSER_ID
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _is_admin_user(self):
        """Check if current user has admin/system access
        
        Follows Odoo 18 pattern from res_users.py _is_admin() method.
        """
        user = self.env.user
        if user.id == SUPERUSER_ID:
            return True
        return user.sudo().has_group('base.group_system') or user.sudo().has_group('base.group_erp_manager')

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """Override search to bypass record rules for admin/system users and extend for team leaders
        
        Follows Odoo 18 pattern from ir_attachment.py - checks is_superuser() first,
        then uses sudo() to bypass record rules for admin users.
        Also extends visibility for team leaders to include team member contacts.
        """
        if self.env.is_superuser():
            # Superuser bypasses all record rules
            return super()._search(domain, offset=offset, limit=limit, order=order)
        
        if self._is_admin_user():
            # Admin users bypass record rules - use sudo context to skip ir.rule restrictions
            return super(ResPartner, self.sudo())._search(domain, offset=offset, limit=limit, order=order)
        
        # Check if user is a contact team leader
        user = self.env.user
        is_contact_restricted = user.has_group('ox_own_contacts_visibility.group_sales_contact_restricted')
        is_contact_team_leader = user.has_group('ox_own_contacts_visibility.group_contact_team_leader')
        
        # Team Leader Access logic: extend to include team member contacts
        if is_contact_restricted and is_contact_team_leader:
            # Find sales teams where user is team leader
            teams = self.env['crm.team'].search([('user_id', '=', user.id)])
            if teams:
                # Get team member user IDs
                member_user_ids = (
                    teams.mapped('crm_team_member_ids')
                    .filtered('active')
                    .mapped('user_id')
                    .filtered(lambda u: u)
                    .ids
                )
                
                if member_user_ids:
                    # Search for own contacts (respects record rules)
                    own_query = super()._search(
                        expression.AND([domain, [
                            '|', '|', '|', '|', '|', '|',
                            ('id', '=', user.partner_id.id),
                            ('create_uid', '=', user.id),
                            ('user_id', '=', user.id),
                            ('message_partner_ids', 'in', user.partner_id.ids),
                            ('parent_id.create_uid', '=', user.id),
                            ('parent_id.user_id', '=', user.id),
                            ('id', '=', 1)
                        ]]),
                        offset=0,
                        limit=0,
                        order=False
                    )
                    
                    # Search for team member contacts (bypass record rules with sudo)
                    team_domain = expression.AND([domain, [
                        '|', '|', '|', '|', '|',
                        ('create_uid', 'in', member_user_ids),
                        ('user_id', 'in', member_user_ids),
                        ('message_partner_ids.user_ids', 'in', member_user_ids),
                        ('parent_id.create_uid', 'in', member_user_ids),
                        ('parent_id.user_id', 'in', member_user_ids)
                    ]])
                    team_query = super(ResPartner, self.sudo())._search(
                        team_domain,
                        offset=0,
                        limit=0,
                        order=False
                    )
                    
                    own_ids = list(own_query) if own_query else []
                    team_ids = list(team_query) if team_query else []
                    result_ids = list(set(own_ids) | set(team_ids))
                    
                    _logger.info(
                        f"[res.partner._search] Team Leader {user.id} ({user.name}) - "
                        f"Found {len(own_ids)} own + {len(team_ids)} team member = {len(result_ids)} total contacts"
                    )
                    
                    if result_ids:
                        return self.browse(result_ids)._as_query(order or self._order)
                    return self.browse([])._as_query(order or self._order)
        
        # Standard behavior for non-team-leaders
        return super()._search(domain, offset=offset, limit=limit, order=order)

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the creator as salesperson when creating a contact"""
        user = self.env.user
        # Only auto-assign for restricted users, not for settings/system users
        if not self._is_admin_user():
            # Set user_id to current user (creator) if not already set
            for vals in vals_list:
                if 'user_id' not in vals or not vals.get('user_id'):
                    _logger.info(
                        f"[ox_own_contacts_visibility.create] Setting user_id to creator {user.id} ({user.login}) "
                        f"for partner with email={vals.get('email')}, name={vals.get('name')}"
                    )
                    vals['user_id'] = self.env.user.id
                else:
                    _logger.info(
                        f"[ox_own_contacts_visibility.create] user_id already set to {vals.get('user_id')} "
                        f"for partner with email={vals.get('email')}, name={vals.get('name')}, skipping auto-assign"
                    )
        else:
            _logger.info(
                f"[ox_own_contacts_visibility.create] Admin user {user.id} ({user.login}) - skipping auto-assign"
            )
        return super().create(vals_list)

    def read(self, fields=None, load='_classic_read'):
        """Override read to allow access to company partners via sudo and team member contacts for team leaders
        
        Bypasses restrictions for admin/system users and handles company partner
        access for restricted sales users. Also allows team leaders to read team member contacts.
        """
        # Bypass restrictions for users with settings/system access
        if self.env.is_superuser() or self._is_admin_user():
            return super().read(fields=fields, load=load)
        
        user = self.env.user
        is_contact_restricted = user.has_group('ox_own_contacts_visibility.group_sales_contact_restricted')
        is_contact_team_leader = user.has_group('ox_own_contacts_visibility.group_contact_team_leader')
        
        if is_contact_restricted:
            # Get company partner IDs
            company_partner_ids = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            allowed_ids = [1] + company_partner_ids
            
            # Separate company partners from others
            company_records = self.filtered(lambda r: r.id in allowed_ids)
            other_records = self - company_records
            
            result = []
            # Read company partners with sudo (bypass security rules)
            if company_records:
                result.extend(super(ResPartner, company_records.sudo()).read(fields=fields, load=load))
            
            # Handle team leader access for other records
            if is_contact_team_leader and other_records:
                teams = self.env['crm.team'].search([('user_id', '=', user.id)])
                if teams:
                    member_user_ids = (
                        teams.mapped('crm_team_member_ids')
                        .filtered('active')
                        .mapped('user_id')
                        .filtered(lambda u: u and u.id)
                        .ids
                    )
                    
                    if member_user_ids:
                        # Use SQL to get ownership info (avoids recursion)
                        self.env.cr.execute(
                            """
                            SELECT id, create_uid, user_id 
                            FROM res_partner 
                            WHERE id = ANY(%s)
                            """,
                            (other_records.ids,)
                        )
                        ownership_map = {row[0]: {'create_uid': row[1], 'user_id': row[2]} 
                                        for row in self.env.cr.fetchall()}
                        
                        # Separate records: own, team member, other
                        own_record_ids = []
                        team_member_record_ids = []
                        other_record_ids = []
                        
                        for record in other_records:
                            rec_id = record.id
                            owner_info = ownership_map.get(rec_id, {})
                            create_uid = owner_info.get('create_uid')
                            user_id = owner_info.get('user_id')
                            
                            # Check if it's own contact
                            if (rec_id == user.partner_id.id or 
                                create_uid == user.id or 
                                user_id == user.id):
                                own_record_ids.append(rec_id)
                            # Check if it's team member contact
                            elif create_uid in member_user_ids or user_id in member_user_ids:
                                team_member_record_ids.append(rec_id)
                            else:
                                other_record_ids.append(rec_id)
                        
                        # Read own records normally (with security rules)
                        if own_record_ids:
                            own_recs = self.browse(own_record_ids)
                            result.extend(super(ResPartner, own_recs).read(fields=fields, load=load))
                        
                        # Read team member records with sudo (bypass security rules)
                        if team_member_record_ids:
                            team_recs = self.browse(team_member_record_ids)
                            result.extend(super(ResPartner, team_recs.sudo()).read(fields=fields, load=load))
                        
                        # Skip other records (not accessible)
                        if other_record_ids:
                            _logger.info(
                                f"[res.partner.read] Team Leader {user.id} skipping "
                                f"{len(other_record_ids)} non-accessible contacts"
                            )
                    else:
                        # No team members, read normally
                        if other_records:
                            result.extend(super(ResPartner, other_records).read(fields=fields, load=load))
                else:
                    # Not a team leader or no teams, read normally
                    if other_records:
                        result.extend(super(ResPartner, other_records).read(fields=fields, load=load))
            else:
                # Not a team leader, read normally
                if other_records:
                    result.extend(super(ResPartner, other_records).read(fields=fields, load=load))
            
            # Return in original order
            if result:
                id_map = {r['id']: r for r in result}
                return [id_map[r.id] for r in self if r.id in id_map]
        
        return super().read(fields=fields, load=load)


