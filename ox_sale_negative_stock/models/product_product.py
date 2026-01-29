from odoo import api, models
from odoo.osv import expression


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=None, order=None, access_rights_uid=None):
        """Override name_search to filter products with zero stock when searching from sale.order.line
        
        This method is called for:
        1. Dropdown autocomplete in Many2one fields
        2. Initial search results
        """
        # Check if we're in a sale context (NOT website/e-commerce)
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
                for item in domain:
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        if item[0] == 'sale_ok':
                            domain_has_sale_ok = True
                            break
                    elif isinstance(item, str):
                        continue
            
            # Method 2: Check context - must be sale.order.line
            context_is_sale_line = (context.get('active_model') == 'sale.order.line')
            
            # Only apply if BOTH conditions are met (very strict)
            has_sale_context = domain_has_sale_ok and context_is_sale_line
        
        # Apply filter when in sale context and feature is enabled
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
                    [('product_tmpl_id.is_storable', '!=', True)]
                ]),  # Show all consu with is_storable=False or None (no filter)
                expression.AND([
                    [('type', '=', 'consu')],
                    [('product_tmpl_id.is_storable', '=', True)],
                    [('qty_available', '>', 0)]
                ])  # Only for consu with is_storable=True: require stock > 0
            ])
            
            # Combine with existing domain
            # Use Odoo's expression.AND to properly combine domains
            # This ensures: (existing_domain) AND (our_filter)
            if domain:
                domain = expression.AND([domain, inclusion_domain])
            else:
                domain = inclusion_domain
        
        # Call parent's _name_search method
        # Since _name_search is dynamically added by Odoo, we'll implement the logic ourselves
        # Search with the filtered domain and return results in the expected format
        if name:
            # If name is provided, add it to the domain
            name_domain = [('name', operator, name)]
            if domain:
                domain = expression.AND([domain, name_domain])
            else:
                domain = name_domain
        
        # Search with the domain
        records = self.search(domain or [], limit=limit, order=order)
        # Return in the format expected by _name_search: [(id, display_name), ...]
        return [(r.id, r.display_name) for r in records]
