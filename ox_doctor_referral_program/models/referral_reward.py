# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ReferralReward(models.Model):
    _name = 'referral.reward'
    _description = 'Referral Reward Tracking'
    _order = 'create_date desc'

    doctor_1_id = fields.Many2one(
        'res.partner',
        string='Doctor 1',
        required=True,
        help='Doctor 1 who receives the reward'
    )
    referred_doctor_id = fields.Many2one(
        'res.partner',
        string='Referred Doctor',
        required=True,
        help='Doctor who made the qualifying purchase'
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        help='Order that triggered the reward'
    )
    vials_purchased = fields.Float(
        string='Vials Purchased',
        help='Number of Skydell Platinum vials purchased'
    )
    reward_type = fields.Selection([
        ('promo_vial', 'Promo Vial (Free)'),
    ], string='Reward Type', required=True, default='promo_vial')
    
    product_id = fields.Many2one(
        'product.product',
        string='Reward Product',
        required=True,
        help='Product to grant as reward (Skydell Platinum)'
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        help='Quantity of reward product to grant'
    )
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('granted', 'Granted'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='pending', required=True)
    
    granted_date = fields.Datetime(
        string='Granted Date',
        help='Date when reward was granted'
    )
    granted_by_id = fields.Many2one(
        'res.users',
        string='Granted By',
        help='User who granted the reward'
    )
    
    # Reward order (free order created for Doctor 1)
    reward_order_id = fields.Many2one(
        'sale.order',
        string='Reward Order',
        help='Free order created for Doctor 1'
    )

    def action_grant_reward(self):
        """Grant the promo reward by creating a free order for Doctor 1"""
        for reward in self:
            if reward.state != 'pending':
                raise UserError('Only pending rewards can be granted.')
            
            # Create free sale order for Doctor 1
            order_vals = {
                'partner_id': reward.doctor_1_id.id,
                'date_order': fields.Datetime.now(),
                'state': 'draft',
                'order_line': [(0, 0, {
                    'product_id': reward.product_id.id,
                    'product_uom_qty': reward.quantity,
                    'price_unit': 0.0,  # Free
                    'name': f'Promo Reward: {reward.product_id.name}',
                })],
                'note': f'Promo reward for referring doctor {reward.referred_doctor_id.name}',
            }
            
            reward_order = self.env['sale.order'].create(order_vals)
            
            # Confirm the order
            reward_order.action_confirm()
            
            # Update reward record
            reward.write({
                'state': 'granted',
                'granted_date': fields.Datetime.now(),
                'granted_by_id': self.env.user.id,
                'reward_order_id': reward_order.id,
            })
            
            _logger.info(
                f"[referral.reward] Granted reward {reward.id} to Doctor 1 {reward.doctor_1_id.id}. "
                f"Created order {reward_order.id}"
            )
            
            return {
                'type': 'ir.actions.act_window',
                'name': 'Reward Order',
                'res_model': 'sale.order',
                'res_id': reward_order.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def action_cancel(self):
        """Cancel the reward"""
        for reward in self:
            if reward.state == 'granted':
                raise UserError('Cannot cancel a granted reward.')
            reward.state = 'cancelled'

    @api.model
    def cron_grant_pending_rewards(self):
        """Automated cron to grant pending rewards"""
        pending_rewards = self.search([('state', '=', 'pending')])
        for reward in pending_rewards:
            try:
                reward.action_grant_reward()
            except Exception as e:
                _logger.error(
                    f"[referral.reward] Failed to grant reward {reward.id}: {str(e)}"
                )
