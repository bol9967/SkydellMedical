from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
from odoo.osv import expression
import logging
_logger = logging.getLogger(__name__)

class CommissionTracking(models.Model):
    _name = 'commission.tracking'
    _description = 'Commission Tracking'
    _rec_name = 'sale_order_id'
    
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', required=True)
    salesperson_id = fields.Many2one('res.users', string='Commission User', required=True)
    commission_plan_id = fields.Many2one('commission.plan', string='Commission Plan', required=True)
    disbursement_frequency = fields.Selection(related='commission_plan_id.disbursement_frequency', 
                                              string='Disbursement Frequency', store=True)
    customer_id = fields.Many2one('res.partner', string='Customer', 
                                   related='sale_order_id.partner_id', store=True)
    
    order_amount = fields.Monetary(string='Order Amount', currency_field='currency_id')
    commission_type = fields.Selection([
        ('first_order', 'First Order'),
        ('residual', 'Residual'),
        ('admin', 'Admin'),
        ('manager', 'Manager')
    ], string='Commission Type', required=True)
    
    commission_percentage = fields.Float(string='Commission %', aggregator=False)
    is_manual_override = fields.Boolean(
        string='Manual Override',
        default=False,
        help="Indicates if the commission percentage was manually adjusted"
    )
    commission_amount = fields.Monetary(string='Commission Amount', 
                                        currency_field='currency_id', compute='_compute_commission_amount', store=True)
    
    invoice_id = fields.Many2one('account.move', string='Customer Invoice')
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state',
        string='Invoice Payment Status',
        store=True,
    )
    invoice_paid_date = fields.Date(string='Invoice Paid Date')
    display_date = fields.Date(string='Date', compute='_compute_display_date', store=True)
   
    vendor_bill_id = fields.Many2one('account.move', string='Vendor Bill')
    vendor_bill_state = fields.Selection(related='vendor_bill_id.state', 
                                         string='Vendor Bill Status')
    
    disbursement_date = fields.Date(string='Disbursement Date')
    is_paid = fields.Boolean(string='Is Paid', default=False)
    
    currency_id = fields.Many2one('res.currency', string='Currency', 
                                   default=lambda self: self.env.company.currency_id)
    
    # ------------------------------------------------------------------
    # Team Leader visibility helpers (own + team commissions)
    # ------------------------------------------------------------------

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """
        Extend search to allow Commission Team Leaders to see:
          - their own commissions
          - commissions of users in the sales teams they lead

        Hierarchy:
          - Commission Admin  : sees all (native rule + bypass here)
          - Commission TL     : own + team members (this override)
          - Commission User   : own only (native rule)
        """
        # Determine the original user (handle sudo environments correctly)
        original_uid = self.env.context.get("uid") or self.env.uid
        if original_uid and original_uid != self.env.user.id:
            user = self.env["res.users"].browse(original_uid)
        else:
            user = self.env.user

        is_commission_admin = user.has_group("ox_sales_commission.group_commission_sale_admin")
        is_commission_user = user.has_group("ox_sales_commission.group_commission_sale_user")
        is_commission_team_leader = user.has_group("ox_sales_commission.group_commission_team_leader")

        # Admins: keep standard behavior (they already have an \"admin sees all\" rule)
        if is_commission_admin:
            return super()._search(domain, offset=offset, limit=limit, order=order)

        # Only extend behavior for users that are both commission users and
        # explicitly marked as Commission Team Leaders
        if is_commission_user and is_commission_team_leader:
            # Sales team leader logic reuses crm.team structure
            teams = self.env["crm.team"].search([("user_id", "=", user.id)])
            if teams:
                # Collect active team member user IDs
                member_user_ids = (
                    teams.mapped("crm_team_member_ids")
                    .filtered("active")
                    .mapped("user_id")
                    .filtered(lambda u: u)
                    .ids
                )

                if member_user_ids:
                    # Own commissions (respect record rules)
                    own_query = super()._search(
                        expression.AND([domain, [("salesperson_id", "=", user.id)]]),
                        offset=0,
                        limit=0,
                        order=False,
                    )
                    # Team member commissions (bypass record rules with sudo)
                    team_query = super(CommissionTracking, self.sudo())._search(
                        expression.AND([domain, [("salesperson_id", "in", member_user_ids)]]),
                        offset=0,
                        limit=0,
                        order=False,
                    )

                    own_ids = list(own_query) if own_query else []
                    team_ids = list(team_query) if team_query else []
                    result_ids = list(set(own_ids) | set(team_ids))

                    if result_ids:
                        return self.browse(result_ids)._as_query(order or self._order)
                    return self.browse([])._as_query(order or self._order)

            # If user is TL but has no team members, or teams missing,
            # fall back to native behavior (own commissions via rule).
            return super()._search(domain, offset=offset, limit=limit, order=order)

        # Non-TL users: keep native behavior
        return super()._search(domain, offset=offset, limit=limit, order=order)

    # ------------------------------------------------------------------
    # Smart button helpers
    # ------------------------------------------------------------------
    def _open_record_action(self, model, res_id):
        """Return a simple ir.actions.act_window opening a specific record.

        Using a minimal action avoids depending on external action XML ids and
        works across installations.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': 'View',
            'res_model': model,
            'view_mode': 'form',
            'target': 'current',
            'res_id': res_id,
        }

    def action_open_vendor_bill(self):
        self.ensure_one()
        if not self.vendor_bill_id:
            return False
        return self._open_record_action('account.move', self.vendor_bill_id.id)

    def action_open_customer_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return self._open_record_action('account.move', self.invoice_id.id)

    def action_open_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return self._open_record_action('sale.order', self.sale_order_id.id)

    def read(self, fields=None, load="_classic_read"):
        """
        Override read so that Commission Team Leaders can actually read
        the commission lines for their team members, even though the
        base record rule only allows \"own\" commissions.

        Strategy:
          - Identify IDs that belong to:
              * own commissions
              * team member commissions
              * other users
          - Read own + team member records with sudo() (after verifying
            salesperson ownership via SQL), skip the rest.
        """
        user = self.env.user

        is_commission_admin = user.has_group("ox_sales_commission.group_commission_sale_admin")
        is_commission_user = user.has_group("ox_sales_commission.group_commission_sale_user")
        is_commission_team_leader = user.has_group("ox_sales_commission.group_commission_team_leader")

        # Admin or non-commission users: use standard behavior
        if is_commission_admin or not is_commission_user or not is_commission_team_leader:
            return super().read(fields, load)

        # Reuse sales team hierarchy via crm.team
        teams = self.env["crm.team"].search([("user_id", "=", user.id)])
        if not teams or not self.ids:
            # No teams or no records -> default behavior
            return super().read(fields, load)

        member_user_ids = (
            teams.mapped("crm_team_member_ids")
            .filtered("active")
            .mapped("user_id")
            .filtered(lambda u: u and u.id)
            .ids
        )

        if not member_user_ids:
            # TL with no active members: falls back to own-only via rule
            return super().read(fields, load)

        # Map commission.tracking -> salesperson_id via SQL to avoid any
        # recursive ORM calls that could re-trigger access logic.
        self.env.cr.execute(
            "SELECT id, salesperson_id FROM commission_tracking WHERE id = ANY(%s)", (self.ids,)
        )
        user_id_map = {row[0]: row[1] for row in self.env.cr.fetchall()}

        team_member_record_ids = [
            rid for rid in self.ids if user_id_map.get(rid) in member_user_ids
        ]
        own_record_ids = [rid for rid in self.ids if user_id_map.get(rid) == user.id]
        other_record_ids = [
            rid for rid in self.ids if rid not in team_member_record_ids and rid not in own_record_ids
        ]

        result = []

        if team_member_record_ids:
            team_member_records = self.browse(team_member_record_ids)
            result.extend(
                super(CommissionTracking, team_member_records.sudo()).read(fields, load)
            )

        if own_record_ids:
            own_records = self.browse(own_record_ids)
            result.extend(super(CommissionTracking, own_records.sudo()).read(fields, load))

        # Skip other users' commissions entirely
        if other_record_ids:
            _logger.info(
                "[commission.tracking.read] Skipping %s non-accessible records for user %s",
                len(other_record_ids),
                user.id,
            )

        # Preserve original order if we have results
        if result:
            id_order = {rid: idx for idx, rid in enumerate(self.ids)}
            return sorted(result, key=lambda r: id_order.get(r["id"], len(self.ids)))

        return result

    # @api.model
    # def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
    #     """Augment grouped results with a consolidated invoice payment status.

    #     We do NOT override the native aggregated value of invoice_payment_state
    #     (which is a count). Instead, we populate a separate summary field that
    #     the list view can display only for grouped rows.
    #     """
    #     res = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

    #     needs_summary = (
    #         'invoice_payment_state_summary' in fields
    #         or any(f.startswith('invoice_payment_state_summary') for f in fields)
    #         or 'invoice_payment_state' in fields
    #         or any(f.startswith('invoice_payment_state:') for f in fields)
    #     )

    #     if needs_summary:
    #         for line in res:
    #             group_domain = line.get('__domain')
    #             if not group_domain:
    #                 continue
    #             records = self.search(group_domain)
    #             states = set(records.mapped('invoice_payment_state'))

    #             # Determine consolidated state: paid if all paid; partial if any partial; else not_paid
    #             if states == {'paid'}:
    #                 summary = 'paid'
    #             elif 'partial' in states and 'paid' in states and len(states) == 2:
    #                 summary = 'partial'
    #             elif 'partial' in states:
    #                 summary = 'partial'
    #             else:
    #                 summary = 'not_paid'

    #             line['invoice_payment_state_summary'] = summary

    #     return res
    
    def _compute_invoice_payment_state_summary(self):
        for record in self:
            record.invoice_payment_state_summary = 0

    @api.onchange('commission_percentage')
    def _onchange_commission_percentage(self):
        """Automatically set is_manual_override when commission percentage is manually changed for manager commissions"""
        if self.commission_type == 'manager' and self.commission_percentage:
            self.is_manual_override = True
    
    def write(self, vals):
        """Override write to automatically set is_manual_override when commission_percentage is changed for manager commissions"""
        if 'commission_percentage' in vals:
            for record in self:
                if record.commission_type == 'manager':
                    if record.vendor_bill_id:
                        raise UserError("Cannot modify commission percentage for manager commissions once a vendor bill has been created.")
                    # Only allow editing if no vendor bill has been created
                    vals['is_manual_override'] = True
        return super().write(vals)

    @api.depends('order_amount', 'commission_percentage')
    def _compute_commission_amount(self):
        for record in self:
            record.commission_amount = (record.order_amount * record.commission_percentage) / 100
    
    @api.depends('invoice_paid_date', 'invoice_id', 'invoice_id.invoice_date', 'sale_order_id', 'sale_order_id.date_order')
    def _compute_display_date(self):
        for record in self:
            if record.invoice_paid_date:
                record.display_date = record.invoice_paid_date
            elif record.invoice_id and record.invoice_id.invoice_date:
                record.display_date = record.invoice_id.invoice_date
            elif record.sale_order_id and record.sale_order_id.date_order:
                # Convert datetime to date
                try:
                    record.display_date = record.sale_order_id.date_order.date()
                except Exception:
                    record.display_date = False
            else:
                record.display_date = False
                     
    # Add method to check if customer is first-time buyer
    def _is_first_order(self, customer_id, salesperson_id):
        previous_orders = self.env['sale.order'].search_count([
            ('partner_id', '=', customer_id),
            ('user_id', '=', salesperson_id),
            ('state', 'in', ['sale', 'done']),
            ('id', '!=', self.sale_order_id.id)
        ])
        return previous_orders == 0
    

    @api.model
    def cron_generate_vendor_bills(self):
        """Cron job to generate vendor bills based on disbursement frequency"""
        today = fields.Date.today()

        # find the active commission plans for testing date override
        active_commission_plan = self.env['commission.plan'].search([
            ('state', '=', 'approved'),
            ('target_period_start', '<=', today),
            ('target_period_end', '>=', today)
        ], limit=1)
        
        if active_commission_plan and active_commission_plan.cron_run_date:
            today = active_commission_plan.cron_run_date

        _logger.info(f"Today: {today},weekday: {today.weekday()},day: {today.day}")
        
        # Get all unpaid commissions with paid invoices
        unpaid_commissions = self.search([
            ('is_paid', '=', False),
            ('invoice_payment_state', '=', 'paid'),
            ('vendor_bill_id', '=', False)
        ])
        
        # Group by salesperson, commission plan, and disbursement frequency
        # This handles both admin and sales team commissions
        commission_groups = {}
        for commission in unpaid_commissions:
            # Key groups by plan type (admin vs sales_team)
            # For sales_team: first_order and residual go in same bill
            # For admin: all admin commissions go in same bill
            key = (
                commission.salesperson_id.id,
                commission.commission_plan_id.disbursement_frequency,
                commission.commission_plan_id.commission_plan_type
            )
            if key not in commission_groups:
                commission_groups[key] = []
            commission_groups[key].append(commission)
        
        # Create vendor bills
        for (salesperson_id, frequency, plan_type), commissions in commission_groups.items():
            if self._should_generate_bill(frequency, today):
                self._create_vendor_bill(salesperson_id, commissions, plan_type)
                
    def _should_generate_bill(self, frequency, date):
        """Check if bill should be generated based on frequency"""
        if frequency == 'weekly':
            return date.weekday() == 0  # Monday
        elif frequency == 'biweekly':
            # Generate on 1st and 15th of month
            return date.day in [1, 15]
        elif frequency == 'monthly':
            return date.day == 1
        return False
        
    def _create_vendor_bill(self, salesperson_id, commissions, plan_type='sales_team'):
        """Create vendor bill for commission payment
        
        Args:
            salesperson_id: ID of the user receiving commission
            commissions: recordset of commission.tracking records
            plan_type: commission plan type ('admin' or 'sales_team')
        """
        salesperson = self.env['res.users'].browse(salesperson_id)
        
        # Determine reference based on plan type
        if plan_type == 'admin':
            ref = f"Admin Commission Payment - {salesperson.name}"
        else:
            ref = f"Sales Commission Payment - {salesperson.name}"
        
        # Create vendor bill
        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': salesperson.partner_id.id,
            'invoice_date': fields.Date.today(),
            'ref': ref,
            'invoice_line_ids': []
        }
        
        for commission in commissions:
            # Create descriptive line name based on commission type
            if commission.commission_type == 'admin':
                line_name = f"Admin Commission for SO {commission.sale_order_id.name}"
            elif commission.commission_type == 'first_order':
                line_name = f"First Order Commission for SO {commission.sale_order_id.name}"
            elif commission.commission_type == 'manager':
                line_name = f"Manager Commission for SO {commission.sale_order_id.name}"
            else:
                line_name = f"Residual Commission for SO {commission.sale_order_id.name}"
            
            line_vals = (0, 0, {
                'name': line_name,
                'quantity': 1,
                'price_unit': commission.commission_amount,
                'account_id': self._get_commission_expense_account().id,
            })
            bill_vals['invoice_line_ids'].append(line_vals)
        
        vendor_bill = self.env['account.move'].create(bill_vals)
        
        # Link vendor bill to commissions
        for commission in commissions:
            commission.vendor_bill_id = vendor_bill.id
            commission.disbursement_date = fields.Date.today()
        
        return vendor_bill
        
    def _get_commission_expense_account(self):
        """Get or create commission expense account"""
        # In Odoo 18, account.account uses company_ids (Many2many) instead of company_id
        # Using standard commission expense account code 6220
        account = self.env['account.account'].search([
            ('code', '=', '6220'),
            ('company_ids', 'in', [self.env.company.id])
        ], limit=1)
        
        if not account:
            account = self.env['account.account'].create({
                'code': '6220',
                'name': 'Commission Expense',
                'account_type': 'expense_direct_cost',
                'company_ids': [(6, 0, [self.env.company.id])],
            })
        return account