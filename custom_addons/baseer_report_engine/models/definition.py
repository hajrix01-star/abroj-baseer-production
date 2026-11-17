"""Declarative report, line and expression records. Computation lives on the engine."""

import ast

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BaseerReportDefinition(models.Model):
    _name = 'baseer.report.definition'
    _description = 'Baseer Report Definition'
    _order = 'name, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    date_mode = fields.Selection(
        [('as_of', 'As of date'), ('range', 'Date range')],
        required=True,
        default='range',
    )
    line_ids = fields.One2many('baseer.report.line', 'report_id')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', 'The report code must be unique.')
    _code_format = models.Constraint(
        r"CHECK(code ~ '^[a-z][a-z0-9_]{0,40}$')",
        'Report codes use a lowercase identifier.',
    )


class BaseerReportLine(models.Model):
    _name = 'baseer.report.line'
    _description = 'Baseer Report Line'
    _order = 'sequence, id'
    _parent_name = 'parent_id'

    report_id = fields.Many2one(
        'baseer.report.definition', required=True, ondelete='cascade', index=True,
    )
    parent_id = fields.Many2one('baseer.report.line', ondelete='cascade', index=True)
    child_ids = fields.One2many('baseer.report.line', 'parent_id')
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True)
    name = fields.Char(required=True, translate=True)
    foldable = fields.Boolean(default=False)
    hideable = fields.Boolean(
        default=True,
        help='When hide-zero is on, a hideable line disappears if every period amount is zero.',
    )
    display = fields.Selection(
        [('section', 'Section'), ('line', 'Line'), ('total', 'Total')],
        default='line',
        required=True,
    )
    show_total = fields.Boolean(default=True)
    expression_ids = fields.One2many('baseer.report.expression', 'line_id')

    _report_code_unique = models.Constraint(
        'UNIQUE(report_id, code)',
        'Each line code is unique inside its report.',
    )
    _code_format = models.Constraint(
        r"CHECK(code ~ '^[A-Z][A-Z0-9_]{0,30}$')",
        'Line codes use uppercase letters, digits and underscores.',
    )

    @api.constrains('parent_id', 'report_id')
    def _check_parent(self):
        for line in self:
            if line.parent_id and line.parent_id.report_id != line.report_id:
                raise ValidationError(_('A line and its parent must belong to the same report.'))
            seen = set()
            parent = line.parent_id
            while parent:
                if parent.id == line.id or parent.id in seen:
                    raise ValidationError(_('Report lines cannot contain a cycle.'))
                seen.add(parent.id)
                parent = parent.parent_id


class BaseerReportExpression(models.Model):
    _name = 'baseer.report.expression'
    _description = 'Baseer Report Expression'
    _order = 'sequence, id'

    line_id = fields.Many2one(
        'baseer.report.line', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    label = fields.Char(translate=True)
    engine = fields.Selection(
        [
            ('account_type', 'Account Type'),
            ('code_prefix', 'Account Code Prefix'),
            ('domain', 'Move Line Domain'),
            ('formula', 'Formula'),
        ],
        required=True,
    )
    account_types = fields.Char(help='Comma-separated account.account types.')
    code_prefixes = fields.Char(help='Comma-separated account code prefixes.')
    domain = fields.Char(help='Literal domain on account.move.line.')
    formula = fields.Char(help='Arithmetic formula using other line codes.')
    figure = fields.Selection(
        [('balance', 'Balance'), ('debit', 'Debit'), ('credit', 'Credit')],
        default='balance',
        required=True,
    )
    sign = fields.Selection(
        [('1', 'Keep sign'), ('-1', 'Reverse sign')],
        default='1',
        required=True,
    )
    date_scope = fields.Selection(
        [
            ('report', 'Report period'),
            ('to_date', 'Cumulative to period end'),
            ('from_fiscalyear', 'Current fiscal year to period end'),
            ('before_fiscalyear', 'Before current fiscal year'),
        ],
        default='report',
        required=True,
    )

    def _account_type_list(self):
        self.ensure_one()
        return [item.strip() for item in (self.account_types or '').split(',') if item.strip()]

    def _prefix_list(self):
        self.ensure_one()
        return [item.strip() for item in (self.code_prefixes or '').split(',') if item.strip()]

    def _domain_list(self):
        self.ensure_one()
        try:
            parsed = ast.literal_eval(self.domain or '')
        except (SyntaxError, ValueError) as error:
            raise ValidationError(_('The move line domain must be a literal list.')) from error
        if not isinstance(parsed, list):
            raise ValidationError(_('The move line domain must be a literal list.'))
        return parsed

    def _matches_account(self, account):
        self.ensure_one()
        if self.engine == 'account_type':
            return account.account_type in set(self._account_type_list())
        if self.engine == 'code_prefix':
            code = account.with_company(account.company_ids[:1] or self.env.company).code or ''
            return any(code.startswith(prefix) for prefix in self._prefix_list())
        return False

    def _account_domain(self):
        """Domain fragment that selects the move lines of this expression."""
        self.ensure_one()
        if self.engine == 'account_type':
            types = self._account_type_list()
            return [('account_id.account_type', 'in', types or ['__none__'])]
        if self.engine == 'code_prefix':
            prefixes = self._prefix_list()
            if not prefixes:
                return [('id', '=', 0)]
            return _or_domains([
                [('account_id.code', '=like', '%s%%' % prefix)] for prefix in prefixes
            ])
        if self.engine == 'domain':
            return self._domain_list()
        return [('id', '=', 0)]

    @api.constrains(
        'engine', 'line_id', 'formula', 'domain', 'account_types', 'code_prefixes',
    )
    def _check_expression(self):
        for expression in self:
            engines = set(expression.line_id.expression_ids.mapped('engine'))
            if 'formula' in engines and (engines != {'formula'} or len(expression.line_id.expression_ids) != 1):
                raise ValidationError(_('A formula line has one formula and no other expressions.'))
            if expression.engine == 'account_type' and not expression._account_type_list():
                raise ValidationError(_('An account-type expression needs at least one type.'))
            if expression.engine == 'code_prefix' and not expression._prefix_list():
                raise ValidationError(_('A code-prefix expression needs at least one prefix.'))
            if expression.engine == 'domain':
                expression._domain_list()
            if expression.engine == 'formula' and not (expression.formula or '').strip():
                raise ValidationError(_('A formula expression needs a formula.'))


def _or_domains(domains):
    domains = [list(domain) for domain in domains if domain]
    if not domains:
        return [('id', '=', 0)]
    return list(fields.Domain.OR(domains))
