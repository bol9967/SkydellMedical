from odoo import models, api, fields

PEPTIDE_CARRIER_NAME = "Overnight Peptide Delivery"
STANDARD_CARRIER_NAME = "Overnight Biologics Delivery"
STANDARD_SHIPPING_NAME = "Standard Shipping"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    manually_selected_standard_shipping = fields.Boolean(
        string="Manually Selected Standard Shipping",
        default=False,
        help="Track if user manually selected Standard Shipping carrier"
    )

    # -----------------------------------------------------------
    # Utility Methods
    # -----------------------------------------------------------
    def _get_peptide_public_category(self):
        param = self.env['ir.config_parameter'].sudo().get_param('ox_peptide_shipping.peptide_category_id')
        category = False
        if param:
            category = self.env['product.public.category'].browse(int(param))
        if not category:
            category = self.env['product.public.category'].search([('name', '=', 'Peptides')], limit=1)
        return category

    def _is_line_peptide(self, line, peptide_pub_categ):
        prod = line.product_id
        if not prod or not peptide_pub_categ:
            return False
        return peptide_pub_categ in prod.public_categ_ids

    def _compute_peptide_subtotal(self):
        peptide_pub_categ = self._get_peptide_public_category()
        amount = 0.0
        for line in self.order_line:
            # Exclude delivery, payment fee, and discount lines
            if (line.display_type or line.is_delivery or 
                getattr(line, 'is_payment_fee', False) or 
                "Peptide Discount" in (line.name or "")):
                continue
            if self._is_line_peptide(line, peptide_pub_categ):
                amount += line.price_subtotal
        return amount

    def _check_peptide_only(self):
        peptide_pub_categ = self._get_peptide_public_category()
        found_any = False
        for line in self.order_line:
            # Exclude delivery, payment fee, discount, and non-product lines
            if (line.display_type or line.is_delivery or 
                getattr(line, 'is_payment_fee', False) or 
                "Peptide Discount" in (line.name or "")):
                continue
            if not line.product_id:
                continue
            found_any = True
            if not self._is_line_peptide(line, peptide_pub_categ):
                return False
        return bool(found_any)

    def _check_other_only(self):
        peptide_pub_categ = self._get_peptide_public_category()
        found_any = False
        for line in self.order_line:
            # Exclude delivery, payment fee, discount, and non-product lines
            if (line.display_type or line.is_delivery or 
                getattr(line, 'is_payment_fee', False) or 
                "Peptide Discount" in (line.name or "")):
                continue
            if not line.product_id:
                continue
            found_any = True
            if self._is_line_peptide(line, peptide_pub_categ):
                return False
        return bool(found_any)

    def _ensure_carrier(self, name, fixed_price=0.0):
        carrier = self.env["delivery.carrier"].search([("name", "=", name)], limit=1)
        if not carrier:
            carrier = self.env["delivery.carrier"].create({
                "name": name,
                "delivery_type": "fixed",
                "fixed_price": fixed_price,
                "website_published": True,
            })
        return carrier

    # -----------------------------------------------------------
    # Delivery / Discount Helpers
    # -----------------------------------------------------------
    def _remove_existing_delivery_lines(self):
        self.order_line.filtered(lambda l: l.is_delivery).unlink()

    def _add_delivery_amount(self, carrier, amount):
        """Add delivery as last line."""
        self._remove_existing_delivery_lines()
        if not carrier:
            return
        delivery_product = carrier.product_id or self.env.ref("delivery.product_product_delivery", raise_if_not_found=False)
        if not delivery_product:
            delivery_product = self.env["product.product"].create({
                "name": "Delivery",
                "type": "service",
                "list_price": 0.0,
            })
        self.order_line.create({
            "order_id": self.id,
            "name": carrier.name,
            "product_id": delivery_product.id,
            "product_uom_qty": 1,
            "price_unit": amount,
            "is_delivery": True,
        })

    def _remove_peptide_discount_lines(self):
        self.order_line.filtered(lambda l: "Peptide Discount" in (l.name or "")).unlink()

    def _get_discount_settings(self):
        """Get discount enable flag and percentage from settings."""
        enable_discount = self.env['ir.config_parameter'].sudo().get_param(
            'ox_peptide_shipping.enable_peptide_discount', 'True'
        ) == 'True'
        discount_pct = float(self.env['ir.config_parameter'].sudo().get_param(
            'ox_peptide_shipping.peptide_discount_percentage', '10.0'
        ))
        return enable_discount, discount_pct

    def _apply_peptide_discount(self, base_amount):
        if base_amount <= 0:
            return
        enable_discount, discount_pct = self._get_discount_settings()
        if not enable_discount or discount_pct <= 0:
            return
        self._remove_peptide_discount_lines()
        disc_product = self.env["product.product"].search(
            [("name", "=", "Peptide Discount"), ("type", "=", "service")], limit=1
        )
        if not disc_product:
            disc_product = self.env["product.product"].create({
                "name": "Peptide Discount",
                "type": "service",
                "list_price": 0.0,
            })
        discount_amount = base_amount * (discount_pct / 100.0)
        self.env["sale.order.line"].create({
            "order_id": self.id,
            "product_id": disc_product.id,
            "name": f"{discount_pct}% Peptide Discount",
            "product_uom_qty": 1,
            "price_unit": -discount_amount,
        })

    # -----------------------------------------------------------
    # New: Maintain Order Line Sequence
    # -----------------------------------------------------------
    def _reorder_special_lines(self):
        """Ensure discount is second last and delivery last."""
        for order in self:
            lines = order.order_line
            discount_lines = lines.filtered(lambda l: "Peptide Discount" in (l.name or ""))
            delivery_lines = lines.filtered(lambda l: l.is_delivery)
            normal_lines = lines - discount_lines - delivery_lines

            ordered_lines = normal_lines
            if discount_lines:
                ordered_lines += discount_lines
            if delivery_lines:
                ordered_lines += delivery_lines

            # Change only sequence, not full write
            for index, line in enumerate(ordered_lines, start=1):
                line.sequence = index

    # -----------------------------------------------------------
    # Main Logic
    # -----------------------------------------------------------
    def _apply_shipping_and_discount_rules(self):
        for order in self:
            if not order.order_line:
                continue

            # STEP 0 — Check order type first to determine if we should override manual selection
            peptide_only = order._check_peptide_only()
            other_only = order._check_other_only()
            peptide_subtotal = order._compute_peptide_subtotal()
            
            # If order is mixed (has both peptide and non-peptide), always use Overnight Biologics Delivery
            # This overrides any manual Standard Shipping selection
            if not peptide_only and not other_only:
                # Order is mixed - must use Overnight Biologics Delivery
                standard_carrier = order._ensure_carrier(STANDARD_CARRIER_NAME, fixed_price=150.0)
                order._remove_existing_delivery_lines()
                order._remove_peptide_discount_lines()
                order.carrier_id = standard_carrier.id
                order._add_delivery_amount(standard_carrier, 150.0)
                if peptide_subtotal >= 5000:
                    enable_discount, _ = order._get_discount_settings()
                    if enable_discount:
                        order._apply_peptide_discount(peptide_subtotal)
                order.manually_selected_standard_shipping = False  # Clear manual flag
                order._reorder_special_lines()
                continue
            
            # If order is peptide-only and above $5000, always use Overnight Peptide Delivery
            # This overrides any manual Standard Shipping selection
            if peptide_only and order.amount_untaxed >= 5000:
                peptide_carrier = order._ensure_carrier(PEPTIDE_CARRIER_NAME, fixed_price=0.0)
                order._remove_existing_delivery_lines()
                order._remove_peptide_discount_lines()
                order.carrier_id = peptide_carrier.id
                order._add_delivery_amount(peptide_carrier, 0.0)
                enable_discount, _ = order._get_discount_settings()
                if enable_discount:
                    order._apply_peptide_discount(order.amount_untaxed)
                order.manually_selected_standard_shipping = False  # Clear manual flag
                order._reorder_special_lines()
                continue
            
            # STEP 0.5 — Respect manually selected "Standard Shipping" carrier
            # Only respect if it was manually selected AND order type allows it
            # (peptide-only below $5000 or non-peptide only)
            if (order.carrier_id and order.carrier_id.name == STANDARD_SHIPPING_NAME and 
                order.manually_selected_standard_shipping):
                # User manually selected Standard Shipping - respect this choice
                # Only update delivery amount if needed, but don't change the carrier
                existing_delivery = order.order_line.filtered(lambda l: l.is_delivery)
                if not existing_delivery:
                    # Add delivery line with 0 cost for Standard Shipping
                    order._add_delivery_amount(order.carrier_id, 0.0)
                order._reorder_special_lines()
                continue

            # STEP 1 — Respect customer default delivery
            partner_carrier = order.partner_id.property_delivery_carrier_id
            if partner_carrier:
                order._remove_existing_delivery_lines()
                order.carrier_id = partner_carrier.id
                if partner_carrier.delivery_type == "fixed" and partner_carrier.fixed_price > 0:
                    order._add_delivery_amount(partner_carrier, partner_carrier.fixed_price)
                order._reorder_special_lines()
                continue

            # STEP 2 — Peptide vs Standard logic (for remaining cases)
            # Note: Mixed orders and peptide orders above $5000 are already handled in STEP 0
            
            peptide_carrier = order._ensure_carrier(PEPTIDE_CARRIER_NAME, fixed_price=0.0)
            standard_carrier = order._ensure_carrier(STANDARD_CARRIER_NAME, fixed_price=150.0)

            order._remove_existing_delivery_lines()
            order._remove_peptide_discount_lines()

            if peptide_only:
                # For peptide orders below $5000, don't auto-select - let user choose
                # Show shipping method selection (both peptide carrier and standard shipping available)
                if order.amount_untaxed < 5000:
                    # Below $5000: Don't auto-select - allow user to choose between:
                    # - Overnight Peptide Delivery ($50)
                    # - Standard Shipping ($0)
                    # Only set carrier if no carrier is currently selected
                    if not order.carrier_id:
                        # No carrier selected - auto-select peptide carrier as default
                        order.carrier_id = peptide_carrier.id
                        order._add_delivery_amount(peptide_carrier, 50.0)
                        # Clear manual selection flag since we auto-selected
                        order.manually_selected_standard_shipping = False
                    elif order.carrier_id.name == STANDARD_SHIPPING_NAME:
                        # User has Standard Shipping selected - keep it
                        order._add_delivery_amount(order.carrier_id, 0.0)
                        order._reorder_special_lines()
                        continue
                    elif order.carrier_id.name == PEPTIDE_CARRIER_NAME:
                        # User has Peptide Carrier selected - keep it
                        order._add_delivery_amount(peptide_carrier, 50.0)
                        order._reorder_special_lines()
                        continue
                    # If carrier is something else, update to peptide carrier
                    order.carrier_id = peptide_carrier.id
                    order._add_delivery_amount(peptide_carrier, 50.0)
                    order.manually_selected_standard_shipping = False
                else:
                    # Above $5000: Auto-select peptide carrier (only option)
                    order.carrier_id = peptide_carrier.id
                    order._add_delivery_amount(peptide_carrier, 0.0)
                    enable_discount, _ = order._get_discount_settings()
                    if enable_discount:
                        order._apply_peptide_discount(order.amount_untaxed)
                    # Clear manual selection flag since we auto-selected
                    order.manually_selected_standard_shipping = False

            elif other_only:
                order.carrier_id = standard_carrier.id
                order._add_delivery_amount(standard_carrier, 150.0)
                # Clear manual selection flag since we auto-selected
                order.manually_selected_standard_shipping = False

            else:
                # Mixed order - always use standard carrier
                order.carrier_id = standard_carrier.id
                order._add_delivery_amount(standard_carrier, 150.0)
                if peptide_subtotal >= 5000:
                    enable_discount, _ = order._get_discount_settings()
                    if enable_discount:
                        order._apply_peptide_discount(peptide_subtotal)
                # Clear manual selection flag since we auto-selected
                order.manually_selected_standard_shipping = False

            # ✅ Always reorder after changes
            order._reorder_special_lines()

    # -----------------------------------------------------------
    # Overrides
    # -----------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            order._apply_shipping_and_discount_rules()
        return orders

    def write(self, vals):
        res = super().write(vals)
        tracked_fields = {"order_line", "partner_id", "pricelist_id", "currency_id"}
        
        # Track if user manually changed carrier to Standard Shipping
        if "carrier_id" in vals:
            for order in self:
                if order.carrier_id and order.carrier_id.name == STANDARD_SHIPPING_NAME:
                    # User manually selected Standard Shipping
                    order.manually_selected_standard_shipping = True
                else:
                    # User selected different carrier - clear manual flag
                    order.manually_selected_standard_shipping = False
        
        for order in self:
            # ✅ Only apply automatically when still a quotation or cancelled
            if order.state in ("draft", "sent", "cancel") and any(f in vals for f in tracked_fields):
                # Don't override if user manually selected Standard Shipping
                if (order.carrier_id and order.carrier_id.name == STANDARD_SHIPPING_NAME and 
                    order.manually_selected_standard_shipping):
                    # User manually selected Standard Shipping - don't override
                    # Just ensure delivery line exists if needed
                    existing_delivery = order.order_line.filtered(lambda l: l.is_delivery)
                    if not existing_delivery:
                        order._add_delivery_amount(order.carrier_id, 0.0)
                    order._reorder_special_lines()
                    continue
                order._apply_shipping_and_discount_rules()
        return res

    def action_confirm(self):
        # Don't override manually selected Standard Shipping (website or Sales app orders)
        for order in self:
            if (order.carrier_id and order.carrier_id.name == STANDARD_SHIPPING_NAME and 
                order.manually_selected_standard_shipping):
                # User manually selected Standard Shipping - don't override, just ensure delivery line exists
                existing_delivery = order.order_line.filtered(lambda l: l.is_delivery)
                if not existing_delivery:
                    order._add_delivery_amount(order.carrier_id, 0.0)
                order._reorder_special_lines()
                continue
        self._apply_shipping_and_discount_rules()
        return super().action_confirm()

    # -----------------------------------------------------------
    # 🔧 FIXED SIGNATURE BELOW
    # -----------------------------------------------------------
    def _cart_update(self, product_id=None, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """✅ Fixed: match Odoo signature to avoid TypeError"""
        res = super()._cart_update(
            product_id=product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs
        )
        for order in self:
            # Don't override if user manually selected Standard Shipping (website or Sales app)
            if order.carrier_id and order.carrier_id.name == STANDARD_SHIPPING_NAME:
                # User manually selected Standard Shipping - don't override
                # Just ensure delivery line exists if needed
                existing_delivery = order.order_line.filtered(lambda l: l.is_delivery)
                if not existing_delivery:
                    order._add_delivery_amount(order.carrier_id, 0.0)
                order._reorder_special_lines()
                continue
            order._apply_shipping_and_discount_rules()
        return res


# -----------------------------------------------------------
# Delivery Carrier Extension (Backend wizard - kept for compatibility)
# -----------------------------------------------------------
class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    @api.model
    def _get_peptide_public_category(self):
        """Get peptide category from settings."""
        param = self.env['ir.config_parameter'].sudo().get_param('ox_peptide_shipping.peptide_category_id')
        return self.env['product.public.category'].browse(int(param)) if param else False

    @api.model
    def available_carriers(self, partner=None, order=None):
        """✅ Fixed: match Odoo core signature (partner, order) - Backend wizard filtering"""
        carriers = super().available_carriers(partner, order)
        if not order:
            return carriers

        peptide_categ = self._get_peptide_public_category()
        if not peptide_categ:
            return carriers

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
                has_non_peptide = True

        # Peptide only -> show both carriers if below $5000, otherwise peptide only
        if has_peptide and not has_non_peptide:
            order_amount = sum(order_lines.mapped('price_subtotal'))
            if order_amount < 5000:
                # Below $5000: show peptide carrier and standard shipping (3rd option)
                return carriers.filtered(lambda c: c.name in (PEPTIDE_CARRIER_NAME, STANDARD_SHIPPING_NAME))
            else:
                # Above $5000: show only peptide carrier
                return carriers.filtered(lambda c: c.name == PEPTIDE_CARRIER_NAME)
        elif has_peptide and has_non_peptide:
            # Mixed order → standard only
            return carriers.filtered(lambda c: c.name == STANDARD_CARRIER_NAME)
        else:
            # Non-peptide only → standard
            return carriers.filtered(lambda c: c.name == STANDARD_CARRIER_NAME)
