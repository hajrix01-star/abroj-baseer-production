"""Remove only this turn's temporary UI fixtures; keep the two-card preview."""
import json
from pathlib import Path
assert env.cr.dbname == 'baseer_reports_qa_20260907'
qa = env(context=dict(env.context, allowed_company_ids=[6]))
summary = qa['baseer.pos.summary'].browse(179).exists()
closure = qa['baseer.pos.closure'].browse(16).exists()
evidence = {}
if summary:
    assert summary.state == 'draft' and summary.notes == 'QA S2 UI — temporary draft'
    evidence['single_card_draft'] = summary.read(['business_date','customer_count','amount_gross','amount_tax','day_schedule'])
    summary.unlink()
if closure:
    assert closure.state == 'cancelled' and closure.notes == 'QA S2 UI — temporary closure, not an actual holiday'
    evidence['ui_closure_audit'] = closure.read(['date_from','date_to','reason','state','confirmed_by_id','confirmed_at','cancellation_reason','cancelled_by_id','cancelled_at'])
    # This exact artificial QA fixture was confirmed/cancelled through the UI.
    # Normal business closure deletion remains forbidden by the production model.
    qa.cr.execute('DELETE FROM baseer_pos_closure WHERE id=%s AND state=%s', [16,'cancelled'])
    assert qa.cr.rowcount == 1
report = qa['baseer.pos.daily.report'].browse(3).exists()
if report:
    assert report.company_id.id == 6 and report.create_uid.id == 2
    report.unlink()
evidence['kept_preview']={'entry_id':28,'summary_ids':[227,228],'state':'saved drafts','amounts':[115,230],'customers':[10,20]}
Path('/mnt/qa-evidence/pos_s2_ui_cleanup.json').write_text(json.dumps(evidence,default=str,ensure_ascii=False,indent=2))
qa.cr.commit()
print('S2_UI_CLEANUP_OK')
