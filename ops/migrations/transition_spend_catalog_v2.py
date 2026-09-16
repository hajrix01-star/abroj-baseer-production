"""Controlled, replay-safe transition from the reviewed v1 spend catalog.

Run this file only through ``odoo shell -d <database>`` after making a
verified backup.  It deliberately uses the Odoo ORM: posted entries are never
updated, v1 rules remain as retired audit evidence, and accounts referenced by
preview evidence are archived rather than deleted.

The transition is intentionally specific to the reviewed Baseer catalog.  It
will stop on any unexpected shape instead of guessing a category.
"""

import json


LEGACY_VERSION = 'noorix-v1'
TARGET_VERSION = 'baseer-v2'
ACTIVE_VERSION_PARAMETER = 'baseer_native_spend.active_catalog_version'

# These IDs are the reviewed, immutable manifest for the production catalog.
# The script is intentionally refused on a database that does not have this
# exact mapping; it is not a generic name-based bulk renamer.
EXPECTED_ACCOUNT_PAIRS = {32: 35, 39: 38, 46: 50}

# Source tag -> canonical tag.  The target rule supplies the canonical leaf.
MERGED_TAGS = {
    'المنصات الحكومية': 'رسوم منصات حكومية',
    'اتصالات': 'مقدمو الاتصالات والإنترنت',
    'مقدمو الكهرباء': 'كهرباء',
}

CANONICAL_ACCOUNT_NAMES = {
    'رسوم منصات حكومية': {
        'ar_001': 'المنصات الحكومية',
        'en_US': 'Government Platforms',
    },
    'مقدمو الاتصالات والإنترنت': {
        'ar_001': 'مقدمو الاتصالات والإنترنت',
        'en_US': 'Telecommunications Providers',
    },
    'كهرباء': {
        'ar_001': 'مقدمو الكهرباء',
        'en_US': 'Electricity Providers',
    },
}


def _normalise(value):
    return ' '.join((value or '').strip().split())


def _tag_index():
    """Index every translated tag spelling, rejecting ambiguous catalog names."""
    index = {}
    for tag in env['res.partner.category'].sudo().search([]):
        for language in ('ar_001', 'en_US', False):
            name = _normalise(tag.with_context(lang=language).name)
            if not name:
                continue
            index.setdefault(name, env['res.partner.category'])
            index[name] |= tag
    return index


def _one_tag(index, name):
    tags = index.get(_normalise(name), env['res.partner.category'])
    if len(tags) != 1:
        raise RuntimeError('Expected one vendor tag for %r, found %s.' % (name, len(tags)))
    return tags


def _distribution_as_int_keys(model):
    distribution = {}
    for key, value in (model.analytic_distribution or {}).items():
        parts = [part.strip() for part in str(key).split(',') if part.strip()]
        # A native tag template must contain one and only one leaf.  Preserve
        # a compound/invalid key as nonmatching evidence instead of raising a
        # conversion error; the caller will stop before any write.
        if len(parts) != 1 or not parts[0].isdigit():
            return {'__non_single_leaf__:%s' % key: value}
        distribution[int(parts[0])] = value
    return distribution


def _financial_snapshot():
    """A compact receipt proving the migration did not touch accounting data."""
    env.cr.execute("""
        SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0),
               coalesce(sum(balance), 0), count(DISTINCT move_id)
          FROM account_move_line
    """)
    move_lines = tuple(str(value) for value in env.cr.fetchone())
    env.cr.execute("""
        SELECT count(*), coalesce(sum(amount_total), 0), coalesce(sum(amount_tax), 0),
               count(partner_id)
          FROM account_move
    """)
    moves = tuple(str(value) for value in env.cr.fetchone())
    return {'move_lines': move_lines, 'moves': moves}


def _assert_no_live_account_references(source_ids, expected_native_model_refs):
    """Reject archiving if a source dimension occurs outside retained evidence."""
    # Odoo batches ORM writes.  The transition repoints the three reviewed
    # distribution models immediately before this guard, while the guard uses
    # SQL for exhaustive schema discovery.  Flush first so SQL observes the
    # in-transaction values rather than the pre-transition JSON payloads.
    env['account.analytic.distribution.model'].sudo().flush_model([
        'analytic_distribution',
    ])
    # Direct FKs are discovered from PostgreSQL's own catalog so a future Odoo
    # module cannot silently add a reference we forgot to enumerate.
    env.cr.execute("""
        SELECT rel.relname, att.attname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_namespace ns ON ns.oid = rel.relnamespace
          JOIN unnest(con.conkey) AS keys(attnum) ON TRUE
          JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = keys.attnum
         WHERE con.contype = 'f'
           AND con.confrelid = 'account_analytic_account'::regclass
           AND ns.nspname = 'public'
         ORDER BY rel.relname, att.attname
    """)
    allowed_evidence = {'baseer_spend_map_rule', 'baseer_spend_map_preview_line'}
    for table_name, column_name in env.cr.fetchall():
        if table_name in allowed_evidence:
            continue
        env.cr.execute(
            'SELECT count(*) FROM "%s" WHERE "%s" = ANY(%%s)' % (table_name, column_name),
            [source_ids],
        )
        if env.cr.fetchone()[0]:
            raise RuntimeError('Live FK references block archival: %s.%s.' % (table_name, column_name))

    # Analytic distributions are JSON rather than foreign keys.  Check every
    # public JSON/JSONB column with this canonical name, not just invoices.
    env.cr.execute("""
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name = 'analytic_distribution'
           AND data_type IN ('json', 'jsonb')
         ORDER BY table_name
    """)
    source_keys = [str(source_id) for source_id in source_ids]
    for table_name, column_name in env.cr.fetchall():
        env.cr.execute(
            '''SELECT count(*)
                 FROM "%s"
                WHERE EXISTS (
                    SELECT 1
                      FROM jsonb_object_keys(coalesce("%s"::jsonb, '{}'::jsonb)) AS item(key)
                      CROSS JOIN LATERAL unnest(string_to_array(item.key, ',')) AS part(value)
                     WHERE btrim(part.value) = ANY(%%s)
                )''' % (table_name, column_name),
            [source_keys],
        )
        count = env.cr.fetchone()[0]
        # Exactly one tag-only model per source is the reviewed setup.  It is
        # inspected separately and is deliberately the only JSON reference
        # that will be rewritten in this transition.
        if table_name == 'account_analytic_distribution_model':
            if count != expected_native_model_refs:
                raise RuntimeError('Unexpected native distribution references to archived sources.')
        elif count:
            raise RuntimeError('Live analytic distribution blocks archival: %s.%s.' % (table_name, column_name))


def _tag_only_model(Model, tag, expected_analytic_account_id):
    """Return the only shared tag-only model and verify its full shape."""
    models = Model.search([
        ('company_id', '=', False),
        ('partner_category_id', '=', tag.id),
    ])
    if (len(models) != 1 or models.partner_id or models.product_id
            or models.product_categ_id or models.account_prefix
            or _distribution_as_int_keys(models) != {expected_analytic_account_id: 100.0}):
        raise RuntimeError('Expected one 100%% shared tag-only native model for %s.' % tag.display_name)
    return models


def _assert_steady_state(receipt_before=None):
    if env['ir.config_parameter'].sudo().get_param(ACTIVE_VERSION_PARAMETER) != TARGET_VERSION:
        raise RuntimeError('The active catalog parameter is not baseer-v2.')
    rules = env['baseer.spend.map.rule'].sudo().search([
        ('catalog_version', '=', TARGET_VERSION),
        ('state', '=', 'approved'),
        ('company_id', '=', False),
        ('selector_kind', '=', 'partner_tag'),
    ])
    if len(rules) != 52:
        raise RuntimeError('v2 steady state expects 52 approved shared tag rules, found %s.' % len(rules))
    if env['baseer.spend.map.rule'].sudo().search_count([
        ('catalog_version', '=', LEGACY_VERSION), ('state', '=', 'approved'),
    ]):
        raise RuntimeError('v1 still contains approved rules.')
    retired = env['baseer.spend.map.rule'].sudo().search([
        ('catalog_version', '=', LEGACY_VERSION), ('state', '=', 'retired'),
        ('company_id', '=', False), ('selector_kind', '=', 'partner_tag'),
    ])
    if len(retired) != 52:
        raise RuntimeError('v2 steady state expects 52 retired v1 rules, found %s.' % len(retired))
    expected_successors = {
        rule.natural_key.replace(LEGACY_VERSION + ':', TARGET_VERSION + ':', 1):
        EXPECTED_ACCOUNT_PAIRS.get(rule.analytic_account_id.id, rule.analytic_account_id.id)
        for rule in retired
    }
    actual_successors = {rule.natural_key: rule.analytic_account_id.id for rule in rules}
    if actual_successors != expected_successors:
        raise RuntimeError('The v2 successors do not exactly match retired v1 rules.')
    Account = env['account.analytic.account'].sudo()
    Model = env['account.analytic.distribution.model'].sudo()
    sources = Account.browse(list(EXPECTED_ACCOUNT_PAIRS))
    if len(sources) != 3 or any(source.active for source in sources):
        raise RuntimeError('The three superseded accounts are not archived.')
    if receipt_before and _financial_snapshot() != receipt_before:
        raise RuntimeError('Accounting snapshot changed during an analytic-only transition.')
    tag_index = _tag_index()
    for source_name, target_name in MERGED_TAGS.items():
        source_tag = _one_tag(tag_index, source_name)
        source_rule = retired.filtered(lambda rule: rule.partner_tag_id == source_tag)
        if len(source_rule) != 1:
            raise RuntimeError('A retired v1 source rule is missing for %s.' % source_name)
        target_id = EXPECTED_ACCOUNT_PAIRS.get(source_rule.analytic_account_id.id)
        if not target_id:
            raise RuntimeError('A reviewed source rule does not match the merge manifest.')
        _tag_only_model(Model, source_tag, target_id)
    _assert_no_live_account_references(list(EXPECTED_ACCOUNT_PAIRS), expected_native_model_refs=0)
    return {
        'status': 'already_applied',
        'v2_rules': len(rules),
        'retired_v1_rules': len(retired),
        'archived_source_accounts': sorted(sources.ids),
        'account_pairs': EXPECTED_ACCOUNT_PAIRS,
        'financial_snapshot': _financial_snapshot(),
    }


def transition():
    parameter = env['ir.config_parameter'].sudo()
    env.cr.execute('SELECT pg_advisory_xact_lock(294811606)')
    if parameter.get_param(ACTIVE_VERSION_PARAMETER) == TARGET_VERSION:
        return _assert_steady_state()

    Rule = env['baseer.spend.map.rule'].sudo()
    Model = env['account.analytic.distribution.model'].sudo()
    Account = env['account.analytic.account'].sudo()
    legacy_rules = Rule.search([
        ('catalog_version', '=', LEGACY_VERSION),
        ('state', '=', 'approved'),
        ('company_id', '=', False),
    ])
    if len(legacy_rules) != 52 or any(rule.selector_kind != 'partner_tag' for rule in legacy_rules):
        raise RuntimeError('Expected exactly 52 approved shared v1 vendor-tag rules.')
    if Rule.search_count([('catalog_version', '=', TARGET_VERSION)]):
        raise RuntimeError('A partial v2 catalog exists; resolve it manually before retrying.')

    receipt_before = _financial_snapshot()

    tag_index = _tag_index()
    source_to_target = {}
    source_tags = {}
    target_rules = {}
    for source_name, target_name in MERGED_TAGS.items():
        source_tag = _one_tag(tag_index, source_name)
        target_tag = _one_tag(tag_index, target_name)
        source_rule = legacy_rules.filtered(lambda rule: rule.partner_tag_id == source_tag)
        target_rule = legacy_rules.filtered(lambda rule: rule.partner_tag_id == target_tag)
        if len(source_rule) != 1 or len(target_rule) != 1:
            raise RuntimeError('Each reviewed source and target tag must have one v1 rule.')
        source_to_target[source_rule.analytic_account_id.id] = target_rule.analytic_account_id.id
        source_tags[source_rule.analytic_account_id.id] = source_tag
        target_rules[target_name] = target_rule

    if source_to_target != EXPECTED_ACCOUNT_PAIRS or len(source_to_target) != 3:
        raise RuntimeError('The reviewed production account pairs do not match the transition manifest.')
    root = env.ref('baseer_native_spend.spend_plan')
    accounts = Account.browse(list(EXPECTED_ACCOUNT_PAIRS) + list(EXPECTED_ACCOUNT_PAIRS.values()))
    if len(accounts) != 6 or any(
        account.company_id or not account.active or account.root_plan_id != root or account.plan_id == root
        for account in accounts
    ):
        raise RuntimeError('Every merged account must be an active shared spend leaf.')
    _assert_no_live_account_references(list(EXPECTED_ACCOUNT_PAIRS), expected_native_model_refs=3)

    # Repoint only the three reviewed tag-only native models before retiring
    # v1; they govern future vendor bills, not posted accounting lines.
    for source_id, target_id in source_to_target.items():
        source_tag = source_tags[source_id]
        models = _tag_only_model(Model, source_tag, source_id)
        models.write({'analytic_distribution': {str(target_id): 100.0}})

    # Clone every reviewed selector.  The three semantic duplicates receive
    # the canonical destination; the other 49 preserve their destination.
    successors = Rule
    for legacy in legacy_rules:
        values = legacy._baseer_rule_values()
        values['catalog_version'] = TARGET_VERSION
        values['analytic_account_id'] = source_to_target.get(
            legacy.analytic_account_id.id,
            legacy.analytic_account_id.id,
        )
        successors |= Rule.create(values)
    if len(successors) != len(legacy_rules):
        raise RuntimeError('The v2 rule clone is incomplete.')
    successors.action_approve()
    legacy_rules.action_retire()

    # Keep preview/audit evidence resolvable, but hide the superseded accounts
    # from ordinary selection.  There are no posted move-line references.
    source_accounts = Account.browse(list(source_to_target))
    source_accounts.write({'active': False})

    # Present the surviving catalog consistently in Arabic and English.
    for tag_name, translations in CANONICAL_ACCOUNT_NAMES.items():
        rule = target_rules[tag_name]
        if len(rule) != 1:
            raise RuntimeError('Cannot find the canonical rule for %s.' % tag_name)
        account = rule.analytic_account_id
        for language, value in translations.items():
            account.with_context(lang=language).write({'name': value})

    # This is deliberately last: a new preview cannot select v2 until its
    # full rule catalog, models and archived predecessors are committed.
    parameter.set_param(ACTIVE_VERSION_PARAMETER, TARGET_VERSION)

    result = _assert_steady_state(receipt_before)
    result.update({
        'retired_v1_rules': len(legacy_rules),
        'archived_source_accounts': source_accounts.ids,
        'repointed_native_models': len(source_to_target),
    })
    return result


try:
    report = transition()
    env.cr.commit()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
except Exception:
    env.cr.rollback()
    raise
