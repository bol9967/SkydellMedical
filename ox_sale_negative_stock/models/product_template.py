from odoo import api, models
from odoo.osv import expression


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _check_domain_has_sale_context(self, domain):
        """Check if domain indicates we're in a sale context"""
        if not domain:
            return False
        
        # Check for sale_ok in domain
        for item in domain:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                if item[0] == 'sale_ok':
                    return True
            elif isinstance(item, (list, tuple)):
                # Recursively check nested domains
                if self._check_domain_has_sale_context(item):
                    return True
        return False

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """Override search to filter products with zero stock when searching from sale.order.line
        
        In Odoo 18, when clicking "Search More..." on product_id field in sale.order.line,
        the search view shows product.template records. We need to filter templates where:
        - type='consu' AND is_storable=True AND all variants have qty_available <= 0
        """
        # IMPORTANT: Only apply our logic when we're CERTAIN we're in a sale.order.line context
        # We must be very strict to avoid affecting other models (purchase.order, etc.)
        context = self.env.context
        has_sale_context = False
        is_website_context = False
        
        # First, check if we're in a website/e-commerce context - if so, skip our logic
        # Website orders have website_id set, and website_sale uses website context
        if context.get('website_id') or context.get('from_website'):
            is_website_context = True
        elif context.get('active_model') == 'sale.order' and context.get('active_id'):
            # Check if the order is a website order
            try:
                order = self.env['sale.order'].browse(context.get('active_id'))
                if order.exists() and order.website_id:
                    is_website_context = True
            except Exception:
                pass  # If we can't check, assume not website context
        elif context.get('active_model') == 'sale.order.line' and context.get('active_id'):
            # Check if the order line belongs to a website order
            try:
                line = self.env['sale.order.line'].browse(context.get('active_id'))
                if line.exists() and line.order_id and line.order_id.website_id:
                    is_website_context = True
            except Exception:
                pass  # If we can't check, assume not website context
        
        # Only proceed if NOT in website context
        if not is_website_context:
            # STRICT CHECK: Only apply if we have BOTH:
            # 1. Domain contains sale_ok (indicating sale context)
            # 2. Context indicates sale.order.line (to be extra safe)
            
            # Method 1: Check domain for sale_ok (from field domain)
            domain_has_sale_ok = False
            if domain:
                domain_has_sale_ok = self._check_domain_has_sale_context(domain)
            
            # Method 2: Check context - must be sale.order.line
            context_is_sale_line = (context.get('active_model') == 'sale.order.line')
            
            # Only apply if BOTH conditions are met (very strict)
            has_sale_context = domain_has_sale_ok and context_is_sale_line
        
        # Apply filter only when in sale context and feature is enabled
        # Only filter if "No Negative Stock Sale" is enabled AND "Display Zero Stock in Search" is disabled
        no_negative_stock_enabled = self.env['ir.config_parameter'].sudo().get_param('ox_sale_negative_stock.no_negative_stock_sale', 'False') == 'True'
        display_in_search = self.env['ir.config_parameter'].sudo().get_param('ox_sale_negative_stock.display_zero_stock_in_search', 'False') == 'True'
        
        if has_sale_context and no_negative_stock_enabled and not display_in_search:
            # Filter logic: Only filter when type='consu' AND is_storable=True
            # For service, combo, and consu with is_storable=False: don't apply filter (show all)
            # For consu with is_storable=True: only show if qty_available > 0
            # 
            # Domain structure: Show products where:
            # - type='service' OR
            # - type='combo' OR
            # - (type='consu' AND is_storable != True) OR
            # - (type='consu' AND is_storable=True AND qty_available > 0)
            # 
            # Use expression.OR to properly combine multiple OR conditions
            inclusion_domain = expression.OR([
                [('type', '=', 'service')],  # Show all service products (no filter)
                [('type', '=', 'combo')],  # Show all combo products (no filter)
                expression.AND([
                    [('type', '=', 'consu')],
                    [('is_storable', '!=', True)]
                ]),  # Show all consu with is_storable=False or None (no filter)
                expression.AND([
                    [('type', '=', 'consu')],
                    [('is_storable', '=', True)],
                    [('product_variant_ids.qty_available', '>', 0)]
                ])  # Only for consu with is_storable=True: require stock > 0
            ])
            
            # Combine with existing domain
            # Use Odoo's expression.AND to properly combine domains
            # This ensures: (existing_domain) AND (our_filter)
            if domain:
                domain = expression.AND([domain, inclusion_domain])
            else:
                domain = inclusion_domain
        
        # Ensure order is a string or None (handle unexpected formats)
        if order is not None and not isinstance(order, str):
            order = None
        
        return super()._search(domain, offset, limit, order)
