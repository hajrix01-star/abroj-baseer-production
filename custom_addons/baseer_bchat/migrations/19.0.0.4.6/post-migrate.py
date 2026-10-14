"""Keep prior internal BChat access while disabling portal-facing switches."""


def migrate(cr, version):
    # New Boolean columns default to True to preserve every existing internal
    # user's previous BChat access. External accounts cannot call the service,
    # and their displayed checkboxes must also be off after an upgrade.
    cr.execute('''
        UPDATE res_users
        SET bchat_chat_view = FALSE, bchat_chat_send = FALSE,
            bchat_media = FALSE, bchat_group_create = FALSE,
            bchat_group_manage = FALSE, bchat_task_view = FALSE,
            bchat_task_manage = FALSE
        WHERE share = TRUE
    ''')
