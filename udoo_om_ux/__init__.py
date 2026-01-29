# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from . import models


def _post_init_hook(env):
    xmlids = [
        'mail.mail_activity_data_email',
        'mail.mail_activity_data_call',
        'mail.mail_activity_data_meeting',
        'mail.mail_activity_data_todo',
        'mail.mail_activity_data_upload_document',
        'mail.mail_activity_data_warning',
    ]
    recs = env['mail.activity.type']
    for xid in xmlids:
        rec = env.ref(xid, raise_if_not_found=False)
        if rec:
            recs |= rec
    recs.write({'keep_done': True})


def _uninstall_hook(env):
    env['web_editor.assets'].reset_omux_light()
    env['web_editor.assets'].reset_omux_dark()

    # Optional: Omux Color Scheme
    ocs_assets = env['ir.asset'].search([('path', 'ilike', 'omux_color_scheme/static/set')])
    if ocs_assets:
        ocs_assets.unlink()
