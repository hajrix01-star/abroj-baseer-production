"""Keep prior internal BWork access while disabling portal-facing switches."""


def migrate(cr, version):
    # New Boolean columns default to True to preserve every existing internal
    # user's previous BWork access. External accounts cannot call the service,
    # and their displayed checkboxes must also be off after an upgrade.
    cr.execute('''
        UPDATE res_users
        SET bwork_chat_view = FALSE, bwork_chat_send = FALSE,
            bwork_media = FALSE, bwork_group_create = FALSE,
            bwork_group_manage = FALSE, bwork_task_view = FALSE,
            bwork_task_manage = FALSE
        WHERE share = TRUE
    ''')
