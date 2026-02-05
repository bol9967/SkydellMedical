# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Global reward product (used as fallback when reward rules don't specify a product)
    skydell_platinum_product_id = fields.Many2one(
        'product.product',
        string='Global Reward Product (Skydell Platinum)',
        config_parameter='ox_doctor_referral_program.skydell_platinum_product_id',
        help='Default product used for rewards when reward rules don\'t specify a product. This is used as fallback.'
    )
    
    auto_grant_rewards = fields.Boolean(
        string='Auto-Grant Rewards',
        default=False,
        config_parameter='ox_doctor_referral_program.auto_grant_rewards',
        help='Automatically grant promo rewards when conditions are met'
    )
    
    reward_rules_count = fields.Integer(
        string='Reward Rules Count',
        compute='_compute_reward_rules_count',
        store=False,
        readonly=True,
        help='Number of reward rules configured for current company'
    )
    
    company_property_user_id = fields.Many2one(
        'res.users',
        string='Company Property User',
        config_parameter='ox_doctor_referral_program.company_property_user_id',
        domain=[('share', '=', False), ('active', '=', True)],
        help='User assigned to partners referred by Doctor 2 (Level 1) or direct signups. This user will be set as res.partner.user_id for these referrals. Only internal users are shown.'
    )
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to compute reward_rules_count"""
        records = super().create(vals_list)
        records._compute_reward_rules_count()
        return records
    
    @api.model
    def default_get(self, fields_list):
        """Override default_get to compute reward_rules_count"""
        res = super().default_get(fields_list)
        if 'reward_rules_count' in fields_list:
            res['reward_rules_count'] = self.env['referral.reward.rule'].search_count([
                ('company_id', '=', self.env.company.id)
            ])
        return res
    
    @api.depends()
    def _compute_reward_rules_count(self):
        """Compute count of reward rules for current company - always fresh"""
        for record in self:
            # Always compute fresh count from database
            record.reward_rules_count = self.env['referral.reward.rule'].search_count([
                ('company_id', '=', self.env.company.id)
            ])
    
    @api.model
    def get_values(self):
        """Override to include fresh reward rules count"""
        res = super().get_values()
        # Get fresh count when loading settings
        res['reward_rules_count'] = self.env['referral.reward.rule'].search_count([
            ('company_id', '=', self.env.company.id)
        ])
        return res

    @api.model
    def get_reward_rules(self):
        """Get active reward rules for current company"""
        return self.env['referral.reward.rule'].search([
            ('active', '=', True),
            ('company_id', '=', self.env.company.id)
        ], order='sequence, id')
    
    def action_open_configured_rules(self):
        """Open list view of all configured reward rules"""
        self.ensure_one()
        # Get count of rules for current company
        company_id = self.env.company.id
        rule_count = self.env['referral.reward.rule'].search_count([
            ('company_id', '=', company_id)
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': f'Configured Reward Rules ({rule_count})',
            'res_model': 'referral.reward.rule',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', company_id)],
            'context': {'default_company_id': company_id},
            'target': 'current',
        }
    
    def action_create_new_rule(self):
        """Open form view to create a new reward rule"""
        self.ensure_one()
        company_id = self.env.company.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Reward Rule',
            'res_model': 'referral.reward.rule',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_company_id': company_id,
                'form_view_initial_mode': 'edit',
            },
        }
