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
