"""Remove exact completed mobile test artifacts; preserve the desktop preview."""
import json
from pathlib import Path
assert env.cr.dbname == 'baseer_reports_qa_20260907'
qa = env(context=dict(env.context, allowed_company_ids=[6]))
entry = qa['baseer.pos.day.entry'].browse(29).exists()
assert entry and entry.state == 'saved' and entry.create_uid.id == 2
assert set(entry.saved_summary_ids.ids) == {229,230}
rows = entry.saved_summary_ids
assert rows.mapped('state') == ['draft','draft']
assert sorted(rows.mapped('amount_gross')) == [120,240]
assert sorted(rows.mapped('customer_count')) == [12,24]
proof=rows.read(['id','business_date','period_scope','customer_count','amount_gross'])
rows.unlink()
# The exact artificial saved transient belongs to this UI acceptance test.
qa.cr.execute('DELETE FROM baseer_pos_day_entry WHERE id=%s AND state=%s',[29,'saved'])
assert qa.cr.rowcount == 1
Path('/mnt/qa-evidence/pos_s2_mobile_save.json').write_text(json.dumps({'passed':True,'records':proof,'cleanup':'exact mobile fixture removed; desktop preview28 retained'},default=str,indent=2))
qa.cr.commit()
print('S2_MOBILE_SAVE_VERIFIED_AND_CLEANED')
