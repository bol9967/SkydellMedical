from odoo import models, fields

class AccountMove(models.Model):
    _inherit = "account.move"

    partner_npi = fields.Char(
        string="NPI# ",
        related="partner_id.npi_number",
        store=False,
        readonly=True,
    )

    shipping_npi = fields.Char(
        string="Shipping NPI",
        related="partner_shipping_id.npi_number",
        store=False,
        readonly=True,
    )
