from odoo import models, fields
from odoo.exceptions import ValidationError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    stock_picking_edit_sequence = fields.Boolean(string='Warehouse Edit Sequence',
                                                 compute='_eg_compute_for_Warehouse_edit_sequence')

    def _eg_compute_for_Warehouse_edit_sequence(self):
        for rec in self:
            if self.env.user.has_group("ox_sequence_no_edit.warehouse_edit_sequence_group"):
                rec.stock_picking_edit_sequence = False
            else:
                rec.stock_picking_edit_sequence = True

    def write(self, vals):
        if 'name' in vals:
            stock_id = self.search([('id', '!=', self.id), ('name', '=', vals['name'])])
            if stock_id:
                raise ValidationError('The {} Sequence Number already exits'.format(vals['name']))
        return super(StockPicking, self).write(vals)
