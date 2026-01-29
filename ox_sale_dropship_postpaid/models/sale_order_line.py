# -*- coding: utf-8 -*-

from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Block dropship procurement until:
           - A payment.transaction is done OR
           - An invoice is paid / in payment.

        Works with:
        - Product-level Dropship route
        - Category-level Dropship route
        - Line-level route, if set
        """

        # Preserve native behavior if something explicitly disables procurement
        if self._context.get("skip_procurement"):
            return True

        # If context flag is set (from payment_transaction), bypass payment check
        if self._context.get("force_allow_dropship_procurement"):
            # Allow all dropship lines to proceed with procurement
            return super(SaleOrderLine, self)._action_launch_stock_rule(
                previous_product_uom_qty=previous_product_uom_qty
            )

        Route = self.env['stock.route']
        dropship_route = Route.search([('name', 'ilike', 'dropship')], limit=1)

        allowed_lines = self.env['sale.order.line']

        for line in self:
            order = line.order_id

            # ---------- Detect if this is a dropship line ----------
            is_dropship = False
            if dropship_route:
                if line.route_id and line.route_id.id == dropship_route.id:
                    is_dropship = True
                elif dropship_route in line.product_id.route_ids:
                    is_dropship = True
                elif line.product_id.categ_id and dropship_route in line.product_id.categ_id.route_ids:
                    is_dropship = True

            # Non-dropship lines → let Odoo handle normally
            if not is_dropship:
                allowed_lines |= line
                continue

            # ---------- Condition A: Payment transaction done ----------
            # Flush to ensure we see the latest transaction state
            self.env.flush_all()
            has_done_tx = bool(order.transaction_ids.filtered(lambda t: t.state == 'done'))

            # ---------- Condition B: Any invoice paid / in_payment ----------
            invoice_paid = bool(order.invoice_ids.filtered(
                lambda inv: inv.state == 'posted' and inv.payment_state in ('paid', 'in_payment')
            ))

            # If either condition is true → allow procurement
            if has_done_tx or invoice_paid:
                allowed_lines |= line
            else:
                # Dropship, but not yet paid → skip for now
                continue

        if not allowed_lines:
            # Nothing to procure at this time
            return True

        # Call the original implementation only on allowed lines
        return super(SaleOrderLine, allowed_lines)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty
        )
