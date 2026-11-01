import base64
import binascii
import hmac
import json
import logging
import time
from uuid import uuid4
from urllib.parse import urlencode

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import hmac as odoo_hmac


_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    baseer_print_session_close_report = fields.Boolean(
        related='config_id.baseer_print_session_close_report', readonly=True,
    )

    def _baseer_current_report_printer(self):
        """Authorize before reading aggregate or privileged hardware data."""
        self.ensure_one()
        self.check_access('read')
        self.config_id.check_access('read')
        user = self.env.user
        if not user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('A Point of Sale user is required to print a session report.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('You do not have access to this session company.'))
        if (self.user_id != user and not user.has_group('point_of_sale.group_pos_manager')):
            raise AccessError(_('You can only print your own current session report.'))
        if self.state != 'opened' or self.config_id.current_session_id != self:
            raise ValidationError(_('The current session report requires the open Point of Sale session.'))
        config = self.config_id
        printer = config.sudo().baseer_receipt_printer_id
        if (not config.baseer_direct_print_enabled or not printer or not printer.active
                or printer.paper_width != '80' or not printer._allows_company(self.company_id)):
            raise ValidationError(_('The 80 mm receipt printer is not available for this company.'))
        if not self.env['baseer.print.job']._agent_supports_native_receipts(printer.agent_id):
            raise ValidationError(_('Update the print agent before printing the current session report.'))
        return printer

    def baseer_prepare_current_report(self):
        """Return server values plus a short-lived, user/session-bound snapshot."""
        self._baseer_current_report_printer()
        as_of = fields.Datetime.now()
        report = self.env['baseer.print.job']._session_close_payload(self, as_of=as_of)
        report['ticket_type'] = 'session_report'
        report['session']['closed_at'] = False
        report['session']['as_of'] = fields.Datetime.to_string(as_of)
        # Format timestamps on the server. The browser never computes money or duration.
        for source, target in [('opened_at', 'opened_label'), ('as_of', 'as_of_label')]:
            value = fields.Datetime.to_datetime(report['session'][source])
            report['session'][target] = fields.Datetime.context_timestamp(self, value).strftime('%Y-%m-%d %H:%M:%S %Z')
        snapshot = {
            'uid': self.env.uid, 'session_id': self.id, 'company_id': self.company_id.id,
            'request_id': str(uuid4()), 'expires_at': int(time.time()) + 300,
            'report': report,
        }
        encoded = base64.urlsafe_b64encode(json.dumps(snapshot, separators=(',', ':'), ensure_ascii=False).encode()).decode()
        signature = odoo_hmac(self.env(su=True), 'baseer.current-session-report.v1', encoded)
        return {'report': report, 'token': encoded + '.' + signature, 'expires_at': snapshot['expires_at']}

    def baseer_enqueue_current_report(self, token, jpeg_base64):
        printer = self._baseer_current_report_printer()
        if not isinstance(token, str) or len(token) > 131072:
            raise AccessError(_('The session report authorization is invalid.'))
        try:
            encoded, signature = token.rsplit('.', 1)
            expected = odoo_hmac(self.env(su=True), 'baseer.current-session-report.v1', encoded)
            if not hmac.compare_digest(signature, expected):
                raise ValueError('signature')
            snapshot = json.loads(base64.b64decode(encoded, altchars=b'-_', validate=True))
            if (snapshot['uid'] != self.env.uid or snapshot['session_id'] != self.id
                    or snapshot['company_id'] != self.company_id.id
                    or snapshot['expires_at'] < time.time()):
                raise ValueError('scope or expiry')
        except (ValueError, TypeError, KeyError, binascii.Error):
            raise AccessError(_('The session report authorization is invalid or expired.')) from None
        job = self.env['baseer.print.job']._enqueue_current_session_report(self, printer, snapshot, jpeg_base64)
        return {'job_id': job.id, 'state': job.state}

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        result = super()._validate_session(
            balancing_account, amount_to_balance, bank_payment_method_diffs,
        )
        for session in self.filtered(
            lambda item: item.state == 'closed' and item.baseer_print_session_close_report
        ):
            try:
                with self.env.cr.savepoint():
                    self.env['baseer.print.job']._enqueue_session_close(session)
            except Exception:
                # Printing is downstream of the native accounting close. Never
                # roll back a valid session close because a printer is offline
                # or misconfigured; managers can recover from the session form.
                _logger.exception('Could not enqueue Baseer closing report for POS session %s', session.id)
        return result

    def action_baseer_print_closing_report(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('Only a Point of Sale manager can print a session closing report.'))
        if self.state != 'closed':
            raise ValidationError(_('The session closing report is available only after the session is closed.'))
        if not self.baseer_print_session_close_report:
            raise ValidationError(_('Enable the session closing report on this point of sale first.'))

        Job = self.env['baseer.print.job']
        job = Job._enqueue_session_close(self)
        if job.state in ('done', 'failed', 'cancelled'):
            job.action_reprint()
            job = Job.search([('reprint_of_id', '=', job.id)], order='reprint_sequence desc', limit=1)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'baseer.print.job',
            'res_id': job.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_baseer_open_whatsapp_closing_report(self):
        """Open the closed-session summary in WhatsApp without sending it."""
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('Only a Point of Sale manager can send a session report by WhatsApp.'))
        self.check_access_rights('read')
        self.check_access_rule('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('You do not have access to this session company.'))
        if self.state != 'closed':
            raise ValidationError(_('The WhatsApp session report is available only after the session is closed.'))
        if not self.baseer_print_session_close_report:
            raise ValidationError(_('Enable the session closing report on this point of sale first.'))

        payload = self.env['baseer.print.job']._session_close_payload(self)
        session = payload['session']
        summary = payload['summary']
        # WhatsApp receives the text in a separate client.  Keep its Arabic
        # labels explicit rather than depending on the current Odoo UI locale.
        payment_lines = [
            f"{payment['method']}: {payment['amount']} {session['currency_code']}"
            for payment in payload['payments']
        ] or ['لا توجد مدفوعات']
        report_text = '\n'.join([
            'تقرير إغلاق الجلسة',
            f"الجلسة: {session['reference']}",
            f"نقطة البيع: {session['point_of_sale']}",
            f"الكاشير: {session['cashier']}",
            f"تاريخ الفتح: {session['opened_at']}",
            f"تاريخ الإغلاق: {session['closed_at']}",
            f"المدة: {session['duration_label']}",
            '',
            f"عدد الفواتير: {summary['invoice_count']}",
            f"المرتجعات: {summary['refund_count']}",
            f"إجمالي المبيعات: {summary['total_amount']} {session['currency_code']}",
            f"إجمالي المدفوعات: {summary['payment_total']} {session['currency_code']}",
            f"معدل الفاتورة: {summary['average_invoice']} {session['currency_code']}",
            f"إجمالي الضيوف: {summary['guest_count']}",
            f"متوسط إنفاق الضيف: {summary['average_per_guest']} {session['currency_code']}",
            f"الوحدات المباعة: {summary['units_sold']}",
            f"الأصناف المباعة: {summary['products_sold']}",
            f"الإلغاءات: {summary['cancellation_count']}",
            '',
            'طرق الدفع',
            *payment_lines,
        ])
        url = 'https://wa.me/?%s' % urlencode({'text': report_text})
        if len(url) > 2000:
            raise ValidationError(_('This session report is too long to open safely in WhatsApp.'))
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}
