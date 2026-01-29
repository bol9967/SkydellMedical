from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_id = fields.Many2one(
        # Domain will be applied dynamically in _name_search and _search methods
        # based on the "No Negative Stock Sale" setting
        # Static domain only filters by sale_ok, dynamic filtering happens in search methods
        domain=[('sale_ok', '=', True)],
    )
    
    on_hand_qty_display = fields.Char(
        string='On Hand Qty',
        compute='_compute_on_hand_qty_display',
        store=False,
        help='Displays the on-hand quantity for products with stock tracking, or product type for others'
    )
    
    show_on_hand_qty_column = fields.Boolean(
        string='Show On Hand Qty Column',
        compute='_compute_show_on_hand_qty_column',
        store=False,
        help='Technical field to control visibility of On Hand Qty column'
    )
    
    @api.depends()
    def _compute_show_on_hand_qty_column(self):
        """Compute whether to show On Hand Qty column based on settings"""
        show_qty = self.env['ir.config_parameter'].sudo().get_param(
            'ox_sale_negative_stock.show_on_hand_qty_in_sale_order_line', 
            'False'
        ) == 'True'
        for line in self:
            line.show_on_hand_qty_column = show_qty
    
    @api.depends('product_id', 'product_id.type', 'product_id.product_tmpl_id.is_storable', 'product_id.qty_available')
    def _compute_on_hand_qty_display(self):
        """Compute the display value for On Hand Qty column"""
        for line in self:
            if not line.product_id:
                line.on_hand_qty_display = ''
            elif line.product_id.type == 'service':
                line.on_hand_qty_display = 'Service'
            elif line.product_id.type == 'combo':
                line.on_hand_qty_display = 'Combo'
            elif line.product_id.type == 'consu':
                if line.product_id.product_tmpl_id.is_storable:
                    # Show actual quantity for tracked products
                    line.on_hand_qty_display = str(line.product_id.qty_available)
                else:
                    # Show "Not Tracked" for consu without tracking
                    line.on_hand_qty_display = 'Not Tracked'
            else:
                line.on_hand_qty_display = ''

    def _check_product_stock_condition(self, product):
        """Check if product should be hidden based on stock availability"""
        # First, check if this is a website/e-commerce order - if so, skip our validation
        # Website orders should use their own stock control settings
        if self.order_id and self.order_id.website_id:
            return True  # Allow all products for website orders
        
        # Check context for website indicators
        context = self.env.context
        if context.get('website_id') or context.get('from_website'):
            return True  # Allow all products for website context
        
        # Check if we're in a website request (for routes with website=True)
        try:
            from odoo.addons.website.models import ir_http
            website = ir_http.get_request_website()
            if website:
                return True  # Allow all products for website requests
        except (ImportError, AttributeError, TypeError):
            pass  # Not in a web request context or website module not available
        
        # Check if feature is enabled
        if self.env['ir.config_parameter'].sudo().get_param('ox_sale_negative_stock.no_negative_stock_sale', 'False') != 'True':
            return True  # Feature disabled, allow all products
        
        # In Odoo 18: Only check stock for Goods (type='consu') with inventory tracking enabled
        # Hide if: type='consu' AND is_storable=True AND qty_available <= 0
        if product.type == 'consu' and product.product_tmpl_id.is_storable:
            return product.qty_available > 0
        
        # For all other products (service, combo, consu without tracking), always allow
        return True

    @api.constrains('product_id')
    def _check_product_stock(self):
        """Prevent adding products with zero on-hand quantity"""
        for line in self:
            if line.product_id and not self._check_product_stock_condition(line.product_id):
                raise ValidationError(
                    _('Product "%s" has zero on-hand quantity and cannot be added to the sale order.')
                    % line.product_id.display_name
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to prevent adding products with zero stock (batch creation)"""
        # Validate each record before creation
        for vals in vals_list:
            if vals.get('product_id'):
                # Check if this is a website order before validating
                is_website_order = False
                if vals.get('order_id'):
                    order = self.env['sale.order'].browse(vals['order_id'])
                    if order.exists() and order.website_id:
                        is_website_order = True
                
                # Check context for website indicators
                context = self.env.context
                if context.get('website_id') or context.get('from_website'):
                    is_website_order = True
                
                # Check if we're in a website request (for routes with website=True)
                if not is_website_order:
                    try:
                        from odoo.addons.website.models import ir_http
                        website = ir_http.get_request_website()
                        if website:
                            is_website_order = True
                    except (ImportError, AttributeError, TypeError):
                        pass  # Not in a web request context or website module not available
                
                # Skip validation for website orders
                if not is_website_order:
                    product = self.env['product.product'].browse(vals['product_id'])
                    # Create a temporary record to use _check_product_stock_condition
                    # We'll check manually for website context first
                    if self.env['ir.config_parameter'].sudo().get_param('ox_sale_negative_stock.no_negative_stock_sale', 'False') == 'True':
                        if product.type == 'consu' and product.product_tmpl_id.is_storable:
                            if product.qty_available <= 0:
                                raise ValidationError(
                                    _('Product "%s" has zero on-hand quantity and cannot be added to the sale order.')
                                    % product.display_name
                                )
        return super().create(vals_list)

    def write(self, vals):
        """Override write to prevent updating to products with zero stock"""
        if vals.get('product_id'):
            product = self.env['product.product'].browse(vals['product_id'])
            if not self._check_product_stock_condition(product):
                raise ValidationError(
                    _('Product "%s" has zero on-hand quantity and cannot be added to the sale order.')
                    % product.display_name
                )
        return super().write(vals)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Override to clear product if it has zero stock"""
        res = super()._onchange_product_id()
        if self.product_id and not self._check_product_stock_condition(self.product_id):
            # Clear the product to prevent it from being added
            self.product_id = False
            return {
                'warning': {
                    'title': 'No Stock Available',
                    'message': 'This product has zero on-hand quantity and cannot be added to the sale order.',
                }
            }
        return res
