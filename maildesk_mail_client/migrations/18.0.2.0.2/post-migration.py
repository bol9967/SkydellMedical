import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _column_exists(cr, table_name, column_name):
    """Check if DB column exists."""
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """Pre-migration: safe data moves only."""
    _logger.info("maildesk_mail_client: pre-migration start (version %s)", version)
    env = api.Environment(cr, SUPERUSER_ID, {})

    try:
        has_old = _column_exists(cr, "mailbox_account", "last_outlook_delta_link")
        has_new = _column_exists(cr, "mailbox_account", "outlook_delta_link")

        if has_old and has_new:
            _logger.info(
                "maildesk_mail_client: migrating last_outlook_delta_link -> outlook_delta_link"
            )
            cr.execute(
                """
                UPDATE mailbox_account
                   SET outlook_delta_link = last_outlook_delta_link
                 WHERE (outlook_delta_link IS NULL OR outlook_delta_link = '')
                   AND last_outlook_delta_link IS NOT NULL
                   AND last_outlook_delta_link <> ''
                """
            )
            _logger.info(
                "maildesk_mail_client: outlook_delta_link updated for %s rows",
                cr.rowcount,
            )
        else:
            _logger.info(
                "maildesk_mail_client: delta link migration skipped "
                "(old=%s, new=%s)",
                has_old,
                has_new,
            )
    except Exception:
        _logger.exception(
            "maildesk_mail_client: error while migrating outlook delta link, "
            "migration continues"
        )

    _logger.info("maildesk_mail_client: pre-migration done")
