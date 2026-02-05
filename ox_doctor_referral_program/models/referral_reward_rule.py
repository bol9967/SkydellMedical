# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReferralRewardRule(models.Model):
    """Reward rules for referral program - flexible product/category based rewards"""
    _name = 'referral.reward.rule'
    _description = 'Referral Reward Rule'
    _order = 'sequence, id'

    name = fields.Char(
        string='Rule Name',
        required=True,
        help='Name of this reward rule'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Enable/disable this reward rule'
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Order of rule evaluation (lower numbers evaluated first)'
    )
    
    # Product/Category Selection
    apply_to_type = fields.Selection([
        ('product', 'Specific Products'),
        ('category', 'Product Categories'),
    ], string='Apply To', required=True, default='product',
       help='Whether this rule applies to specific products or product categories')
    
    product_ids = fields.Many2many(
        'product.product',
        'referral_reward_rule_product_rel',
        'rule_id', 'product_id',
        string='Products',
        help='Products that trigger this reward rule',
        domain="[('sale_ok', '=', True)]"
    )
    product_category_ids = fields.Many2many(
        'product.category',
        'referral_reward_rule_category_rel',
        'rule_id', 'category_id',
        string='Product Categories',
        help='Product categories that trigger this reward rule'
    )
    
    # Reward Type and Threshold
    reward_type = fields.Selection([
        ('qty', 'Quantity Based'),
        ('revenue', 'Revenue Based'),
    ], string='Reward Type', required=True, default='qty',
       help='Whether reward is based on quantity or revenue')
    
    minimum_qty = fields.Float(
        string='Minimum Quantity',
        default=0.0,
        help='Minimum quantity required to trigger reward (if reward_type = qty)'
    )
    minimum_revenue = fields.Monetary(
        string='Minimum Revenue',
        currency_field='currency_id',
        default=0.0,
        help='Minimum revenue required to trigger reward (if reward_type = revenue)'
    )
    
    # Reward Product
    reward_product_id = fields.Many2one(
        'product.product',
        string='Reward Product',
        required=False,
        help='Free product to grant as reward. If not set, uses global Skydell Platinum product'
    )
    reward_quantity = fields.Float(
        string='Reward Quantity',
        default=1.0,
        required=True,
        help='Quantity of reward product to grant'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        help='Company this rule applies to'
    )
    
    # Description
    description = fields.Text(
        string='Description',
        help='Additional notes about this reward rule'
    )

    @api.constrains('product_ids', 'product_category_ids', 'apply_to_type')
    def _check_products_or_categories(self):
        """Ensure at least one product or category is selected"""
        for rule in self:
            if rule.apply_to_type == 'product' and not rule.product_ids:
                raise ValidationError(
                    'Please select at least one product when "Apply To" is set to "Specific Products".'
                )
            elif rule.apply_to_type == 'category' and not rule.product_category_ids:
                raise ValidationError(
                    'Please select at least one product category when "Apply To" is set to "Product Categories".'
                )

    @api.constrains('minimum_qty', 'minimum_revenue', 'reward_type')
    def _check_threshold(self):
        """Ensure threshold is set based on reward type"""
        for rule in self:
            if rule.reward_type == 'qty' and rule.minimum_qty <= 0:
                raise ValidationError(
                    'Minimum Quantity must be greater than 0 when Reward Type is "Quantity Based".'
                )
            elif rule.reward_type == 'revenue' and rule.minimum_revenue <= 0:
                raise ValidationError(
                    'Minimum Revenue must be greater than 0 when Reward Type is "Revenue Based".'
                )

    def get_applicable_products(self):
        """Get all products that this rule applies to"""
        self.ensure_one()
        if self.apply_to_type == 'product':
            return self.product_ids
        else:  # category
            return self.env['product.product'].search([
                ('categ_id', 'in', self.product_category_ids.ids),
                ('sale_ok', '=', True)
            ])

    def get_reward_product(self):
        """Get reward product - use rule's product or fallback to global Skydell Platinum"""
        self.ensure_one()
        if self.reward_product_id:
            return self.reward_product_id
        
        # Fallback to global Skydell Platinum product
        skydell_platinum_product_id = self.env['ir.config_parameter'].sudo().get_param(
            'ox_doctor_referral_program.skydell_platinum_product_id'
        )
        if skydell_platinum_product_id:
            return self.env['product.product'].browse(int(skydell_platinum_product_id))
        
        return False

    def check_order_eligibility(self, order):
        """Check if an order qualifies for this reward rule
        
        Returns:
            tuple: (is_eligible: bool, matched_qty: float, matched_revenue: float, reward_product: product.product or False)
        """
        self.ensure_one()
        
        if not self.active:
            return False, 0.0, 0.0, False
        
        # Get reward product (with fallback to global)
        reward_product = self.get_reward_product()
        if not reward_product:
            return False, 0.0, 0.0, False
        
        # Get applicable products for this rule
        applicable_products = self.get_applicable_products()
        if not applicable_products:
            return False, 0.0, 0.0, False
        
        # Filter order lines that match this rule
        matching_lines = order.order_line.filtered(
            lambda l: l.product_id in applicable_products
        )
        
        if not matching_lines:
            return False, 0.0, 0.0, False
        
        # Calculate totals
        total_qty = sum(matching_lines.mapped('product_uom_qty'))
        total_revenue = sum(matching_lines.mapped('price_subtotal'))
        
        # Check threshold based on reward type
        if self.reward_type == 'qty':
            is_eligible = total_qty >= self.minimum_qty
            return is_eligible, total_qty, total_revenue, reward_product
        else:  # revenue
            is_eligible = total_revenue >= self.minimum_revenue
            return is_eligible, total_qty, total_revenue, reward_product
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure company_id is set from context if not provided"""
        for vals in vals_list:
            if 'company_id' not in vals:
                # Try to get from context (set by res.config.settings or action)
                company_id = self.env.context.get('default_company_id')
                if company_id:
                    vals['company_id'] = company_id
                elif not vals.get('company_id'):
                    # Fallback to current company
                    vals['company_id'] = self.env.company.id
        return super(ReferralRewardRule, self).create(vals_list)
    
    @api.model
    def action_open_reward_rules(self):
        """Action method to open reward rules list view
        
        This method is used instead of a static window action to avoid context
        evaluation errors when Odoo tries to evaluate company_id as a variable.
        No context is set here - the model's create() method handles company_id automatically.
        """
        # Return window action without context to avoid evaluation errors
        # The model's create() method will set company_id from self.env.company.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reward Rules',
            'res_model': 'referral.reward.rule',
            'view_mode': 'list,form',
            'domain': [],
            # No context - model handles company_id via create() method
            'target': 'current',
            'help': '<p class="o_view_nocontent_smiling_face">Create your first reward rule!</p><p>Configure flexible reward rules based on products or categories, with quantity or revenue thresholds.</p>',
        }
