# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""
Compatibility module for ox_peptide_shipping.
Ensures payment fee lines are excluded from peptide shipping logic.
This module extends ox_peptide_shipping methods to exclude payment fee lines
from peptide detection and carrier filtering logic.
"""

from odoo import models, api


class SaleOrder(models.Model):
    """Extend ox_peptide_shipping to exclude payment fee lines."""
    _inherit = 'sale.order'

    def _check_peptide_only(self):
        """Override to exclude payment fee lines from peptide check."""
        # Call parent method but ensure payment fee lines are excluded
        # The parent filters: display_type, is_delivery, "Peptide Discount"
        # We need to also exclude is_payment_fee lines
        peptide_pub_categ = self._get_peptide_public_category()
        found_any = False
        for line in self.order_line:
            # Exclude payment fee lines (in addition to parent's exclusions)
            if (line.display_type or line.is_delivery or line.is_payment_fee or 
                "Peptide Discount" in (line.name or "")):
                continue
            if not line.product_id:
                continue
            found_any = True
            if not self._is_line_peptide(line, peptide_pub_categ):
                return False
        return bool(found_any)

    def _check_other_only(self):
        """Override to exclude payment fee lines from other check."""
        # Call parent method but ensure payment fee lines are excluded
        peptide_pub_categ = self._get_peptide_public_category()
        found_any = False
        for line in self.order_line:
            # Exclude payment fee lines (in addition to parent's exclusions)
            if (line.display_type or line.is_delivery or line.is_payment_fee or 
                "Peptide Discount" in (line.name or "")):
                continue
            if not line.product_id:
                continue
            found_any = True
            if self._is_line_peptide(line, peptide_pub_categ):
                return False
        return bool(found_any)

    def _compute_peptide_subtotal(self):
        """Override to exclude payment fee lines from peptide subtotal."""
        peptide_pub_categ = self._get_peptide_public_category()
        amount = 0.0
        for line in self.order_line:
            # Exclude payment fee lines (in addition to parent's exclusions)
            if (line.display_type or line.is_delivery or line.is_payment_fee or 
                "Peptide Discount" in (line.name or "")):
                continue
            if self._is_line_peptide(line, peptide_pub_categ):
                amount += line.price_subtotal
        return amount


class DeliveryCarrier(models.Model):
    """Extend ox_peptide_shipping delivery carrier to exclude payment fee lines."""
    _inherit = 'delivery.carrier'

    def _is_available_for_order(self, order):
        """Override to exclude payment fee lines from availability check."""
        result = super()._is_available_for_order(order)
        if not result:
            return False

        peptide_categ = self._get_peptide_category()
        if not peptide_categ:
            return result

        # Ignore delivery + discount + payment fee lines
        order_lines = order.order_line.filtered(
            lambda l: not l.is_delivery
            and not l.is_payment_fee  # Exclude payment fee lines
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
                has_non_peptide = True

        # Peptide only -> show both carriers if below $5000, otherwise peptide only
        if has_peptide and not has_non_peptide:
            order_amount = sum(order_lines.mapped('price_subtotal'))
            if order_amount < 5000:
                return self.name in ("Overnight Peptide Delivery", "Standard Shipping")
            else:
                return self.name == "Overnight Peptide Delivery"

        # Mixed -> standard only
        if has_peptide and has_non_peptide:
            return self.name == "Overnight Biologics Delivery"

        # Non-peptide only -> standard
        if not has_peptide:
            return self.name == "Overnight Biologics Delivery"

        return result

    @api.model
    def available_carriers(self, partner=None, order=None):
        """Override to exclude payment fee lines from carrier filtering."""
        carriers = super().available_carriers(partner, order)
        if not order:
            return carriers

        peptide_categ = self._get_peptide_category()
        if not peptide_categ:
            return carriers

        # Ignore delivery + discount + payment fee lines
        order_lines = order.order_line.filtered(
            lambda l: not l.is_delivery
            and not l.is_payment_fee  # Exclude payment fee lines
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
                has_non_peptide = True

        # Choose which carriers should be offered
        if has_peptide and not has_non_peptide:
            order_amount = sum(order_lines.mapped('price_subtotal'))
            if order_amount < 5000:
                return carriers.filtered(lambda c: c.name in ("Overnight Peptide Delivery", "Standard Shipping"))
            else:
                return carriers.filtered(lambda c: c.name == "Overnight Peptide Delivery")
        elif has_peptide and has_non_peptide:
            return carriers.filtered(lambda c: c.name == "Overnight Biologics Delivery")
        else:
            return carriers.filtered(lambda c: c.name == "Overnight Biologics Delivery")

