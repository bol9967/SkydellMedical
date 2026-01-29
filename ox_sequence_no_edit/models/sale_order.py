from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    edit_sequence = fields.Boolean(
        string='Sales Order Edit Sequence',
        compute='_eg_compute_for_edit_sequence'
    )

    def _eg_compute_for_edit_sequence(self):
        for rec in self:
            if self.env.user.has_group("ox_sequence_no_edit.sale_edit_sequence_group"):
                rec.edit_sequence = False
            else:
                rec.edit_sequence = True

    def write(self, vals):
        # 🚨 Prevent duplicate SO numbers
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

        # Handle sequence change
        if 'name' in vals:
            for so in self:
                old_name = old_names.get(so.id)
                if old_name and old_name != so.name:
                    # 1️⃣ Log on SO
                    so.message_post(
                        body=f"Sale Order sequence updated from {old_name} to {so.name} by {self.env.user.name}"
                    )

                    # 2️⃣ Update linked invoices via lines
                    invoices = self.env['account.move'].search([
                        ('move_type', 'in', ('out_invoice', 'out_refund')),
                        ('invoice_line_ids.sale_line_ids.order_id', '=', so.id)
                    ])
                    if invoices:
                        invoices._compute_invoice_origin()
                        for inv in invoices:
                            inv.message_post(
                                body=f"Invoice Origin recomputed to {inv.invoice_origin} "
                                     f"due to Sale Order sequence change by {self.env.user.name}"
                            )

                    # 3️⃣ Update stock pickings
                    pickings = self.env['stock.picking'].search([
                        ('origin', 'ilike', old_name)
                    ])
                    for picking in pickings:
                        new_origin = picking.origin.replace(old_name, so.name) if picking.origin else so.name
                        picking.write({'origin': new_origin})
                        picking.message_post(
                            body=f"Origin updated from {old_name} to {so.name} "
                                 f"due to Sale Order sequence change by {self.env.user.name}"
                        )
                    # 4️⃣ Update Procurement Group name (no chatter on group itself)
                    if so.procurement_group_id and so.procurement_group_id.name != so.name:
                        old_group_name = so.procurement_group_id.name
                        so.procurement_group_id.write({'name': so.name}
                        )
        return res
