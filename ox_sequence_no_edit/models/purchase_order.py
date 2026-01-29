from odoo import models, fields
from odoo.exceptions import ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    purchase_edit_sequence = fields.Boolean(
        string='Purchase Order Edit Sequence',
        compute='_compute_for_hide_edit_sequence_purchase_'
    )

    def _compute_for_hide_edit_sequence_purchase_(self):
        for rec in self:
            if self.env.user.has_group("ox_sequence_no_edit.purchase_edit_sequence_group"):
                rec.purchase_edit_sequence = False
            else:
                rec.purchase_edit_sequence = True

    def write(self, vals):
        # 🚨 Prevent duplicate sequence numbers
        if 'name' in vals:
            existing = self.search([
                ('id', '!=', self.id),
                ('name', '=', vals['name'])
            ])
            if existing:
                raise ValidationError(
                    f"The sequence number {vals['name']} already exists"
                )

        old_names = {rec.id: rec.name for rec in self}
        res = super().write(vals)

        # After write, handle sequence changes
        if 'name' in vals:
            for po in self:
                old_name = old_names.get(po.id)
                if old_name and old_name != po.name:
                    # 1️⃣ Log on PO
                    po.message_post(
                        body=f"Purchase Order sequence updated from {old_name} to {po.name} by {self.env.user.name}"
                    )

                    # 2️⃣ Update linked Vendor Bills/Refunds
                    moves_rel = self.env['account.move'].search([
                        ('move_type', 'in', ('in_invoice', 'in_refund')),
                        ('invoice_line_ids.purchase_line_id.order_id', '=', po.id)
                    ])
                    moves_text = self.env['account.move'].search([
                        ('move_type', 'in', ('in_invoice', 'in_refund')),
                        ('invoice_origin', 'ilike', old_name)
                    ])
                    moves = (moves_rel | moves_text).sudo()

                    if moves:
                        moves._compute_invoice_origin()
                        for move in moves:
                            move.message_post(
                                body=f"Invoice Origin recomputed to {move.invoice_origin} "
                                     f"due to Purchase Order sequence change by {self.env.user.name}"
                            )

                    # 3️⃣ Update linked Stock Pickings via group_id
                    if po.group_id:
                        pickings = self.env['stock.picking'].search([
                            ('group_id', '=', po.group_id.id)
                        ])
                        for picking in pickings:
                            old_origin = picking.origin or ""
                            if old_name in old_origin:
                                new_origin = old_origin.replace(old_name, po.name)
                            elif not old_origin:
                                new_origin = po.name
                            else:
                                # If origin is something stale like "P00002", force latest PO.name
                                new_origin = po.name

                            if new_origin != old_origin:
                                picking.write({'origin': new_origin})
                                picking.message_post(
                                    body=f"Origin updated from {old_origin or '(empty)'} "
                                         f"to {new_origin} due to Purchase Order sequence change "
                                         f"by {self.env.user.name}"
                                )
                            
                            # 4️⃣ Update Procurement Group name (no chatter, because model has no mail.thread)
                            if po.group_id and po.group_id.name != po.name:
                                old_group_name = po.group_id.name
                                po.group_id.write({'name': po.name}
                                )
        return res
