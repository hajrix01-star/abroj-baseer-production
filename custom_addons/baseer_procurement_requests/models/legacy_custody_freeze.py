"""Read-only freeze of the legacy PCUST Petty Cash path.

The live representative custody path is ``baseer.procurement.representative.advance``
(funding/return/reversal) plus native supplier payments from the representative's
custody journal.  The legacy ``baseer.procurement.custody`` records and their
events stay readable and keep counting in the representative balance, but no
new PCUST record, movement, close, or purchase-batch link may be created or
changed, whether from the UI, RPC, or an external API client.

Test fixtures and data migrations can still build historical records with the
in-process proof below.  It is an object identity that cannot be serialized
into an RPC context, and it also requires a superuser environment.
"""

from odoo import api, models
from odoo.exceptions import UserError

LEGACY_FIXTURE_CONTEXT = '_baseer_legacy_custody_fixture'
LEGACY_FIXTURE_PROOF = object()


def legacy_fixture_context(env):
    """Return an environment allowed to build historical PCUST records (tests/migrations only)."""
    return env(su=True, context=dict(env.context, **{LEGACY_FIXTURE_CONTEXT: LEGACY_FIXTURE_PROOF}))


def _legacy_allowed(env):
    return env.su and env.context.get(LEGACY_FIXTURE_CONTEXT) is LEGACY_FIXTURE_PROOF


def _raise_frozen(env):
    raise UserError(env._(
        'Legacy Petty Cash (PCUST) is read-only. Record transfers and returns in '
        'Representative Petty Cash instead.'
    ))


def _mail_only(model, vals):
    """Chatter/activity bookkeeping does not change the custody record."""
    mail_fields = set(model.env['mail.thread']._fields) | set(model.env['mail.activity.mixin']._fields)
    return set(vals) <= mail_fields


class LegacyProcurementCustodyFreeze(models.Model):
    _inherit = 'baseer.procurement.custody'

    @api.model_create_multi
    def create(self, vals_list):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().create(vals_list)

    def write(self, vals):
        if self and not _legacy_allowed(self.env) and not _mail_only(self, vals):
            _raise_frozen(self.env)
        return super().write(vals)

    def unlink(self):
        if self and not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().unlink()

    def action_close(self):
        # The original close writes through ``super(ProcurementCustody, ...)``,
        # skipping ``write``; block the action itself.
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().action_close()


class LegacyProcurementCustodyEventFreeze(models.Model):
    _inherit = 'baseer.procurement.custody.event'

    @api.model_create_multi
    def create(self, vals_list):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().create(vals_list)

    def write(self, vals):
        if self and not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().write(vals)

    def unlink(self):
        if self and not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().unlink()

    def action_post(self):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().action_post()


class LegacyProcurementCustodyPeriodCloseFreeze(models.Model):
    _inherit = 'baseer.procurement.custody.period.close'

    @api.model_create_multi
    def create(self, vals_list):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().create(vals_list)

    def action_close(self):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().action_close()


class LegacyPurchaseBatchLineCustodyFreeze(models.Model):
    _inherit = 'baseer.purchase.batch.line'

    @api.model_create_multi
    def create(self, vals_list):
        if not _legacy_allowed(self.env) and any(vals.get('procurement_custody_id') for vals in vals_list):
            _raise_frozen(self.env)
        return super().create(vals_list)

    def write(self, values):
        if values.get('procurement_custody_id') and not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().write(values)


class LegacyPurchaseBatchCustodyFreeze(models.Model):
    _inherit = 'baseer.purchase.batch'

    @api.model_create_multi
    def create(self, vals_list):
        if not _legacy_allowed(self.env) and any(vals.get('procurement_custody_id') for vals in vals_list):
            _raise_frozen(self.env)
        return super().create(vals_list)

    def write(self, values):
        if values.get('procurement_custody_id') and not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().write(values)

    def action_resettle_custody(self):
        if not _legacy_allowed(self.env):
            _raise_frozen(self.env)
        return super().action_resettle_custody()
