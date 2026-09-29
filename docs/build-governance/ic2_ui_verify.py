"""Read-only accounting verification of actual IC2 browser actions."""
import json
from pathlib import Path
assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
batch_meta = json.loads(Path('/mnt/qa-evidence/ic2-ui-fixtures-batch.json').read_text())
summary_meta = json.loads(Path('/mnt/qa-evidence/ic2-ui-fixtures-summary.json').read_text())
batch = env['baseer.purchase.batch'].browse(batch_meta['batch_id'])
row, neighbor = batch.line_ids.sorted('id')
assert row.baseer_cancelled and row.move_id.state == 'cancel'
assert row.payment_id.state == 'canceled' and row.payment_id.move_id.state == 'cancel'
assert neighbor.move_id.state == 'posted' and neighbor.payment_id.move_id.state == 'posted'
assert batch.amount_gross == 500 and row.gross_amount == 500
summary = env['baseer.pos.summary'].browse(summary_meta['summary_ui']['id'])
replacement = summary.replacement_id
assert summary.state == 'cancelled' and replacement.state == 'approved'
assert summary.amount_gross == 690 and replacement.amount_gross == 790 and replacement.customer_count == 15
assert len(summary.reversal_move_ids) == len(summary._native_moves())
for move in summary._native_moves():
    reverse = summary.reversal_move_ids.filtered(lambda item: item.reversed_entry_id == move)
    assert len(reverse) == 1 and reverse.state == 'posted'
    for account in move.line_ids.account_id:
        assert round(sum((move | reverse).line_ids.filtered(lambda line: line.account_id == account).mapped('balance')), 2) == 0
assert env['baseer.financial.correction.audit'].search_count([('move_id', '=', row.move_id.id), ('operation', '=', 'cancel')]) == 1
assert env['baseer.financial.correction.audit'].search_count([('move_id', '=', summary.move_id.id), ('operation', '=', 'edit')]) == 1
report = {'status': 'PASS', 'database': env.cr.dbname, 'read_only': True, 'main_untouched': True,
          'batch': 'Cancelled invoice/payment retained; active neighbor and batch total500',
          'summary': 'Original690 exactly reversed by account; replacement790/15customers approved; one audit'}
Path('/mnt/qa-evidence/ic2-ui-accounting.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
env.cr.rollback()
