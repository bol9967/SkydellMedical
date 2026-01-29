# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


from odoo import api, fields, models

class MaildeskInlineAttachment(models.Model):
    _name = "maildesk.inline.attachment"
    _description = "MailDesk Inline Attachment (CID Image)"
    _rec_name = "filename"
    _order = "id desc"

    message_uid = fields.Char(
        string="Message UID",
        index=True,
        required=True,
    )
    account_id = fields.Many2one(
        "mailbox.account",
        string="Mailbox Account",
        index=True,
        required=True,
        ondelete="cascade",
    )

    content_id = fields.Char(
        string="Content-ID",
        index=True,
        help="CID without < >",
    )
    filename = fields.Char(
        string="Filename",
    )
    mimetype = fields.Char(
        string="MIME Type",
    )

    data = fields.Binary(
        string="Payload",
        attachment=False,
    )
    create_date = fields.Datetime(readonly=True)

    @api.model
    def create_from_part(self, account_id, message_uid, part_index, content_id, filename, mimetype, payload):
        clean_cid = (content_id or "").strip("<>").strip()

        return self.create({
            "message_uid": str(message_uid),
            "account_id": account_id,
            "content_id": clean_cid,
            "filename": filename or f"inline_{part_index}",
            "mimetype": mimetype or "application/octet-stream",
            "data": payload,
        })

    @api.model
    def gc_old(self, days=7):
        limit_date = fields.Datetime.now() - fields.Date.to_timedelta(days)
        old = self.search([("create_date", "<", limit_date)])
        old.unlink()
        return len(old)
