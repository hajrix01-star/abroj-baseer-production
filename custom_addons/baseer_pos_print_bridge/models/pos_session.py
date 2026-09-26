import logging
from urllib.parse import urlencode

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    baseer_print_session_close_report = fields.Boolean(
        related='config_id.baseer_print_session_close_report', readonly=True,
    )

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
