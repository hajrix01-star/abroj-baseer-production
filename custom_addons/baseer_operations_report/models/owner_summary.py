"""Private arithmetic for the owner summary, not yet connected to the report.

Only a server-side adapter may supply these facts, after source completeness,
company, access and cash-allocation checks. This reducer cannot prove those
facts or grant access. It has no ORM, RPC, cache, persistence or side effects.
Amounts are already VAT-inclusive and allocated by the source adapter; no
invoice allocation or accounting policy is introduced here.
"""

from decimal import Decimal, ROUND_HALF_UP, localcontext


_ZERO = Decimal('0.00')
_CENT = Decimal('0.01')
_UNCLASSIFIED = frozenset(('unclassified', 'unconfirmed_bill_classification'))


def _outflow_bucket(event):
    """A label from the source adapter, never inferred from a display name."""
    kind = event.get('classification')
    if kind in _UNCLASSIFIED:
        return kind, {}
    if kind == 'purchase':
        path = event.get('category_path')
        if not isinstance(path, (list, tuple)) or not 2 <= len(path) <= 64:
            raise ValueError('A classified purchase needs a non-root category path.')
        normalized, seen = [], set()
        for part in path:
            if not isinstance(part, (list, tuple)) or len(part) != 2:
                raise ValueError('Invalid category path.')
            identity, name = _identity(part[0]), _text(part[1])
            if identity in seen:
                raise ValueError('A category path cannot contain a cycle.')
            seen.add(identity)
            normalized.append((identity, name))
        return 'purchase:' + '/'.join(str(item[0]) for item in normalized), {
            'classification': kind, 'name': normalized[-1][1],
            'category_path': normalized,
        }
    if kind == 'operating_account':
        identity = _identity(event.get('account_id'))
        return 'operating_account:%s' % identity, {
            'classification': kind, 'name': _text(event.get('account_name')),
            'account_id': identity,
        }
    if kind in ('payroll', 'employee_advance'):
        return kind, {'classification': kind}
    if kind in ('employee_services', 'operating_services'):
        key = _text(event.get('service_key'))
        return kind + ':' + key, {
            'classification': kind, 'name': _text(event.get('service_name')),
            'service_key': key,
        }
    raise ValueError('Unknown outflow classification.')


def _money(value):
    # Reject floats, including finite floats: converting them here would hide
    # an upstream contract violation. Never round a source amount to accept it.
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError('A finite Decimal amount is required.')
    if value.as_tuple().exponent < -2:
        raise ValueError('Source amounts must have at most two decimal places.')
    # Bound arithmetic explicitly, rather than silently losing low-order cents
    # if an invalid upstream value exceeds Decimal's ambient precision.
    if value.copy_abs() >= Decimal('1e18'):
        raise ValueError('Source amount exceeds the summary precision contract.')
    return value


def _identity(value):
    if type(value) is not int or value <= 0:
        raise ValueError('A positive source identity is required.')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonempty source key is required.')
    return value


def build_owner_summary(events, liquidity_totals, *, company_id):
    """Aggregate one already-proven company/period without changing its facts.

    Each incoming event supplies exact, signed channel allocations. Each cash
    event supplies one existing allocation to a source line. Multiple distinct
    lines may share a liquidity witness; together they must equal that witness
    exactly. Repeated lines are errors, not silently dropped duplicate amounts.

    Unconfirmed bill attribution is NOT unconfirmed cash: the proven cash stays
    in the total/difference, but never becomes a purchase category. The current
    reducer does not claim report/source completeness. Classified buckets are
    supplied by the adapter, never guessed here. Bucket counts are distinct
    liquidity witnesses per bucket and cannot be added across categories.
    Percentages are independently rounded presentation values;
    they may sum to 99.99 or 100.01, without changing any monetary amount.
    """
    _identity(company_id)
    if not isinstance(liquidity_totals, dict):
        raise ValueError('Liquidity witnesses must be an explicit mapping.')
    expected = {}
    for key, value in liquidity_totals.items():
        key, value = _identity(key), _money(value)
        if value <= 0:
            raise ValueError('An outflow witness must be positive.')
        expected[key] = value

    # Pure arithmetic must not inherit a caller's reduced Decimal precision.
    with localcontext() as context:
        context.prec = 60
        incoming = _ZERO
        cash = _ZERO
        incoming_count = 0
        seen = set()
        channel_totals = {}
        paid = {}
        payment_classes = {}
        buckets = {}
        for event in events:
            if not isinstance(event, dict):
                raise ValueError('An explicit source fact is required.')
            if _identity(event.get('company_id')) != company_id:
                raise ValueError('Mixed-company facts are not permitted.')
            _text(event.get('source_model'))
            _identity(event.get('source_id'))
            line_model = _text(event.get('line_model'))
            line_id = _identity(event.get('line_id'))
            amount = _money(event.get('amount'))
            direction = event.get('direction')
            if direction not in ('incoming', 'outgoing'):
                raise ValueError('Unknown event direction.')
            payment_id = event.get('payment_line_id')
            if direction == 'outgoing':
                payment_id = _identity(payment_id)
                if amount <= 0 or payment_id not in expected:
                    raise ValueError('An outflow needs a positive witnessed allocation.')
            elif payment_id is not None:
                raise ValueError('An incoming sale must not carry an outflow witness.')
            identity = (line_model, line_id, payment_id or 0)
            if identity in seen:
                raise ValueError('A source allocation was supplied more than once.')
            seen.add(identity)

            if direction == 'incoming':
                channels = event.get('channels')
                if not isinstance(channels, (list, tuple)) or not channels:
                    raise ValueError('Explicit channel or unallocated evidence is required.')
                allocated = _ZERO
                channel_keys = set()
                for item in channels:
                    if not isinstance(item, (list, tuple)) or len(item) != 3:
                        raise ValueError('Invalid channel allocation.')
                    key, name, value = item
                    _text(key)
                    if not isinstance(name, str) or key in channel_keys:
                        raise ValueError('Invalid or repeated channel identity.')
                    channel_keys.add(key)
                    value = _money(value)
                    if amount * value < 0 or (not amount and value):
                        raise ValueError('Channel allocations must retain the sale sign.')
                    if key in channel_totals and channel_totals[key]['name'] != name:
                        raise ValueError('Conflicting names for one channel identity.')
                    row = channel_totals.setdefault(key, {'name': name, 'amount': _ZERO})
                    row['amount'] += value
                    allocated += value
                if allocated != amount:
                    raise ValueError('Channel allocations do not equal the source amount.')
                incoming += amount
                incoming_count += 1
            else:
                classification = event.get('classification')
                bucket_key, metadata = _outflow_bucket(event)
                if event.get('channels'):
                    raise ValueError('Cash outflows cannot be attributed to sales channels.')
                unconfirmed = classification == 'unconfirmed_bill_classification'
                if (payment_id in payment_classes
                        and payment_classes[payment_id] != unconfirmed):
                    raise ValueError('Unconfirmed and confirmed allocation cannot share a cash event.')
                payment_classes[payment_id] = unconfirmed
                paid[payment_id] = paid.get(payment_id, _ZERO) + amount
                bucket = buckets.setdefault(bucket_key, {
                    'amount': _ZERO, 'ids': set(), 'metadata': metadata,
                })
                if bucket['metadata'] != metadata:
                    raise ValueError('Conflicting labels for one classified bucket.')
                bucket['amount'] += amount
                bucket['ids'].add(payment_id)
                cash += amount

        if paid != expected:
            raise ValueError('Cash allocations do not exactly cover the liquidity witnesses.')
        channels = [
            {'key': key, **row, 'percentage': (
                (row['amount'] * 100 / incoming).quantize(_CENT, rounding=ROUND_HALF_UP)
                if incoming else None
            )}
            for key, row in sorted(channel_totals.items())
        ]
        return {
            'incoming_total': incoming,
            'cash_total': cash,
            'difference': incoming - cash,
            'channels': channels,
            'outflow_buckets': [
                {'key': key, 'amount': bucket['amount'], 'count': len(bucket['ids']),
                 **bucket['metadata']}
                for key, bucket in sorted(buckets.items())
            ],
            'has_unclassified_outflows': bool(_UNCLASSIFIED.intersection(buckets)),
            'incoming_event_count': incoming_count,
            'cash_event_count': len(paid),
        }
