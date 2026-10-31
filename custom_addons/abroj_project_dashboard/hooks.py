def backfill_duration(cr):
    """Preserve legacy deadlines and derive inclusive durations where possible."""
    cr.execute("""
        UPDATE project_task
           SET x_abroj_duration_days = CASE
               WHEN x_abroj_date_start IS NOT NULL AND date_deadline IS NOT NULL
               THEN GREATEST(1, date_deadline::date - x_abroj_date_start + 1)
               ELSE 1 END
    """)


def post_init_hook(env):
    backfill_duration(env.cr)
