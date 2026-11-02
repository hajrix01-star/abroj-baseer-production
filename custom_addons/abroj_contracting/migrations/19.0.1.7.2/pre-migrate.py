def migrate(cr, version):
    """Remove the stray DB-only view abroj_contracting.project_form_budget_lines_tab.

    It referenced abroj_budget_line_ids (defined in abroj_project_dashboard), which
    breaks view validation when abroj_contracting loads. The tab now lives in
    abroj_project_dashboard. Idempotent; touches only that one record.
    """
    cr.execute("""
        SELECT id, res_id FROM ir_model_data
         WHERE module = 'abroj_contracting' AND name = 'project_form_budget_lines_tab'
           AND model = 'ir.ui.view'
    """)
    for imd_id, view_id in cr.fetchall():
        if view_id:
            cr.execute("DELETE FROM ir_ui_view WHERE inherit_id = %s", [view_id])
            cr.execute("DELETE FROM ir_ui_view WHERE id = %s", [view_id])
        cr.execute("DELETE FROM ir_model_data WHERE id = %s", [imd_id])
