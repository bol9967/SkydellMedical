# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class TermsConditions(models.Model):
    """Model to store Terms & Conditions versions"""
    _name = 'terms.conditions'
    _description = 'Terms & Conditions'
    _order = 'version desc, create_date desc'

    name = fields.Char(string="Title", required=True)
    version = fields.Char(string="Version", required=True, help="e.g., 1.0, 2.0, etc.")
    content = fields.Html(string="Terms & Conditions Content", required=True, sanitize=False)
    active = fields.Boolean(string="Active", default=True, help="Only active terms can be accepted")
    effective_date = fields.Date(string="Effective Date", required=True, default=fields.Date.today)
    is_current = fields.Boolean(string="Current Version", default=False, help="The current version users must accept")
    
    acceptance_count = fields.Integer(string="Acceptance Count", compute='_compute_acceptance_count', store=False)
    
    _sql_constraints = [
        ('version_unique', 'UNIQUE(version)', 'Version must be unique!')
    ]

    @api.depends('acceptance_ids')
    def _compute_acceptance_count(self):
        for record in self:
            record.acceptance_count = len(record.acceptance_ids)

    @api.model
    def get_current_terms(self):
        """Get the current active terms that users must accept"""
        return self.search([
            ('active', '=', True),
            ('is_current', '=', True)
        ], limit=1, order='effective_date desc')

    def action_set_current(self):
        """Set this version as current and deactivate others"""
        self.ensure_one()
        # Deactivate all other versions
        self.search([('id', '!=', self.id)]).write({'is_current': False})
        # Set this as current
        self.write({'is_current': True, 'active': True})
        return True

    def unlink(self):
        """Prevent deletion if there are any acceptances"""
        for record in self:
            if record.acceptance_ids:
                raise ValidationError(
                    _("Cannot delete Terms & Conditions that have been accepted. "
                      "This version has %d acceptance(s). "
                      "You can deactivate it instead by unchecking the 'Active' field.") 
                    % len(record.acceptance_ids)
                )
        return super(TermsConditions, self).unlink()

    def write(self, vals):
        """Override write to track content changes"""
        # Track content changes before updating
        if 'content' in vals:
            new_content = vals.get('content', '')
            for record in self:
                old_content = record.content or ''
                if old_content != new_content:
                    # Create content history record
                    self.env['terms.content.history'].sudo().create({
                        'terms_id': record.id,
                        'old_content': old_content,
                        'new_content': new_content,
                        'changed_by': self.env.user.id,
                        'change_date': fields.Datetime.now(),
                    })
        
        return super(TermsConditions, self).write(vals)

    acceptance_ids = fields.One2many('terms.acceptance', 'terms_id', string="Acceptances")
    content_history_ids = fields.One2many('terms.content.history', 'terms_id', string="Content History")


class TermsAcceptance(models.Model):
    """Model to store Terms & Conditions acceptance audit trail"""
    _name = 'terms.acceptance'
    _description = 'Terms & Conditions Acceptance'
    _order = 'acceptance_date desc'

    terms_id = fields.Many2one('terms.conditions', string="Terms & Conditions", required=True, ondelete='cascade')
    terms_version = fields.Char(string="Version", related='terms_id.version', store=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string="Partner", required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string="User", compute='_compute_user_id', store=True, readonly=True)
    
    @api.depends('partner_id', 'partner_id.user_ids')
    def _compute_user_id(self):
        for record in self:
            if record.partner_id and record.partner_id.user_ids:
                record.user_id = record.partner_id.user_ids[0]
            else:
                record.user_id = False
    
    # Audit Trail Fields
    acceptance_date = fields.Datetime(string="Acceptance Date (UTC)", required=True, default=fields.Datetime.now)
    ip_address = fields.Char(string="IP Address", required=True)
    digital_signature = fields.Binary(string="Digital Signature", required=True, help="Digital signature image (base64)")
    digital_signature_name = fields.Char(string="Signature Name", help="Name associated with the signature")
    
    # Additional metadata
    user_agent = fields.Text(string="User Agent", help="Browser and device information")
    acceptance_method = fields.Selection([
        ('signup', 'During Signup'),
        ('manual', 'Manual Acceptance'),
        ('update', 'Terms Update'),
    ], string="Acceptance Method", default='signup', required=True)
    
    # Signed content snapshot - preserves the exact content that was signed
    signed_content = fields.Html(string="Signed Content", readonly=True, sanitize=False,
                                 help="The exact Terms & Conditions content that was signed by the user")

    @api.model
    def create_acceptance(self, terms_id, partner_id, signature_image, signature_name, ip_address, user_agent=None, method='signup'):
        """Create a new terms acceptance record with audit trail and content snapshot"""
        terms = self.env['terms.conditions'].browse(terms_id)
        if not terms.exists():
            raise ValidationError("Terms & Conditions not found")
        
        if not signature_image:
            raise ValidationError("Digital signature is required")
        
        # Decode base64 if it's a data URL
        if isinstance(signature_image, str) and signature_image.startswith('data:image'):
            # Extract base64 part from data URL
            signature_image = signature_image.split(',', 1)[1] if ',' in signature_image else signature_image
        
        # Store the content snapshot at the time of signing
        signed_content = terms.content or ''
        
        return self.create({
            'terms_id': terms_id,
            'partner_id': partner_id,
            'digital_signature': signature_image,
            'digital_signature_name': signature_name.strip() if signature_name else '',
            'ip_address': ip_address,
            'user_agent': user_agent,
            'acceptance_method': method,
            'acceptance_date': fields.Datetime.now(),
            'signed_content': signed_content,  # Preserve the exact content that was signed
        })


class TermsContentHistory(models.Model):
    """Model to track changes made to Terms & Conditions content"""
    _name = 'terms.content.history'
    _description = 'Terms & Conditions Content History'
    _order = 'change_date desc'

    terms_id = fields.Many2one('terms.conditions', string="Terms & Conditions", required=True, ondelete='cascade')
    terms_version = fields.Char(string="Version", related='terms_id.version', store=True, readonly=True)
    old_content = fields.Html(string="Previous Content", readonly=True, sanitize=False)
    new_content = fields.Html(string="New Content", readonly=True, sanitize=False)
    changed_by = fields.Many2one('res.users', string="Changed By", required=True, readonly=True)
    change_date = fields.Datetime(string="Change Date", required=True, default=fields.Datetime.now, readonly=True)
    change_summary = fields.Text(string="Change Summary", help="Optional summary of what was changed")
