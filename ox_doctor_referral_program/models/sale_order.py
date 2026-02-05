# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Referral tracking
    is_referral_order = fields.Boolean(
        string='Referral Order',
        compute='_compute_is_referral_order',
        store=True,
        help='True if order is from a referred doctor'
    )
    referral_doctor_1_id = fields.Many2one(
        'res.partner',
        string='Doctor 1 (Referral Chain)',
        compute='_compute_referral_doctor_1',
        store=True,
        help='Doctor 1 in the referral chain (for promo rewards)'
    )
    
    # Promo reward tracking
    promo_reward_granted = fields.Boolean(
        string='Promo Reward Granted',
        default=False,
        help='True if Doctor 1 has received promo reward for this order'
    )

    @api.depends('partner_id', 'partner_id.referral_salesperson_id')
    def _compute_is_referral_order(self):
        for order in self:
            order.is_referral_order = bool(
                order.partner_id and 
                order.partner_id.referral_salesperson_id
            )

    @api.depends('partner_id', 'partner_id.doctor_1_id')
    def _compute_referral_doctor_1(self):
        for order in self:
            if order.partner_id and order.partner_id.doctor_1_id:
                order.referral_doctor_1_id = order.partner_id.doctor_1_id
            else:
                order.referral_doctor_1_id = False

    @api.model_create_multi
    def create(self, vals_list):
        """Assign salesperson based on referral chain"""
        orders = super().create(vals_list)
        
        # Process salesperson assignment after creation
        for order in orders:
            self._assign_salesperson_from_referral(order)
        
        return orders

    def write(self, vals):
        """Handle salesperson assignment when partner changes"""
        result = super().write(vals)
        
        # If partner_id changed, check for salesperson assignment
        if 'partner_id' in vals:
            for order in self:
                self._assign_salesperson_from_referral(order)
        
        return result

    def _assign_salesperson_from_referral(self, order):
        """Assign salesperson based on referral chain
        
        Uses partner.user_id (native salesperson field) which is set from referral chain.
        This aligns with ox_sales_commission module which uses order.user_id for commission tracking.
        """
        if order.partner_id:
            # Use native user_id field from partner (set via referral chain)
            # Only assign salesperson if:
            # 1. Referral level is 0 (Doctor 1) or 1 (Doctor 2/3/4)
            # 2. NOT a company referral (level 999 from Doctor 2/3/4's referrals)
            if order.partner_id.referral_level <= 1 and order.partner_id.user_id:
                if not order.user_id:
                    order.user_id = order.partner_id.user_id.id
                    _logger.info(
                        f"[sale.order] Assigned salesperson {order.partner_id.user_id.id} "
                        f"to order {order.id} for partner {order.partner_id.id} "
                        f"(referral level: {order.partner_id.referral_level})"
                    )
            elif order.partner_id.referral_level > 2:
                # Company referral - no salesperson assignment
                _logger.info(
                    f"[sale.order] Order {order.id} is company referral "
                    f"(level {order.partner_id.referral_level}) - no salesperson assignment"
                )

    def action_confirm(self):
        """Check for promo reward eligibility when order is confirmed"""
        result = super().action_confirm()
        
        # Check promo reward eligibility after order confirmation
        self._check_promo_reward_eligibility()
        
        return result

    def _check_promo_reward_eligibility(self):
        """Check if Doctor 1 is eligible for promo reward using reward rules"""
        for order in self:
            # Only process if:
            # 1. Order is confirmed
            # 2. Has Doctor 1 in referral chain
            # 3. Promo reward not already granted
            if (order.state not in ['sale', 'done'] or 
                not order.referral_doctor_1_id or 
                order.promo_reward_granted):
                continue
            
            # Check referral level - only grant if referred by Doctor 1, 2, 3, or 4
            # (Level 1 or 2 in referral chain, where level 0 = Doctor 1, level 1 = Doctor 2/3/4)
            # Doctor 1 boundary is 1 level - so Doctor 1 gets rewards for referrals of Doctor 2, 3, 4
            if order.partner_id.referral_level not in [1, 2]:
                continue
            
            # Get active reward rules for current company
            reward_rules = self.env['referral.reward.rule'].search([
                ('active', '=', True),
                ('company_id', '=', order.company_id.id)
            ], order='sequence, id')
            
            if not reward_rules:
                # Fallback to legacy configuration if no rules exist
                self._check_legacy_reward_eligibility(order)
                continue
            
            # Check each reward rule
            for rule in reward_rules:
                is_eligible, matched_qty, matched_revenue, reward_product = rule.check_order_eligibility(order)
                
                if is_eligible and reward_product:
                    _logger.info(
                        f"[sale.order] Order {order.id} qualifies for reward rule '{rule.name}'. "
                        f"Matched Qty: {matched_qty}, Revenue: {matched_revenue}. "
                        f"Reward Product: {reward_product.name}. "
                        f"Doctor 1: {order.referral_doctor_1_id.id}"
                    )
                    
                    # Create promo reward record
                    self.env['referral.reward'].create({
                        'doctor_1_id': order.referral_doctor_1_id.id,
                        'referred_doctor_id': order.partner_id.id,
                        'sale_order_id': order.id,
                        'vials_purchased': matched_qty,  # Store matched quantity
                        'reward_type': 'promo_vial',
                        'product_id': reward_product.id,
                        'quantity': rule.reward_quantity,
                        'state': 'pending',
                    })
                    
                    order.promo_reward_granted = True
                    _logger.info(
                        f"[sale.order] Created promo reward for Doctor 1 {order.referral_doctor_1_id.id} "
                        f"from order {order.id} using rule '{rule.name}'"
                    )
                    # Only apply first matching rule
                    break
    
    def _check_legacy_reward_eligibility(self, order):
        """Legacy reward check - only used if no reward rules exist"""
        # This method is kept for backward compatibility but should not be used
        # Users should configure reward rules instead
        skydell_platinum_product = self.env['ir.config_parameter'].sudo().get_param(
            'ox_doctor_referral_program.skydell_platinum_product_id'
        )
        
        if not skydell_platinum_product:
            _logger.warning(
                "[sale.order] No reward rules configured and Skydell Platinum product not configured. "
                "Please configure reward rules in Settings → Doctor Referral Program → Reward Rules."
            )
            return
        
        _logger.warning(
            "[sale.order] No reward rules found. Please configure reward rules in Settings. "
            "Legacy minimum vials check is no longer supported."
        )
