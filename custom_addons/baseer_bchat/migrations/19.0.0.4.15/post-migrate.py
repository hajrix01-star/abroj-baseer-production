"""Preserve the old combined media grant exactly once for existing accounts."""


def migrate(cr, version):
    cr.execute('''
        UPDATE res_users
        SET bchat_media_view = CASE WHEN share THEN FALSE ELSE COALESCE(bchat_media, FALSE) END,
            bchat_media_download = CASE WHEN share THEN FALSE ELSE COALESCE(bchat_media, FALSE) END,
            bchat_media_rights_migrated = TRUE
        WHERE NOT COALESCE(bchat_media_rights_migrated, FALSE)
    ''')
