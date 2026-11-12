"""Shared matrix presentation for owner-summary exports; no money arithmetic."""


def owner_print_rows(periods):
    totals, channels, groups = {}, {}, {}

    def add(target, key, value, period_key, kind):
        row = target.setdefault(key, {
            'key': key, 'label': value['label'], 'kind': kind, 'amounts': {},
        })
        row['amounts'][period_key] = {
            'amount': value['amount'], 'negative': value['negative'],
            'percentage': value.get('percentage'),
        }
        return row

    for period in periods:
        period_key = period['key']
        for total in period['totals']:
            kind = 'section net_income' if total['key'] == 'difference' else 'section'
            add(totals, total['key'], total, period_key, kind)
        for channel in period['channels']:
            add(channels, 'channel:' + channel['key'], channel, period_key, 'account')
        for group in period['outflows']:
            key = 'outflow:' + group['key']
            row = add(groups, key, group, period_key, 'result account')
            details = row.setdefault('children', {})
            for detail in group['rows']:
                add(details, key + ':' + detail['key'], detail, period_key, 'channel')
    rows = [totals['incoming_total'], *channels.values(), totals['cash_total']]
    for group in groups.values():
        rows.append(group)
        rows.extend(group['children'].values())
    rows.append(totals['difference'])
    return rows


def owner_snapshot_has_figures(snapshot, company_id):
    """Reject partial snapshots before presenting or exporting figures."""
    if not isinstance(snapshot, dict) or snapshot.get('company_id') != company_id:
        return False
    periods = snapshot.get('periods')
    if not isinstance(periods, list) or not periods:
        return False
    for period in periods:
        if not isinstance(period, dict) or not all(key in period for key in (
                'key', 'date_from', 'date_to', 'totals', 'channels', 'outflows')):
            return False
        if not all(isinstance(period[key], list) for key in ('totals', 'channels', 'outflows')):
            return False
        if not {'incoming_total', 'cash_total', 'difference'}.issubset(
                {row.get('key') for row in period['totals'] if isinstance(row, dict)}):
            return False
    return True
