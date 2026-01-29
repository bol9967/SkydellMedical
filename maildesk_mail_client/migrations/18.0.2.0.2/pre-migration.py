import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _table_exists(cr, table_name):
    """Check if DB table exists."""
    cr.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_name = %s
        """,
        (table_name,),
    )
    return bool(cr.fetchone())


def _drop_columns_mail_message(cr):
    """Drop obsolete columns from mail_message."""
    if not _table_exists(cr, "mail_message"):
        _logger.info(
            "maildesk_mail_client: mail_message table missing, skip dropping columns"
        )
        return

    columns_to_drop = [
        "force_show_content",
        "trusted_by_user_id",
        "mailbox_uid",
        "flags",
        "is_read",
        "is_starred",
        "formatted_date",
        "is_draft",
        "preview_text",
        "to_display",
        "cc_display",
        "bcc_display",
        "body_original",
        "avatar_partner_id",
        "external_id",
        "change_key",
        "sender_display_name",
        "search_text",
    ]
    for col in columns_to_drop:
        _logger.info(
            'maildesk_mail_client: dropping column mail_message.%s (if exists)',
            col,
        )
        # IF EXISTS сам по себе безопасен, try/except не нужен
        cr.execute(f'ALTER TABLE mail_message DROP COLUMN IF EXISTS "{col}"')


def _drop_columns_mailbox_account(cr):
    """Drop obsolete columns from mailbox_account."""
    if not _table_exists(cr, "mailbox_account"):
        _logger.info(
            "maildesk_mail_client: mailbox_account table missing, "
            "skip dropping columns"
        )
        return

    columns_to_drop = [
        "notify_enabled",
        "notify_interval_minutes",
        "last_notify_sent",
        "last_outlook_delta_link",
    ]
    for col in columns_to_drop:
        _logger.info(
            'maildesk_mail_client: dropping column mailbox_account.%s (if exists)',
            col,
        )
        cr.execute(f'ALTER TABLE mailbox_account DROP COLUMN IF EXISTS "{col}"')


def _drop_columns_res_partner(cr):
    """Drop obsolete columns from res_partner."""
    if not _table_exists(cr, "res_partner"):
        _logger.info(
            "maildesk_mail_client: res_partner table missing, skip dropping columns"
        )
        return

    _logger.info(
        'maildesk_mail_client: dropping column res_partner.email_count (if exists)'
    )
    cr.execute('ALTER TABLE res_partner DROP COLUMN IF EXISTS "email_count"')


def _drop_m2m_tables(cr):
    """Drop obsolete M2M tables."""
    for table in ("mail_message_tag_rel", "mail_message_folder_rel"):
        _logger.info(
            "maildesk_mail_client: dropping M2M table %s (if exists)", table
        )
        cr.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def _drop_old_tables_and_models(cr):
    """Drop old tables and clean their ir.model.fields metadata."""
    for table in ("mailbox_attachment", "mailbox_sync_job", "mailbox_thread"):
        _logger.info(
            "maildesk_mail_client: dropping table %s (if exists)", table
        )
        cr.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    _logger.info(
        "maildesk_mail_client: cleaning ir_model_fields for old models"
    )
    cr.execute(
        """
        DELETE FROM ir_model_fields
         WHERE model_id IN (
             SELECT id
               FROM ir_model
              WHERE model IN (
                    'mailbox.attachment',
                    'mailbox.sync.job',
                    'mailbox.thread'
              )
         )
        """
    )
    _logger.info(
        "maildesk_mail_client: ir_model_fields cleaned, %s rows removed",
        cr.rowcount,
    )


def _unlink_by_xml_ids(env, xml_ids):
    """Unlink records by XML IDs if they exist (без проглатывания SQL ошибок)."""
    for xmlid in xml_ids:
        rec = env.ref(xmlid, raise_if_not_found=False)
        if rec:
            _logger.info(
                "maildesk_mail_client: unlinking record %s (model: %s, id: %s)",
                xmlid,
                rec._name,
                rec.id,
            )
            rec.sudo().unlink()
        else:
            _logger.info(
                "maildesk_mail_client: XML ID %s not found, nothing to unlink",
                xmlid,
            )


def _delete_old_crons(env):
    """Delete obsolete ir.cron records."""
    xml_ids = [
        "maildesk_mail_client.ir_cron_mailbox_sync",
        "maildesk_mail_client.ir_cron_sync_folder_history",
        "maildesk_mail_client.ir_cron_mailbox_sync_job_runner",
        "maildesk_mail_client.ir_cron_compute_missing_values",
        "maildesk_mail_client.ir_cron_mailbox_discover_folders",
    ]
    _unlink_by_xml_ids(env, xml_ids)


def _delete_old_rules(env):
    """Delete obsolete ir.rule records."""
    xml_ids = [
        "maildesk_mail_client.rule_mailbox_account_user",
        "maildesk_mail_client.rule_mailbox_account_admin",
        "maildesk_mail_client.rule_mailbox_folder_user",
        "maildesk_mail_client.rule_mailbox_folder_admin",
        "maildesk_mail_client.rule_mail_message_user",
        "maildesk_mail_client.rule_mail_message_admin",
    ]
    _unlink_by_xml_ids(env, xml_ids)


def _delete_old_ui(env):
    """Delete obsolete views/actions/menus."""

    # mailbox.attachment
    xml_ids_attachment = [
        "maildesk_mail_client.view_mailbox_attachment_list",
        "maildesk_mail_client.view_mailbox_attachment_form",
        "maildesk_mail_client.view_mailbox_attachment_search",
        "maildesk_mail_client.view_mailbox_attachment_kanban",
        "maildesk_mail_client.action_mailbox_attachment",
        "maildesk_mail_client.menu_mailbox_attachment",
    ]
    _unlink_by_xml_ids(env, xml_ids_attachment)

    # mailbox.sync.job
    xml_ids_sync_job = [
        "maildesk_mail_client.view_mailbox_sync_job_list",
        "maildesk_mail_client.view_mailbox_sync_job_form",
        "maildesk_mail_client.view_mailbox_sync_job_search",
        "maildesk_mail_client.action_mailbox_sync_jobs",
        "maildesk_mail_client.menu_mailbox_sync_jobs",
    ]
    _unlink_by_xml_ids(env, xml_ids_sync_job)


def migrate(cr, version):
    """Post-migration for maildesk_mail_client V2."""
    _logger.info("maildesk_mail_client: post-migration start (version %s)", version)
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("maildesk_mail_client: dropping obsolete columns")
    _drop_columns_mail_message(cr)
    _drop_columns_mailbox_account(cr)
    _drop_columns_res_partner(cr)

    _logger.info("maildesk_mail_client: dropping obsolete M2M tables")
    _drop_m2m_tables(cr)

    _logger.info("maildesk_mail_client: dropping old tables and model metadata")
    _drop_old_tables_and_models(cr)

    _logger.info("maildesk_mail_client: deleting obsolete crons, rules, UI")
    _delete_old_crons(env)
    _delete_old_rules(env)
    _delete_old_ui(env)

    _logger.info("maildesk_mail_client: post-migration done")
