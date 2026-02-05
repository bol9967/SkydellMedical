# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
from datetime import datetime, timedelta, time

_logger = logging.getLogger(__name__)


class ReferralDashboard(models.Model):
    """Dashboard model for referral analytics overview"""
    _name = 'referral.dashboard'
    _description = 'Referral Program Dashboard'
    _order = 'id'

    # This is a virtual model - we'll use SQL view or computed fields
    name = fields.Char(string='Dashboard', default='Referral Program Dashboard')
    
    # Stat fields for tiles
    total_clicks = fields.Integer(string='Total Clicks', compute='_compute_stats')
    unique_clicks = fields.Integer(string='Unique Clicks', compute='_compute_stats')
    total_signups = fields.Integer(string='Total Signups', compute='_compute_stats')
    conversion_rate = fields.Float(string='Conversion Rate %', compute='_compute_stats')
    total_revenue = fields.Monetary(string='Total Revenue', currency_field='currency_id', compute='_compute_stats')
    order_count = fields.Integer(string='Orders', compute='_compute_stats')
    average_order_value = fields.Monetary(string='Avg Order Value', currency_field='currency_id', compute='_compute_stats')
    new_referrals = fields.Integer(string='New Referrals', compute='_compute_stats')
    active_referrers = fields.Integer(string='Active Referrers', compute='_compute_stats')
    pending_fraud = fields.Integer(string='Pending Fraud Cases', compute='_compute_stats')
    
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    
    # Date filters
    date_from = fields.Date(string='From Date', default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='To Date', default=fields.Date.today)

    @api.depends('date_from', 'date_to')
    def _compute_stats(self):
        """Compute dashboard statistics"""
        for dashboard in self:
            date_from = dashboard.date_from or (fields.Date.today() - timedelta(days=30))
            date_to = dashboard.date_to or fields.Date.today()
            
            # Get clicks
            clicks = self.env['referral.link.click'].search([
                ('click_date', '>=', datetime.combine(date_from, time.min)),
                ('click_date', '<=', datetime.combine(date_to, time.max))
            ])
            dashboard.total_clicks = len(clicks)
            dashboard.unique_clicks = len(clicks.filtered('is_unique'))
            dashboard.total_signups = len(clicks.filtered('converted'))
            
            # Conversion rate
            if dashboard.total_clicks > 0:
                dashboard.conversion_rate = (dashboard.total_signups / dashboard.total_clicks) * 100
            else:
                dashboard.conversion_rate = 0.0
            
            # Get orders from referred partners
            referred_partners = self.env['res.partner'].search([
                ('referred_by_id', '!=', False),
                ('create_date', '>=', datetime.combine(date_from, time.min)),
                ('create_date', '<=', datetime.combine(date_to, time.max))
            ])
            
            orders = self.env['sale.order'].search([
                ('partner_id', 'in', referred_partners.ids),
                ('date_order', '>=', datetime.combine(date_from, time.min)),
                ('date_order', '<=', datetime.combine(date_to, time.max)),
                ('state', 'in', ['sale', 'done'])
            ])
            
            dashboard.total_revenue = sum(orders.mapped('amount_total'))
            dashboard.order_count = len(orders)
            
            if dashboard.order_count > 0:
                dashboard.average_order_value = dashboard.total_revenue / dashboard.order_count
            else:
                dashboard.average_order_value = 0.0
            
            # New referrals
            dashboard.new_referrals = len(referred_partners)
            
            # Active referrers (partners with referral code who had clicks in period)
            active_referrer_ids = list(set(clicks.mapped('partner_id').ids))
            dashboard.active_referrers = len([pid for pid in active_referrer_ids if pid])
            
            # Pending fraud cases
            fraud_cases = self.env['referral.fraud.detection'].search_count([
                ('status', '=', 'pending')
            ])
            dashboard.pending_fraud = fraud_cases

    @api.model
    def get_dashboard_record(self):
        """Get or create dashboard record"""
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({
                'name': 'Referral Program Dashboard',
                'date_from': fields.Date.today() - timedelta(days=30),
                'date_to': fields.Date.today()
            })
        return dashboard

    @api.model
    def get_dashboard_stats(self, date_from=None, date_to=None):
        """Get dashboard statistics as dict for JS widget"""
        if not date_from:
            date_from = fields.Date.today() - timedelta(days=30)
        if not date_to:
            date_to = fields.Date.today()
        
        dashboard = self.get_dashboard_record()
        dashboard.write({
            'date_from': date_from,
            'date_to': date_to
        })
        dashboard._compute_stats()
        
        # Get time-series data for charts
        time_series_data = self._get_time_series_data(date_from, date_to)
        # Get breakdown data for bar charts
        breakdown_data = self._get_breakdown_data(date_from, date_to)
        # Get sparkline data for KPI tiles
        sparkline_data = self._get_sparkline_data(date_from, date_to)
        
        return {
            'total_clicks': dashboard.total_clicks,
            'unique_clicks': dashboard.unique_clicks,
            'total_signups': dashboard.total_signups,
            'conversion_rate': dashboard.conversion_rate,
            'total_revenue': dashboard.total_revenue,
            'order_count': dashboard.order_count,
            'average_order_value': dashboard.average_order_value,
            'new_referrals': dashboard.new_referrals,
            'active_referrers': dashboard.active_referrers,
            'pending_fraud': dashboard.pending_fraud,
            'time_series': time_series_data,
            'breakdown': breakdown_data,
            'sparklines': sparkline_data,
        }
    
    def _get_time_series_data(self, date_from, date_to):
        """Get time-series data for line/bar charts"""
        # Generate daily data points
        current_date = datetime.combine(date_from, time.min)
        end_date = datetime.combine(date_to, time.max)
        dates = []
        clicks_data = []
        signups_data = []
        revenue_data = []
        
        while current_date <= end_date:
            dates.append(current_date.strftime('%Y-%m-%d'))
            day_start = datetime.combine(current_date.date(), time.min)
            day_end = datetime.combine(current_date.date(), time.max)
            
            # Count clicks for this day
            clicks = self.env['referral.link.click'].search_count([
                ('click_date', '>=', day_start),
                ('click_date', '<=', day_end)
            ])
            clicks_data.append(clicks)
            
            # Count signups for this day
            signups = self.env['referral.link.click'].search_count([
                ('click_date', '>=', day_start),
                ('click_date', '<=', day_end),
                ('converted', '=', True)
            ])
            signups_data.append(signups)
            
            # Get revenue for this day
            referred_partners = self.env['res.partner'].search([
                ('referred_by_id', '!=', False)
            ])
            orders = self.env['sale.order'].search([
                ('partner_id', 'in', referred_partners.ids),
                ('date_order', '>=', day_start),
                ('date_order', '<=', day_end),
                ('state', 'in', ['sale', 'done'])
            ])
            revenue_data.append(sum(orders.mapped('amount_total')))
            
            current_date += timedelta(days=1)
        
        return {
            'dates': dates,
            'clicks': clicks_data,
            'signups': signups_data,
            'revenue': revenue_data,
        }
    
    def _get_breakdown_data(self, date_from, date_to):
        """Get breakdown data for horizontal bar charts"""
        date_from_dt = datetime.combine(date_from, time.min)
        date_to_dt = datetime.combine(date_to, time.max)
        
        # Device breakdown
        clicks = self.env['referral.link.click'].search([
            ('click_date', '>=', date_from_dt),
            ('click_date', '<=', date_to_dt)
        ])
        
        device_data = {}
        for click in clicks:
            # Simple device detection from user agent
            ua = (click.user_agent or '').lower()
            if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
                device = 'Mobile'
            elif 'tablet' in ua or 'ipad' in ua:
                device = 'Tablet'
            else:
                device = 'Desktop'
            device_data[device] = device_data.get(device, 0) + 1
        
        # Referral type breakdown (Doctor 1, Doctor 2/3/4, Company)
        referred_partners = self.env['res.partner'].search([
            ('referred_by_id', '!=', False),
            ('create_date', '>=', date_from_dt),
            ('create_date', '<=', date_to_dt)
        ])
        
        doctor_1_count = 0
        doctor_2_4_count = 0
        company_count = 0
        
        for partner in referred_partners:
            referrer = partner.referred_by_id
            if referrer:
                # Check if referrer is Doctor 1 (has is_doctor_1 field and it's True)
                if hasattr(referrer, 'is_doctor_1') and referrer.is_doctor_1:
                    doctor_1_count += 1
                # Check if referrer has Doctor-Referred category
                elif referrer.category_id:
                    category_names = referrer.category_id.mapped('name')
                    if any('Doctor-Referred' in name for name in category_names):
                        doctor_2_4_count += 1
                    else:
                        company_count += 1
                else:
                    company_count += 1
            else:
                company_count += 1
        
        return {
            'device': {
                'labels': list(device_data.keys()) or ['Desktop', 'Mobile', 'Tablet'],
                'data': [device_data.get(d, 0) for d in ['Desktop', 'Mobile', 'Tablet']]
            },
            'referral_type': {
                'labels': ['Doctor 1', 'Doctor 2/3/4', 'Company'],
                'data': [doctor_1_count, doctor_2_4_count, company_count]
            }
        }
    
    def _get_sparkline_data(self, date_from, date_to):
        """Get sparkline data for KPI tiles (last 30 days or period)"""
        # Get data points for sparklines (simplified - last 7 days)
        sparkline_days = 7
        current_date = datetime.combine(date_to, time.min) - timedelta(days=sparkline_days)
        end_date = datetime.combine(date_to, time.max)
        
        clicks_sparkline = []
        signups_sparkline = []
        revenue_sparkline = []
        conversion_sparkline = []
        
        while current_date <= end_date:
            day_start = datetime.combine(current_date.date(), time.min)
            day_end = datetime.combine(current_date.date(), time.max)
            
            clicks = self.env['referral.link.click'].search_count([
                ('click_date', '>=', day_start),
                ('click_date', '<=', day_end)
            ])
            clicks_sparkline.append(clicks)
            
            signups = self.env['referral.link.click'].search_count([
                ('click_date', '>=', day_start),
                ('click_date', '<=', day_end),
                ('converted', '=', True)
            ])
            signups_sparkline.append(signups)
            
            referred_partners = self.env['res.partner'].search([
                ('referred_by_id', '!=', False)
            ])
            orders = self.env['sale.order'].search([
                ('partner_id', 'in', referred_partners.ids),
                ('date_order', '>=', day_start),
                ('date_order', '<=', day_end),
                ('state', 'in', ['sale', 'done'])
            ])
            revenue = sum(orders.mapped('amount_total'))
            revenue_sparkline.append(revenue)
            
            conversion = (signups / clicks * 100) if clicks > 0 else 0
            conversion_sparkline.append(conversion)
            
            current_date += timedelta(days=1)
        
        return {
            'clicks': clicks_sparkline,
            'signups': signups_sparkline,
            'revenue': revenue_sparkline,
            'conversion': conversion_sparkline,
        }

    def action_view_clicks(self):
        """Open clicks view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Referral Link Clicks',
            'res_model': 'referral.link.click',
            'view_mode': 'graph,list,form',
            'domain': [
                ('click_date', '>=', datetime.combine(self.date_from, time.min)),
                ('click_date', '<=', datetime.combine(self.date_to, time.max))
            ],
            'context': {'search_default_today': 0}
        }

    def action_view_unique_clicks(self):
        """Open unique clicks view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Unique Clicks',
            'res_model': 'referral.link.click',
            'view_mode': 'list,form',
            'domain': [
                ('click_date', '>=', datetime.combine(self.date_from, time.min)),
                ('click_date', '<=', datetime.combine(self.date_to, time.max)),
                ('is_unique', '=', True)
            ],
        }

    def action_view_signups(self):
        """Open signups (converted clicks) view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Signups',
            'res_model': 'referral.link.click',
            'view_mode': 'list,form',
            'domain': [
                ('click_date', '>=', datetime.combine(self.date_from, time.min)),
                ('click_date', '<=', datetime.combine(self.date_to, time.max)),
                ('converted', '=', True)
            ],
        }

    def action_view_orders(self):
        """Open orders from referred partners"""
        self.ensure_one()
        referred_partners = self.env['res.partner'].search([
            ('referred_by_id', '!=', False)
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': 'Orders from Referrals',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', 'in', referred_partners.ids),
                ('date_order', '>=', datetime.combine(self.date_from, time.min)),
                ('date_order', '<=', datetime.combine(self.date_to, time.max)),
                ('state', 'in', ['sale', 'done'])
            ],
        }

    def action_view_referrals(self):
        """Open new referrals view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Referrals',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [
                ('referred_by_id', '!=', False),
                ('create_date', '>=', datetime.combine(self.date_from, time.min)),
                ('create_date', '<=', datetime.combine(self.date_to, time.max))
            ],
        }

    def action_view_referrers(self):
        """Open active referrers view"""
        self.ensure_one()
        clicks = self.env['referral.link.click'].search([
            ('click_date', '>=', datetime.combine(self.date_from, time.min)),
            ('click_date', '<=', datetime.combine(self.date_to, time.max))
        ])
        referrer_ids = list(set(clicks.mapped('partner_id').ids))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Active Referrers',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', referrer_ids)],
        }

    def action_view_fraud(self):
        """Open fraud detection view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fraud Detection',
            'res_model': 'referral.fraud.detection',
            'view_mode': 'list,form',
            'domain': [('status', '=', 'pending')],
        }
