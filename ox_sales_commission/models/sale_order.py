
from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    commission_tracking_ids = fields.One2many('commission.tracking', 'sale_order_id', 
                                               string='Commission Tracking')
    
    manual_manager_commission_percentage = fields.Float(
        string='Manual Manager Commission %',
        help="Override manager commission percentage for this specific order. Leave empty to use default from commission plan.",
        tracking=True
    )
    
    def action_confirm(self):
        res = super().action_confirm()
        self._create_commission_tracking()
        return res
    
    def _get_commission_base_amount(self, order):
        """Calculate commission base amount excluding delivery and payment fees.
        
        Commission is calculated on untaxed amount excluding:
        - Delivery/shipping lines (is_delivery = True)
        - Payment processing fee lines (is_payment_fee = True)
        - Display lines (section/note lines)
        """
        # Filter out delivery, payment fee, and display lines
        commission_lines = order.order_line.filtered(
            lambda line: not line.is_delivery 
            and not getattr(line, 'is_payment_fee', False)
            and not line.display_type
        )
        # Sum price_subtotal (untaxed amount) for commission-eligible lines
        return sum(commission_lines.mapped('price_subtotal'))
    
    def _get_net_commission_base(self, order, salesperson_commission_amount=0.0):
        """Calculate net commission base: Order Amount - (Product Cost + Salesperson Commission).
        
        Net Commission Base = Order Amount (excluding delivery/payment fees) 
                             - (Product Cost Price (excluding delivery/payment fees) + Salesperson Commission)
        
        This represents: Order Amount - Total Costs (Product Cost + Salesperson Commission)
        """
        # Get order amount excluding delivery and payment fees (same as base commission)
        order_amount = self._get_commission_base_amount(order)
        
        # Filter out delivery, payment fee, and display lines
        product_lines = order.order_line.filtered(
            lambda line: not line.is_delivery 
            and not getattr(line, 'is_payment_fee', False)
            and not line.display_type
            and line.product_id
        )
        
        # Calculate total product cost price (standard_price * quantity for each line)
        # Only for product lines (excluding delivery/payment fees)
        # Need to handle UOM conversion: standard_price is in product's standard UOM
        total_cost = 0.0
        for line in product_lines:
            if not line.product_id:
                continue
            # Get standard price (cost) - this is in product's standard UOM
            cost_price = line.product_id.standard_price or 0.0
            
            # Convert quantity to product's standard UOM if needed
            if line.product_uom and line.product_id.uom_id:
                # Convert quantity from line UOM to product standard UOM
                quantity_in_std_uom = line.product_uom._compute_quantity(
                    line.product_uom_qty, 
                    line.product_id.uom_id
                )
            else:
                quantity_in_std_uom = line.product_uom_qty
            
            total_cost += cost_price * quantity_in_std_uom
        
        # Net commission base = Order Amount - (Product Cost + Salesperson Commission)
        net_base = order_amount - (total_cost + salesperson_commission_amount)
        return net_base
    
    def _create_commission_tracking(self):
        for order in self:
            # Calculate commission base amount (excluding delivery and payment fees)
            commission_base_amount = self._get_commission_base_amount(order)
            
            # First, check for active Admin commission plans
            # Admin plans apply to ALL sales orders regardless of salesperson
            admin_plan = self.env['commission.plan'].search([
                ('commission_plan_type', '=', 'admin'),
                ('state', '=', 'approved'),
                ('target_period_start', '<=', order.date_order.date()),
                ('target_period_end', '>=', order.date_order.date())
            ], limit=1)
            
            if admin_plan:
                # Create commission for admin person
                # Admin commissions use a flat rate (first_order_commission) or can be a fixed percentage
                admin_commission_vals = {
                    'sale_order_id': order.id,
                    'salesperson_id': admin_plan.admin_person_id.id,
                    'commission_plan_id': admin_plan.id,
                    'order_amount': commission_base_amount,
                    'commission_type': 'admin',
                    # For admin, use first_order_commission as the standard rate
                    'commission_percentage': admin_plan.first_order_commission,
                }
                
                # Create admin commission tracking with elevated rights
                self.env['commission.tracking'].sudo().create(admin_commission_vals)
            
            # Then, check for Sales Team commission plans (original logic)
            if not order.user_id:
                continue
                
            # Find active Sales Team commission plan for this salesperson
            sales_team_plan = self.env['commission.plan'].search([
                ('commission_plan_type', '=', 'sales_team'),
                ('salesperson_ids', 'in', order.user_id.id),
                ('state', '=', 'approved'),
                ('target_period_start', '<=', order.date_order.date()),
                ('target_period_end', '>=', order.date_order.date())
            ], limit=1)
            
            if not sales_team_plan:
                continue
            
            # Check if first order for this salesperson and customer
            is_first = self._is_customer_first_order(order.partner_id.id, order.user_id.id)
            
            commission_type = 'first_order' if is_first else 'residual'
                
            commission_vals = {
                'sale_order_id': order.id,
                'salesperson_id': order.user_id.id,
                'commission_plan_id': sales_team_plan.id,
                'order_amount': commission_base_amount,
                'commission_type': commission_type,
                'commission_percentage': sales_team_plan.first_order_commission if is_first else sales_team_plan.residual_commission,
            }
            
            # Create commission tracking with elevated rights to avoid access errors
            # for regular sales users during confirmation.
            salesperson_commission_record = self.env['commission.tracking'].sudo().create(commission_vals)
            salesperson_commission_amount = salesperson_commission_record.commission_amount or 0.0
            
            # Create commission for Sales Team Manager if applicable
            # Manager gets commission on sales made by their team members
            # Manager uses the same commission plan as the salesperson, but with manager rates
            # Priority logic:
            # 1. If plan has manager rates defined (> 0), use them (even if global setting is off)
            # 2. If plan has no manager rates, check global setting
            # 3. Manual override always takes precedence
            
            # Check if plan has manager commission rates defined
            # Old plans may not have these fields set (will be 0.0)
            has_manager_rates = (
                sales_team_plan.manager_first_order_commission and 
                sales_team_plan.manager_first_order_commission > 0 and
                sales_team_plan.manager_residual_commission and 
                sales_team_plan.manager_residual_commission > 0
            )
            
            # Check global setting (only used if plan doesn't have rates defined)
            enable_manager_commission = self.env['ir.config_parameter'].sudo().get_param(
                'ox_sales_commission.enable_manager_commission', 'True'
            ) == 'True'
            
            # Only create manager commission if:
            # 1. Plan has manager rates defined (plan-level override), OR
            # 2. Global setting is enabled AND plan doesn't have rates, OR
            # 3. Manual override is set on the order
            should_create_manager_commission = (
                has_manager_rates or  # Plan has rates defined (always use them)
                (enable_manager_commission and not has_manager_rates) or  # Global setting on, plan has no rates
                order.manual_manager_commission_percentage  # Manual override
            )
            
            if (should_create_manager_commission and 
                order.team_id and 
                order.team_id.user_id and 
                order.team_id.user_id.id != order.user_id.id):
                
                # Only proceed if plan has manager rates defined OR manual override is set
                if has_manager_rates or order.manual_manager_commission_percentage:
                    # Check if this is first order for manager (based on customer and team)
                    is_manager_first = self._is_manager_first_order(order.partner_id.id, order.team_id.id)
                    
                    # Determine manager commission percentage
                    if order.manual_manager_commission_percentage:
                        # Use manual override if set
                        manager_commission_pct = order.manual_manager_commission_percentage
                        is_manual_override = True
                    else:
                        # Use plan default
                        if is_manager_first:
                            manager_commission_pct = sales_team_plan.manager_first_order_commission
                        else:
                            manager_commission_pct = sales_team_plan.manager_residual_commission
                        is_manual_override = False
                    
                    # Only create if percentage is valid (not None/False)
                    if manager_commission_pct is not None and manager_commission_pct is not False:
                        manager_commission_type = 'manager'
                        
                        # Get commission type from plan (default to 'base' if not set for old plans)
                        commission_calc_type = getattr(sales_team_plan, 'manager_commission_type', 'base') or 'base'
                        
                        # Calculate manager commission base based on commission type
                        # Manual override uses the same base calculation as the plan type
                        if commission_calc_type == 'net':
                            # Net Commission: product cost price + salesperson commission
                            manager_commission_base = self._get_net_commission_base(
                                order, 
                                salesperson_commission_amount
                            )
                        else:
                            # Base Commission: order amount excluding delivery/payment fees
                            manager_commission_base = self._get_commission_base_amount(order)
                        
                        manager_commission_vals = {
                            'sale_order_id': order.id,
                            'salesperson_id': order.team_id.user_id.id,  # Manager
                            'commission_plan_id': sales_team_plan.id,  # Use the same plan as salesperson
                            'order_amount': manager_commission_base,
                            'commission_type': manager_commission_type,
                            'commission_percentage': manager_commission_pct,
                            'is_manual_override': is_manual_override,
                        }
                        
                        # Create manager commission tracking
                        self.env['commission.tracking'].sudo().create(manager_commission_vals)
    
    def _is_customer_first_order(self, partner_id, user_id):
        previous_orders = self.search_count([
            ('partner_id', '=', partner_id),
            ('user_id', '=', user_id),
            ('state', 'in', ['sale', 'done']),
            ('id', '!=', self.id)
        ])
        return previous_orders == 0
    
    def _is_salesperson_first_order(self, user_id):
        previous_orders = self.search_count([
            ('user_id', '=', user_id),
            ('state', 'in', ['sale', 'done']),
            ('id', '!=', self.id)
        ])
        return previous_orders == 0
    
    def _is_manager_first_order(self, partner_id, team_id):
        """Check if this is the first order from this customer for this sales team"""
        previous_orders = self.search_count([
            ('partner_id', '=', partner_id),
            ('team_id', '=', team_id),
            ('state', 'in', ['sale', 'done']),
            ('id', '!=', self.id)
        ])
        return previous_orders == 0