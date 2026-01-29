from odoo import models, api

PEPTIDE_CARRIER_NAME = "Overnight Peptide Delivery"
STANDARD_CARRIER_NAME = "Overnight Biologics Delivery"
STANDARD_SHIPPING_NAME = "Standard Shipping"


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    @api.model
    def _get_peptide_category(self):
        """Return configured peptide eCommerce category (public category)."""
        param = self.env['ir.config_parameter'].sudo().get_param('ox_peptide_shipping.peptide_category_id')
        return self.env['product.public.category'].browse(int(param)) if param else False

    # --- WEBSITE visibility (kept as you wrote) -------------------------------
    def _is_available_for_order(self, order):
        """Control website visibility of carriers based on peptide vs mixed cart."""
        # Keep core checks
        result = super()._is_available_for_order(order)
        if not result:
            return False

        peptide_categ = self._get_peptide_category()
        if not peptide_categ:
            return result  # if not configured, don't filter further

        # Ignore delivery + discount + payment fee lines
        order_lines = order.order_line.filtered(
            lambda l: not l.is_delivery
            and not getattr(l, 'is_payment_fee', False)
            and l.product_id
            and "Peptide Discount" not in (l.name or "")
        )

        has_peptide = False
        has_non_peptide = False
        for line in order_lines:
            categs = line.product_id.public_categ_ids
            if peptide_categ in categs:
                has_peptide = True
            else:
                # includes uncategorized or non-peptide
                has_non_peptide = True

        # Peptide only -> show both carriers if below $5000, otherwise peptide only
        if has_peptide and not has_non_peptide:
            # Calculate order amount (excluding delivery and discount)
            order_amount = sum(order_lines.mapped('price_subtotal'))
            if order_amount < 5000:
                # Below $5000: show peptide carrier and standard shipping (3rd option)
                return self.name in (PEPTIDE_CARRIER_NAME, STANDARD_SHIPPING_NAME)
            else:
                # Above $5000: show only peptide carrier
                return self.name == PEPTIDE_CARRIER_NAME

        # Mixed -> standard only
        if has_peptide and has_non_peptide:
            return self.name == STANDARD_CARRIER_NAME

        # Non-peptide only -> standard
        if not has_peptide:
            return self.name == STANDARD_CARRIER_NAME

        return result

    # --- BACKEND wizard filtering (this is where the error came from) ---------
    @api.model
    def available_carriers(self, partner=None, order=None):
        """
        Match core signature: available_carriers(partner, order)
        Used by delivery wizard: choose.delivery.carrier
        """
        carriers = super().available_carriers(partner, order)
        if not order:
            return carriers  # nothing to filter without an order

        peptide_categ = self._get_peptide_category()
        if not peptide_categ:
            return carriers  # not configured -> no extra filtering

        # Ignore delivery + discount + payment fee lines
        order_lines = order.order_line.filtered(
            lambda l: not l.is_delivery
            and not getattr(l, 'is_payment_fee', False)
            and l.product_id
            and "Peptide Discount" not in (l.name or "")
        )

        has_peptide = False
        has_non_peptide = False
        # Empty or non-peptide categories count as non-peptide
        for line in order_lines:
            categs = line.product_id.public_categ_ids
            if peptide_categ in categs:
                has_peptide = True
            else:
                has_non_peptide = True

        # Choose which carriers should be offered
        if has_peptide and not has_non_peptide:
            # Peptide only -> show both carriers if below $5000, otherwise peptide only
            order_amount = sum(order_lines.mapped('price_subtotal'))
            if order_amount < 5000:
                # Below $5000: show peptide carrier and standard shipping (3rd option)
                return carriers.filtered(lambda c: c.name in (PEPTIDE_CARRIER_NAME, STANDARD_SHIPPING_NAME))
            else:
                # Above $5000: show only peptide carrier
                return carriers.filtered(lambda c: c.name == PEPTIDE_CARRIER_NAME)
        elif has_peptide and has_non_peptide:
            # Mixed
            return carriers.filtered(lambda c: c.name == STANDARD_CARRIER_NAME)
        else:
            # Non-peptide only
            return carriers.filtered(lambda c: c.name == STANDARD_CARRIER_NAME)
