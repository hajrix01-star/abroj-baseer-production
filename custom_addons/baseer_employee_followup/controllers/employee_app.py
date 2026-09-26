import base64
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

import pytz

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request


class EmployeeFollowupApp(http.Controller):
    _stage_order = {'opening': 1, 'midday': 2, 'closing': 4}
    _stage_details = {
        'opening': {'title_ar': 'بداية الدوام', 'title_en': 'Start of shift', 'lines': 'opening_line_ids', 'completion': 'opening_completion'},
        'midday': {'title_ar': 'وسط الدوام', 'title_en': 'Mid-shift', 'lines': 'midday_line_ids', 'completion': 'midday_completion'},
        'closing': {'title_ar': 'الإغلاق', 'title_en': 'Closing', 'lines': 'closing_line_ids', 'completion': 'closing_completion'},
    }

    def _has_manager_app_access(self):
        """PWA admission is owned by the current Odoo user, never by the browser."""
        user = request.env.user
        return user._is_admin() or user.baseer_manager_app_access

    def _require_manager_app_access(self):
        if not self._has_manager_app_access():
            raise AccessError('You are not allowed to access the manager app.')

    def _selected_backend_company(self):
        """Use Odoo's selected-company cookie, never a user's default company.

        Client actions call JSON routes directly, so their requests do not carry
        the normal model-RPC context.  Odoo itself stores the selected company
        list in ``cids``.  Accept only the first value that is still allowed to
        the authenticated user; an absent or invalid cookie keeps Odoo's safe
        default-company behavior.
        """
        raw_company_ids = request.httprequest.cookies.get('cids', '')
        selected_company_ids = []
        for value in raw_company_ids.split('-'):
            if value.isdigit():
                selected_company_ids.append(int(value))
        allowed_company_ids = set(request.env.user.company_ids.ids)
        company_id = next((company_id for company_id in selected_company_ids
                           if company_id in allowed_company_ids), request.env.company.id)
        return request.env['res.company'].browse(company_id)

    def _has_backend_dashboard_access(self):
        user = request.env.user
        return user.has_group('baseer_employee_followup.group_followup_manager') or user.has_group('base.group_system')

    def _employee_for_current_user(self):
        self._require_manager_app_access()
        employee_model = request.env['hr.employee'].sudo()
        # Prefer the active company, but do not deny a permitted manager just
        # because their current Odoo session is on another allowed company.
        # The shift itself always continues under the selected employee's
        # company.  This reads existing assignments only; it never creates or
        # changes a user-to-employee link.
        employee = employee_model.search([
            ('user_id', '=', request.env.user.id),
            ('company_id', '=', request.env.company.id),
            ('active', '=', True),
        ], limit=1)
        if employee:
            return employee
        return employee_model.search([
            ('user_id', '=', request.env.user.id),
            ('company_id', 'in', request.env.user.company_ids.ids),
            ('active', '=', True),
        ], order='company_id, id', limit=1)

    def _current_shift(self, employee):
        return request.env['baseer.followup.shift'].sudo().with_company(employee.company_id).search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if employee else request.env['baseer.followup.shift']

    def _is_arabic(self):
        """Keep the PWA language independent from an Odoo account's locale."""
        language = request.httprequest.cookies.get('baseer_shift_lang')
        if language in ('ar', 'en'):
            return language == 'ar'
        if request.session.uid:
            language = request.env.user.lang or ''
        else:
            language = request.httprequest.headers.get('Accept-Language', '')
        return not language or language.lower().startswith('ar')

    def _ui(self, is_arabic):
        return {
            'app_name': 'بصير شِفت' if is_arabic else 'Baseer Shift',
            'today_nav': 'لوحة اليوم' if is_arabic else 'Today',
            'today_title': 'مهام اليوم' if is_arabic else 'Today’s tasks',
            'today_copy': 'تابع ما يحتاج إنجازًا اليوم.' if is_arabic else 'Track what needs to be completed today.',
            'today_complete': 'تم' if is_arabic else 'Complete',
            'today_incomplete': 'غير مكتمل' if is_arabic else 'Incomplete',
            'today_open_task': 'فتح المهمة' if is_arabic else 'Open task',
            'dashboard_title': 'ملخص الشهر' if is_arabic else 'Monthly overview',
            'dashboard_nav': 'لوحة التحكم' if is_arabic else 'Dashboard',
            'shift_nav': 'المتابعة' if is_arabic else 'Shift follow-up',
            'tasks_nav': 'المهام' if is_arabic else 'Tasks',
            'menu_label': 'فتح القائمة' if is_arabic else 'Open menu',
            'close_menu': 'إغلاق القائمة' if is_arabic else 'Close menu',
            'navigation_label': 'تنقل بصير شِفت' if is_arabic else 'Baseer Shift navigation',
            'account_label': 'الحساب' if is_arabic else 'Account',
            'language_label': 'اللغة' if is_arabic else 'Language',
            'shift_overview_title': 'متابعة الوردية' if is_arabic else 'Shift follow-up',
            'shift_overview_copy': 'أكمل مراحل ورديتك بالترتيب.' if is_arabic else 'Complete your shift stages in order.',
            'backend_dashboard_title': 'لوحة متابعة الموظفين' if is_arabic else 'Employee follow-up dashboard',
            'employee_performance': 'أداء الموظفين' if is_arabic else 'Employee performance',
            'employee': 'الموظف' if is_arabic else 'Employee',
            'employee_score': 'التقييم' if is_arabic else 'Score',
            'evaluation_notes': 'ملاحظات التقييم' if is_arabic else 'Evaluation notes',
            'top_noted_employees': 'الأكثر ملاحظات' if is_arabic else 'Most noted employees',
            'latest_followups': 'أحدث المتابعات' if is_arabic else 'Latest follow-ups',
            'no_employee_data': 'لا توجد تقييمات للموظفين حتى الآن.' if is_arabic else 'No employee evaluations yet.',
            'no_open_followups': 'لا توجد متابعات مفتوحة.' if is_arabic else 'No open follow-ups.',
            'month_period': 'الفترة' if is_arabic else 'Period',
            'shift_completion': 'التزام المدير' if is_arabic else 'Manager adherence',
            'team_quality': 'جودة أداء الفريق' if is_arabic else 'Team performance quality',
            'revenue_growth': 'نمو الإيراد' if is_arabic else 'Revenue growth',
            'revenue_comparison': 'مقارنة بنفس الفترة من الشهر السابق' if is_arabic else 'Compared with the same period last month',
            'no_revenue_comparison': 'لا توجد مقارنة سابقة' if is_arabic else 'No prior comparison',
            'revenue_unavailable': 'غير متاح لهذا الحساب' if is_arabic else 'Not available for this account',
            'open_followups': 'متابعات مفتوحة' if is_arabic else 'Open follow-ups',
            'followups_tab': 'المتابعات' if is_arabic else 'Follow-ups',
            'history_tab': 'السجل' if is_arabic else 'History',
            'pending_followups': 'متابعات معلّقة' if is_arabic else 'Pending follow-ups',
            'completed_followups': 'تم الإنجاز' if is_arabic else 'Completed',
            'no_completed_followups': 'لا توجد متابعات منجزة حتى الآن.' if is_arabic else 'No completed follow-ups yet.',
            'attention_alerts': 'تنبيهات تحتاج متابعة' if is_arabic else 'Needs attention',
            'view_notes': 'عرض الملاحظات' if is_arabic else 'View notes',
            'no_followups': 'لا توجد متابعات لهذا الشهر.' if is_arabic else 'No follow-ups for this month.',
            'note_open': 'مفتوحة' if is_arabic else 'Open',
            'note_resolved': 'تمت المعالجة' if is_arabic else 'Resolved',
            'day_count': 'يوم' if is_arabic else 'days',
            'followup_count': 'متابعات' if is_arabic else 'follow-ups',
            'team_indicators': 'مؤشرات أداء الفريق' if is_arabic else 'Team performance indicators',
            'monthly': 'هذا الشهر' if is_arabic else 'This month',
            'followup_sections': 'أقسام المتابعة' if is_arabic else 'Follow-up sections',
            'opening': 'بداية الدوام' if is_arabic else 'Start of shift',
            'midday': 'وسط الدوام' if is_arabic else 'Mid-shift',
            'closing': 'الإغلاق' if is_arabic else 'Closing',
            'employee_evaluation': 'تقييم الموظفين' if is_arabic else 'Employee evaluations',
            'open_section': 'فتح التفاصيل' if is_arabic else 'Open details',
            'current_shift': 'الوردية الحالية' if is_arabic else 'Current shift',
            'operational_date': 'تاريخ الوردية' if is_arabic else 'Shift date',
            'no_active_shift': 'لا توجد وردية مفتوحة الآن.' if is_arabic else 'There is no active shift right now.',
            'start_shift': 'بدء الدوام' if is_arabic else 'Start shift',
            'stage_completed': 'تم تسجيل بداية الدوام.' if is_arabic else 'Start-of-shift tasks are complete.',
            'done': 'تم' if is_arabic else 'Done',
            'back_dashboard': 'الرجوع للملخص' if is_arabic else 'Back to overview',
            'back_followup': 'العودة إلى المتابعة' if is_arabic else 'Back to shift follow-up',
            'back_tasks': 'العودة إلى المهام' if is_arabic else 'Back to tasks',
            'my_profile': 'ملف الموظف' if is_arabic else 'My profile',
            'logout': 'تسجيل الخروج' if is_arabic else 'Sign out',
            'add_note': 'إضافة ملاحظة' if is_arabic else 'Add note',
            'add_stage_note': 'إضافة ملاحظة للمرحلة' if is_arabic else 'Add stage note',
            'add_followup': '+ إضافة متابعة' if is_arabic else '+ Add follow-up',
            'start_shift_for_followup': 'ابدأ الوردية أولًا لإضافة ملاحظة أو مهمة أو تذكير.' if is_arabic else 'Start your shift first to add a note, task, or reminder.',
            'followup_type_title': 'اختر نوع المتابعة' if is_arabic else 'Choose follow-up type',
            'followup_note': 'ملاحظة' if is_arabic else 'Note',
            'followup_task': 'مهمة' if is_arabic else 'Task',
            'followup_reminder': 'تذكير' if is_arabic else 'Reminder',
            'followup_note_hint': 'توثيق ملاحظة أو مشكلة' if is_arabic else 'Document an observation or issue',
            'followup_task_hint': 'شيء يجب إنجازه ومتابعته' if is_arabic else 'Work that must be completed and tracked',
            'followup_reminder_hint': 'تنبيه في الوقت الذي تحدده' if is_arabic else 'An alert at the time you set',
            'followup_title': 'العنوان' if is_arabic else 'Title',
            'followup_details': 'التفاصيل' if is_arabic else 'Details',
            'note_for_line': 'ملاحظة مرتبطة بالبند' if is_arabic else 'Note linked to this item',
            'note_reason': 'سبب الملاحظة' if is_arabic else 'Reason for the note',
            'additional_details': 'تفاصيل إضافية' if is_arabic else 'Additional details',
            'followup_image': 'صورة اختيارية' if is_arabic else 'Optional image',
            'add_photo': 'إرفاق صورة' if is_arabic else 'Attach a photo',
            'take_photo': 'التقاط بالكاميرا' if is_arabic else 'Take a photo',
            'choose_photo': 'اختيار من الاستوديو' if is_arabic else 'Choose from gallery',
            'followup_target': 'موعد المتابعة اختياري' if is_arabic else 'Optional target time',
            'reminder_time': 'وقت التذكير' if is_arabic else 'Reminder time',
            'reminder_recurrence': 'تكرار التذكير' if is_arabic else 'Reminder recurrence',
            'recurrence_once': 'مرة واحدة' if is_arabic else 'One time',
            'recurrence_daily': 'يومي' if is_arabic else 'Daily',
            'recurrence_weekly': 'أسبوعي' if is_arabic else 'Weekly',
            'recurrence_monthly': 'شهري' if is_arabic else 'Monthly',
            'save_followup': 'حفظ المتابعة' if is_arabic else 'Save follow-up',
            'complete_followup': 'تمت المعالجة' if is_arabic else 'Mark as resolved',
            'complete_reminder': 'تم لهذا الموعد' if is_arabic else 'Complete this occurrence',
            'share_whatsapp': 'مشاركة عبر واتساب' if is_arabic else 'Share via WhatsApp',
            'task_items': 'عناصر المهمة' if is_arabic else 'Task items',
            'task_item': 'عنصر المهمة' if is_arabic else 'Task item',
            'task_item_placeholder': 'اكتب العنصر المطلوب إنجازه' if is_arabic else 'Describe one item to complete',
            'add_task_item': '+ إضافة عنصر' if is_arabic else '+ Add item',
            'remove_task_item': 'حذف' if is_arabic else 'Remove',
            'remaining_items': 'عناصر متبقية' if is_arabic else 'items remaining',
            'next_midday': 'الانتقال إلى مهام وسط الدوام' if is_arabic else 'Continue to mid-shift tasks',
            'next_closing': 'الانتقال إلى مهام الإغلاق' if is_arabic else 'Continue to closing tasks',
            'close_shift': 'إغلاق الوردية' if is_arabic else 'Close shift',
            'evaluation_title': 'تقييم الموظفين' if is_arabic else 'Employee evaluations',
            'evaluation_today_summary': 'ملخص تقييمات اليوم' if is_arabic else 'Today\'s evaluation summary',
            'evaluation_start_shift_first': 'ابدأ الوردية أولًا' if is_arabic else 'Start the shift first',
            'evaluation_shift_required': 'التقييم يرتبط بالوردية الحالية.' if is_arabic else 'Evaluations belong to the current shift.',
            'evaluation_reviewed': 'تم تقييمهم' if is_arabic else 'Evaluated',
            'evaluation_staff_today': 'موظف اليوم' if is_arabic else 'staff today',
            'evaluation_remaining': 'المتبقي' if is_arabic else 'Remaining',
            'evaluation_employee': 'موظف' if is_arabic else 'employee',
            'evaluation_overall_performance': 'الأداء الكلي' if is_arabic else 'Overall performance',
            'evaluation_stars': 'نجوم' if is_arabic else 'stars',
            'evaluation_summary': 'تم تقييم' if is_arabic else 'Evaluated',
            'evaluation_of': 'من' if is_arabic else 'of',
            'evaluation_employee_label': 'الموظف' if is_arabic else 'Employee',
            'evaluation_select_employee': 'اختر موظفًا' if is_arabic else 'Choose an employee',
            'evaluation_show_indicators': 'إظهار مؤشرات التقييم' if is_arabic else 'Show evaluation indicators',
            'evaluation_absent_today': 'غائب اليوم' if is_arabic else 'Absent today',
            'evaluation_mark_present': 'اعتباره حاضرًا' if is_arabic else 'Mark present',
            'evaluation_saved': 'تقييم محفوظ — عدّله ثم احفظ إذا احتجت.' if is_arabic else 'Evaluation saved — edit it and save again if needed.',
            'evaluation_note': 'ملاحظة عامة اختيارية' if is_arabic else 'Optional overall note',
            'evaluation_note_placeholder': 'أي ملاحظة على أداء الموظف' if is_arabic else 'Any note about the employee\'s performance',
            'evaluation_save': 'حفظ التقييم' if is_arabic else 'Save evaluation',
            'rating_out_of_five': 'من 5' if is_arabic else 'out of 5',
            'attached_image': 'الصورة المرفقة' if is_arabic else 'Attached image',
        }

    def _render_private(self, template, values):
        """Prevent operational PWA pages from being retained on a shared device."""
        response = request.render(template, values)
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Pragma'] = 'no-cache'
        return response

    def _shift_overview_context(self, employee, is_arabic):
        """Build the existing shift projection for the dedicated PWA section."""
        shift = self._current_shift(employee)
        dashboard = self._monthly_dashboard(employee, is_arabic) if employee else False
        if not employee:
            return {'employee': employee, 'shift': shift, 'dashboard': dashboard}
        for summary in dashboard['stage_summaries']:
            summary['available'] = bool(shift and self._stage_order[summary['stage']] <= self._stage_order[shift.state])
            summary['complete_today'] = bool(shift and getattr(
                shift, self._stage_details[summary['stage']]['completion']) == 100)
        return {'employee': employee, 'shift': shift, 'dashboard': dashboard}

    def _today_board_context(self, employee, is_arabic):
        """Read the current user's actionable work without changing its owners."""
        dashboard = self._monthly_dashboard(employee, is_arabic) if employee else False
        shift = self._current_shift(employee) if employee else request.env['baseer.followup.shift']
        followups = self._followup_cards(employee, is_arabic) if employee else {'open_notes': []}
        statuses = []
        if shift:
            stage_name = self._stage_details[shift.state]['title_ar'] if is_arabic else self._stage_details[shift.state]['title_en']
            stage_lines = getattr(shift, self._stage_details[shift.state]['lines'])
            completed_lines = len(stage_lines.filtered('done'))
            statuses.append({
                'kind': 'shift', 'title': stage_name,
                'detail': '%s/%s' % (completed_lines, len(stage_lines)),
                'done': completed_lines == len(stage_lines),
                'href': '/employee-app/shift/%s' % shift.state,
            })
            staff = request.env['hr.employee'].sudo().search([
                ('company_id', '=', employee.company_id.id), ('active', '=', True), ('followup_excluded', '=', False),
            ], order='name')
            evaluated_ids = set(request.env['baseer.followup.employee.evaluation'].sudo().with_company(employee.company_id).search([
                ('shift_id', '=', shift.id),
            ]).mapped('employee_id').ids)
            absent_ids = set(shift.absence_ids.mapped('employee_id').ids)
            due_staff = [member for member in staff if member.id not in absent_ids]
            completed_evaluations = len([member for member in due_staff if member.id in evaluated_ids])
            statuses.append({
                'kind': 'evaluation', 'title': self._ui(is_arabic)['employee_evaluation'],
                'detail': '%s/%s' % (completed_evaluations, len(due_staff)),
                'done': completed_evaluations == len(due_staff),
                'href': '/employee-app/evaluation',
            })
        open_followups = followups['open_notes']
        recent_followups = (followups['open_notes'] + followups['resolved_notes'])[:8]
        return {
            'employee': employee, 'shift': shift, 'dashboard': dashboard,
            'today_statuses': statuses, 'today_followups': recent_followups,
        }

    def _revenue_trend(self, company, first_day, today):
        """Return the compact revenue trend only to admitted manager-app users."""
        if not self._has_manager_app_access():
            return {'available': False}

        current_end = today + timedelta(days=1)
        previous_start = first_day - relativedelta(months=1)
        previous_end = previous_start + (current_end - first_day)

        def posted_revenue(date_start, date_end):
            request.env.cr.execute("""
                SELECT COALESCE(-SUM(line.balance), 0)::numeric
                  FROM account_move_line AS line
                  JOIN account_account AS account ON account.id = line.account_id
                 WHERE line.company_id = %s
                   AND line.parent_state = 'posted'
                   AND line.date >= %s
                   AND line.date < %s
                   AND account.account_type IN ('income', 'income_other')
            """, [company.id, date_start, date_end])
            return Decimal(str(request.env.cr.fetchone()[0] or '0'))

        current_revenue = posted_revenue(first_day, current_end)
        previous_revenue = posted_revenue(previous_start, previous_end)
        percentage = None
        direction = 'neutral'
        if previous_revenue:
            percentage = ((current_revenue - previous_revenue) * Decimal('100') / abs(previous_revenue)).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP)
            direction = 'positive' if percentage > 0 else 'negative' if percentage < 0 else 'neutral'
        return {
            'available': True,
            'percentage': ('%+d' % int(percentage)) if percentage is not None else False,
            'has_comparison': percentage is not None,
            'direction': direction,
        }

    def _operational_alerts(self, employee, first_day, next_month_day, is_arabic, revenue):
        """Derive a compact, manager-owned alert strip from existing Odoo records."""
        evaluation_model = request.env['baseer.followup.employee.evaluation'].sudo().with_company(employee.company_id)
        evaluations = evaluation_model.search([
            ('evaluator_id', '=', employee.id), ('shift_id.operational_date', '>=', first_day),
            ('shift_id.operational_date', '<', next_month_day),
        ])
        alerts = []
        for rated_employee in evaluations.mapped('employee_id'):
            ratings = evaluations.filtered(lambda evaluation: evaluation.employee_id == rated_employee).mapped('line_ids.rating')
            percentage = round(sum(ratings) * 100 / (len(ratings) * 5)) if ratings else 0
            if ratings and percentage < 60:
                alerts.append({
                    'priority': 10, 'level': 'danger',
                    'message': ('أداء %s منخفض هذا الشهر — %s٪' % (rated_employee.name, percentage)) if is_arabic else ('%s performance is low this month — %s%%' % (rated_employee.name, percentage)),
                    'href': '/employee-app/evaluation?employee_id=%s' % rated_employee.id,
                })

        shift = self._current_shift(employee)
        if shift:
            staff = request.env['hr.employee'].sudo().search([
                ('company_id', '=', employee.company_id.id), ('active', '=', True), ('followup_excluded', '=', False),
            ], order='name')
            evaluated_employee_ids = set(request.env['baseer.followup.employee.evaluation'].sudo().with_company(employee.company_id).search([
                ('shift_id', '=', shift.id),
            ]).mapped('employee_id').ids)
            absent_employee_ids = set(shift.absence_ids.mapped('employee_id').ids)
            for staff_member in staff:
                if staff_member.id not in evaluated_employee_ids and staff_member.id not in absent_employee_ids:
                    alerts.append({
                        'priority': 20, 'level': 'warning',
                        'message': ('لم يتم تقييم %s في وردية اليوم' % staff_member.name) if is_arabic else ('%s has not been evaluated in today\'s shift' % staff_member.name),
                        'href': '/employee-app/evaluation?employee_id=%s' % staff_member.id,
                    })
            active_lines = getattr(shift, self._stage_details[shift.state]['lines'])
            incomplete_line = active_lines.filtered(lambda line: not line.done)[:1]
            if incomplete_line:
                stage_title = self._stage_details[shift.state]['title_ar'] if is_arabic else self._stage_details[shift.state]['title_en']
                alerts.append({
                    'priority': 30, 'level': 'warning',
                    'message': ('مهمة «%s» لم تُنجز في %s' % (incomplete_line.name, stage_title)) if is_arabic else ('“%s” is incomplete in %s' % (incomplete_line.name_en, stage_title)),
                    'href': '/employee-app/shift/%s' % shift.state,
                })

        open_items = request.env['baseer.followup.note'].sudo().with_company(employee.company_id).search([
            ('employee_id', '=', employee.id), ('state', '=', 'open'),
        ], order='target_at asc, reported_at desc, id desc')
        now = fields.Datetime.now()
        type_meta = {
            'note': (40, 'info', 'ملاحظة مفتوحة: %s', 'Open note: %s'),
            'task': (25, 'warning', 'مهمة تحتاج متابعة: %s', 'Task needs follow-up: %s'),
            'reminder': (12, 'danger', 'تذكير مستحق: %s', 'Reminder due: %s'),
        }
        for item in open_items:
            if item.item_type == 'reminder' and item.target_at and item.target_at > now:
                continue
            priority, level, message_ar, message_en = type_meta[item.item_type]
            message_name = item.name
            if item.item_type == 'task':
                message_name = ('%s — باقي %s' % (item.name, item.task_remaining_count)) if is_arabic else ('%s — %s remaining' % (item.name, item.task_remaining_count))
            alerts.append({
                'priority': priority, 'level': level,
                'message': (message_ar % message_name) if is_arabic else (message_en % message_name),
                'href': '/employee-app/notes',
            })
        if revenue.get('available') and revenue.get('has_comparison'):
            percentage = int(revenue['percentage'])
            if percentage < 0:
                alerts.append({
                    'priority': 15, 'level': 'danger',
                    'message': ('انخفض الإيراد هذا الشهر %s٪ مقارنة بالفترة السابقة' % abs(percentage)) if is_arabic else ('Revenue is down %s%% compared with the prior period' % abs(percentage)),
                    'href': '/employee-app/',
                })
            elif percentage > 0:
                alerts.append({
                    'priority': 90, 'level': 'success',
                    'message': ('ممتاز يا %s، الإيراد ارتفع %s٪ مقارنة بالفترة السابقة' % (employee.name, percentage)) if is_arabic else ('Great work, %s — revenue is up %s%% compared with the prior period' % (employee.name, percentage)),
                    'href': '/employee-app/',
                })
        return sorted(alerts, key=lambda alert: (alert['priority'], alert['message']))[:3]

    def _monthly_dashboard(self, employee, is_arabic):
        today = fields.Date.context_today(request.env.user)
        first_day = today.replace(day=1)
        next_month_day = first_day + relativedelta(months=1)
        shift_model = request.env['baseer.followup.shift'].sudo().with_company(employee.company_id)
        shifts = shift_model.search([
            ('employee_id', '=', employee.id),
            ('operational_date', '>=', first_day), ('operational_date', '<', next_month_day),
        ])
        total_shifts = len(shifts)
        # The monthly KPI intentionally uses the whole calendar month. A day only
        # counts once it has a fully closed operational shift; days without a
        # started shift remain incomplete instead of disappearing from the rate.
        days_in_month = (next_month_day - first_day).days
        completed_days = len({
            shift.operational_date for shift in shifts
            if shift.state == 'closed' and shift.operational_date
        })
        stage_summaries = []
        for stage, field_name in (
            ('opening', 'opening_completion'), ('midday', 'midday_completion'), ('closing', 'closing_completion'),
        ):
            percentage = round(sum(shifts.mapped(field_name)) / total_shifts) if total_shifts else 0
            stage_summaries.append({
                'stage': stage,
                'sequence': self._stage_order[stage],
                'name': self._stage_details[stage]['title_ar'] if is_arabic else self._stage_details[stage]['title_en'],
                'percentage': percentage,
                'has_data': bool(total_shifts),
            })
        # A day counts only when its whole shift has reached the locked closed state.
        # The close action itself enforces 100% opening, mid-shift and closing work
        # plus the required employee evaluations.
        shift_completion = round(completed_days * 100 / days_in_month) if days_in_month else 0
        evaluation_model = request.env['baseer.followup.employee.evaluation'].sudo().with_company(employee.company_id)
        evaluations = evaluation_model.search([
            ('evaluator_id', '=', employee.id), ('shift_id.operational_date', '>=', first_day),
            ('shift_id.operational_date', '<', next_month_day),
        ])
        rating_lines = evaluations.mapped('line_ids')
        team_quality = round(sum(rating_lines.mapped('rating')) * 100 / (len(rating_lines) * 5)) if rating_lines else 0
        templates = request.env['baseer.followup.evaluation.template'].sudo().search([
            ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', employee.company_id.id),
        ], order='sequence, id')
        performance_indicators = []
        for template in templates:
            ratings = rating_lines.filtered(lambda line: line.template_id == template).mapped('rating')
            performance_indicators.append({
                'name': template.name if is_arabic else template.name_en,
                'percentage': round(sum(ratings) * 100 / (len(ratings) * 5)) if ratings else 0,
                'has_data': bool(ratings),
            })
        open_notes = request.env['baseer.followup.note'].sudo().with_company(employee.company_id).search_count([
            ('employee_id', '=', employee.id), ('state', '=', 'open'),
        ])
        revenue = self._revenue_trend(employee.company_id, first_day, today)
        alerts = self._operational_alerts(employee, first_day, next_month_day, is_arabic, revenue)
        weekday_names_ar = ('الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد')
        today_label = ('%s %s' % (weekday_names_ar[today.weekday()], today.strftime('%d/%m/%Y'))
                       if is_arabic else today.strftime('%A %d/%m/%Y'))
        return {
            'today': today_label,
            'days_in_month': days_in_month,
            'completed_days': completed_days,
            'open_notes': open_notes,
            'shift_completion': shift_completion,
            'manager_noncompliance_alert': (100 - shift_completion) >= 5,
            'team_quality': team_quality,
            'revenue': revenue,
            'alerts': alerts,
            'stage_summaries': stage_summaries,
            'performance_indicators': performance_indicators,
            'has_evaluation_data': bool(rating_lines),
        }

    def _company_dashboard(self, company, is_arabic):
        """Read-only management summary; deliberately does not require a manager HR profile."""
        today = fields.Date.context_today(request.env.user)
        first_day = today.replace(day=1)
        next_month_day = first_day + relativedelta(months=1)
        shifts = request.env['baseer.followup.shift'].with_company(company).search([
            ('company_id', '=', company.id),
            ('operational_date', '>=', first_day), ('operational_date', '<', next_month_day),
        ])
        total_shifts = len(shifts)
        days_in_month = (next_month_day - first_day).days
        completed_days = len({shift.operational_date for shift in shifts if shift.state == 'closed' and shift.operational_date})
        stage_summaries = []
        for stage, field_name in (
            ('opening', 'opening_completion'), ('midday', 'midday_completion'), ('closing', 'closing_completion'),
        ):
            stage_summaries.append({
                'stage': stage,
                'sequence': self._stage_order[stage],
                'name': self._stage_details[stage]['title_ar'] if is_arabic else self._stage_details[stage]['title_en'],
                'percentage': round(sum(shifts.mapped(field_name)) / total_shifts) if total_shifts else 0,
                'has_data': bool(total_shifts),
            })
        evaluations = request.env['baseer.followup.employee.evaluation'].with_company(company).search([
            ('company_id', '=', company.id), ('shift_id.operational_date', '>=', first_day),
            ('shift_id.operational_date', '<', next_month_day),
        ])
        rating_lines = evaluations.mapped('line_ids')
        templates = request.env['baseer.followup.evaluation.template'].sudo().search([
            ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='sequence, id')
        performance_indicators = [{
            'name': template.name if is_arabic else template.name_en,
            'percentage': round(sum(ratings) * 100 / (len(ratings) * 5)) if ratings else 0,
            'has_data': bool(ratings),
        } for template in templates for ratings in [rating_lines.filtered(lambda line: line.template_id == template).mapped('rating')]]
        shift_completion = round(completed_days * 100 / days_in_month) if days_in_month else 0
        weekday_names_ar = ('الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد')
        return {
            'today': ('%s %s' % (weekday_names_ar[today.weekday()], today.strftime('%d/%m/%Y')) if is_arabic else today.strftime('%A %d/%m/%Y')),
            'days_in_month': days_in_month,
            'completed_days': completed_days,
            'open_notes': request.env['baseer.followup.note'].with_company(company).search_count([('company_id', '=', company.id), ('state', '=', 'open')]),
            'shift_completion': shift_completion,
            'manager_noncompliance_alert': (100 - shift_completion) >= 5,
            'team_quality': round(sum(rating_lines.mapped('rating')) * 100 / (len(rating_lines) * 5)) if rating_lines else 0,
            'revenue': self._revenue_trend(company, first_day, today),
            'alerts': [],
            'stage_summaries': stage_summaries,
            'performance_indicators': performance_indicators,
            'has_evaluation_data': bool(rating_lines),
        }

    # This is an application endpoint, not a website page.  Keeping it out of
    # website language routing prevents `/employee-app/` being rewritten to a
    # language-prefixed URL that does not belong to the PWA.
    @http.route(['/employee-app', '/employee-app/'], type='http', auth='public', methods=['GET'], multilang=False)
    def employee_app(self):
        if not request.session.uid:
            is_arabic = self._is_arabic()
            response = request.render('baseer_employee_followup.employee_app_login', {
                'is_arabic': is_arabic,
                'redirect_url': '/employee-app',
            })
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
            return response
        if not self._has_manager_app_access():
            is_arabic = self._is_arabic()
            response = request.render('baseer_employee_followup.employee_app_access_denied', {
                'is_arabic': is_arabic,
            })
            response.headers['Cache-Control'] = 'no-store'
            return response
        is_arabic = self._is_arabic()
        employee = self._employee_for_current_user()
        context = self._today_board_context(employee, is_arabic)
        context.update({'is_arabic': is_arabic, 'ui': self._ui(is_arabic)})
        return self._render_private('baseer_employee_followup.employee_app_today', context)

    @http.route('/employee-app/dashboard', type='http', auth='user', methods=['GET'], multilang=False)
    def employee_app_dashboard(self):
        """Keep monthly analytics separate from the daily action board."""
        self._require_manager_app_access()
        is_arabic = self._is_arabic()
        employee = self._employee_for_current_user()
        context = self._shift_overview_context(employee, is_arabic)
        context.update({'is_arabic': is_arabic, 'ui': self._ui(is_arabic)})
        shift = context['shift']
        if employee:
            context['dashboard']['opening_midday_summaries'] = [
                item for item in context['dashboard']['stage_summaries'] if item['stage'] in ('opening', 'midday')]
            context['dashboard']['closing_summary'] = next(
                item for item in context['dashboard']['stage_summaries'] if item['stage'] == 'closing')
        context['current_stage_title'] = (
            self._stage_details[shift.state]['title_ar'] if is_arabic else self._stage_details[shift.state]['title_en']
        ) if shift else False
        return self._render_private('baseer_employee_followup.employee_app', context)

    @http.route('/employee-app/shift', type='http', auth='user', methods=['GET'], multilang=False)
    def shift_overview(self):
        """Dedicated operational view; stage ownership stays in the existing model."""
        is_arabic = self._is_arabic()
        employee = self._employee_for_current_user()
        context = self._shift_overview_context(employee, is_arabic)
        context.update({'is_arabic': is_arabic, 'ui': self._ui(is_arabic)})
        return self._render_private('baseer_employee_followup.employee_app_shift_overview', context)

    @http.route('/employee-app/language/<string:language>', type='http', auth='public', methods=['GET'], csrf=False, multilang=False)
    def employee_app_language(self, language, next='/employee-app'):
        """Persist an explicit PWA language without changing the user's Odoo profile."""
        language = language if language in ('ar', 'en') else 'ar'
        next_url = next if next.startswith('/employee-app') else '/employee-app'
        response = request.redirect(next_url)
        response.set_cookie('baseer_shift_lang', language, max_age=60 * 60 * 24 * 365, samesite='Lax')
        return response

    @http.route('/employee-app/profile', type='http', auth='user', methods=['GET'], multilang=False)
    def employee_app_profile(self):
        """Read-only employee identity for the signed-in PWA user."""
        self._require_manager_app_access()
        is_arabic = self._is_arabic()
        return self._render_private('baseer_employee_followup.employee_app_profile', {
            'employee': self._employee_for_current_user(),
            'user': request.env.user,
            'is_arabic': is_arabic,
            'ui': self._ui(is_arabic),
        })

    @http.route('/employee-app/logout', type='http', auth='user', methods=['POST'], csrf=True, multilang=False)
    def employee_app_logout(self):
        """End the Odoo session, then return to the PWA sign-in page."""
        request.session.logout(keep_db=True)
        return request.redirect('/employee-app')

    @http.route('/employee-app/backend-dashboard-data', type='json', auth='user', methods=['POST'])
    def backend_dashboard_data(self):
        """Read-only native-Odoo dashboard payload backed by the PWA authority."""
        if not self._has_backend_dashboard_access():
            raise AccessError('You cannot view the follow-up dashboard.')
        company = self._selected_backend_company()
        is_arabic = self._is_arabic()
        ui = self._ui(is_arabic)
        dashboard = self._company_dashboard(company, is_arabic)
        today = fields.Date.context_today(request.env.user)
        first_day = today.replace(day=1)
        next_month_day = first_day + relativedelta(months=1)
        staff = request.env['hr.employee'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True), ('followup_excluded', '=', False),
        ], order='name', limit=50)
        evaluations = request.env['baseer.followup.employee.evaluation'].with_company(company).search([
            ('company_id', '=', company.id), ('shift_id.operational_date', '>=', first_day),
            ('shift_id.operational_date', '<', next_month_day), ('employee_id', 'in', staff.ids),
        ], order='evaluated_at desc, id desc')
        templates = request.env['baseer.followup.evaluation.template'].with_company(company).search([
            ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='sequence, id')
        performance_threshold = company.baseer_followup_performance_threshold
        employee_rows = []
        for staff_member in staff:
            staff_evaluations = evaluations.filtered(lambda evaluation: evaluation.employee_id == staff_member)
            ratings = staff_evaluations.mapped('line_ids.rating')
            percentage = round(sum(ratings) * 100 / (len(ratings) * 5)) if ratings else None
            note_count = len(staff_evaluations.filtered(lambda evaluation: bool((evaluation.note or '').strip())))
            latest = staff_evaluations[:1]
            evaluation_lines = staff_evaluations.mapped('line_ids')
            indicators = []
            for template in templates:
                template_ratings = evaluation_lines.filtered(lambda line: line.template_id == template).mapped('rating')
                rating = round(sum(template_ratings) / len(template_ratings), 1) if template_ratings else None
                filled_stars = int(Decimal(str(rating)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if rating is not None else 0
                indicators.append({
                    'id': template.id,
                    'name': template.name if is_arabic else (template.name_en or template.name),
                    'rating': rating,
                    'stars': [{'filled': star <= filled_stars} for star in range(1, 6)],
                })
            employee_rows.append({
                'id': staff_member.id,
                'name': staff_member.name,
                'photo_url': '/employee-app/backend-employee-avatar/%s' % staff_member.id,
                'percentage': percentage,
                'performance_state': ('pending' if percentage is None
                                      else ('below-threshold' if percentage < performance_threshold else 'on-target')),
                'note_count': note_count,
                'evaluated_at': fields.Datetime.context_timestamp(request.env.user, latest.evaluated_at).strftime('%d/%m/%Y %H:%M') if latest else False,
                'indicators': indicators,
            })
        employee_rows.sort(key=lambda row: (row['percentage'] is None, -(row['percentage'] or 0), row['name']))
        top_noted_employees = sorted(
            (row for row in employee_rows if row['note_count']),
            key=lambda row: (-row['note_count'], row['percentage'] is None, -(row['percentage'] or 0), row['name']),
        )[:5]
        followups = request.env['baseer.followup.note'].with_company(company).search([
            ('company_id', '=', company.id), ('state', '=', 'open'),
        ], order='target_at asc, reported_at desc, id desc', limit=10)
        followup_rows = [{
            'id': note.id,
            'type': ui['followup_%s' % note.item_type],
            'name': note.name,
            'description': note.description or False,
            'reported_at': fields.Datetime.context_timestamp(request.env.user, note.reported_at).strftime('%d/%m/%Y %H:%M'),
            'target_at': fields.Datetime.context_timestamp(request.env.user, note.target_at).strftime('%d/%m/%Y %H:%M') if note.target_at else False,
            'remaining_count': note.task_remaining_count,
        } for note in followups]
        return {
            'ui': ui,
            'is_arabic': is_arabic,
            'dashboard': dashboard,
            'employees': employee_rows,
            'performance_threshold': performance_threshold,
            'top_noted_employees': top_noted_employees,
            'followups': followup_rows,
        }

    @http.route('/employee-app/backend-employee-avatar/<int:employee_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def backend_employee_avatar(self, employee_id):
        """Serve the dashboard's employee thumbnail without granting general HR read access."""
        if not self._has_backend_dashboard_access():
            raise AccessError('You cannot view employee images.')
        company = self._selected_backend_company()
        employee = request.env['hr.employee'].sudo().search([
            ('id', '=', employee_id), ('company_id', '=', company.id),
            ('active', '=', True), ('followup_excluded', '=', False),
        ], limit=1)
        if not employee or not employee.image_128:
            return request.not_found()
        image_data = base64.b64decode(employee.image_128)
        if image_data.startswith(b'\x89PNG\r\n\x1a\n'):
            content_type = 'image/png'
        elif image_data.startswith(b'\xff\xd8\xff'):
            content_type = 'image/jpeg'
        elif image_data.startswith((b'GIF87a', b'GIF89a')):
            content_type = 'image/gif'
        elif image_data.startswith(b'RIFF') and image_data[8:12] == b'WEBP':
            content_type = 'image/webp'
        else:
            return request.not_found()
        return request.make_response(image_data, headers=[
            ('Content-Type', content_type),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    def _followup_cards(self, employee, is_arabic):
        ui = self._ui(is_arabic)
        notes = request.env['baseer.followup.note'].sudo().with_company(employee.company_id).search([
            ('employee_id', '=', employee.id),
        ], order='state asc, target_at asc, reported_at desc, id desc')
        note_cards = []
        for note in notes:
            type_label = ui['followup_%s' % note.item_type]
            message = '\n'.join(filter(None, [type_label, note.name, note.description or '', '%s: %s' % (ui['operational_date'], note.shift_id.operational_date)]))
            target_at = fields.Datetime.context_timestamp(request.env.user, note.target_at).strftime('%d/%m/%Y %H:%M') if note.target_at else False
            note_cards.append({
                'record': note, 'type_label': type_label, 'target_at': target_at,
                'remaining_count': note.task_remaining_count,
                'remaining_label': ('%s عناصر متبقية' % note.task_remaining_count) if is_arabic else ('%s items remaining' % note.task_remaining_count),
                'complete_label': ui['complete_reminder'] if note.item_type == 'reminder' and note.recurrence != 'once' else ui['complete_followup'],
                'whatsapp_url': 'https://wa.me/?text=%s' % quote(message, safe=''),
            })
        return {
            'open_notes': [card for card in note_cards if card['record'].state == 'open'],
            'resolved_notes': [card for card in note_cards if card['record'].state == 'resolved'],
            'ui': ui,
        }

    @http.route('/employee-app/notes', type='http', auth='user', methods=['GET'])
    def notes_history(self, **kwargs):
        return request.redirect('/employee-app/follow-up?tab=history')

    @http.route('/employee-app/shift/<string:stage>', type='http', auth='user', methods=['GET'])
    def stage_view(self, stage):
        employee = self._employee_for_current_user()
        if stage not in self._stage_details:
            raise AccessError('Unknown shift stage.')
        shift = self._current_shift(employee)
        if not shift:
            return request.redirect('/employee-app/shift')
        if self._stage_order[stage] > self._stage_order[shift.state]:
            return request.redirect('/employee-app/shift/%s' % shift.state)
        is_arabic = self._is_arabic()
        stage_info = self._stage_details[stage]
        midday_available = fields.Datetime.now() >= shift.started_at + timedelta(hours=4)
        completion_ready = getattr(shift, stage_info['completion']) == 100
        can_advance = (
            stage == shift.state
            and completion_ready
            and (stage != 'opening' or midday_available)
            and (stage != 'midday' or shift._required_evaluations_complete())
        )
        advance_lock_message = False
        if stage == 'opening' and completion_ready and not midday_available:
            advance_lock_message = (
                'يتاح وسط الدوام بعد أربع ساعات من بدء الوردية.'
                if is_arabic else 'Mid-shift becomes available four hours after the shift starts.'
            )
        elif stage == 'midday' and completion_ready and not shift._required_evaluations_complete():
            advance_lock_message = (
                'أكمل تقييم الموظفين المطلوبين قبل الانتقال إلى الإغلاق.'
                if is_arabic else 'Complete the required employee evaluations before starting closing.'
            )
        else:
            advance_lock_message = (
                'أكمل جميع بنود هذه المرحلة للوصول إلى 100٪ قبل المتابعة.'
                if is_arabic else 'Complete every task in this stage before continuing.'
            )
        return self._render_private('baseer_employee_followup.employee_app_stage', {
            'employee': employee, 'shift': shift, 'stage': stage,
            'stage_title': stage_info['title_ar'] if is_arabic else stage_info['title_en'],
            'stage_step': ('%s من 4' % self._stage_order[stage]) if is_arabic else ('%s of 4' % self._stage_order[stage]),
            'stage_lines': getattr(shift, stage_info['lines']),
            'stage_completion': getattr(shift, stage_info['completion']),
            'can_advance': can_advance,
            'advance_lock_message': advance_lock_message,
            'is_current_stage': stage == shift.state,
            'is_arabic': is_arabic, 'ui': self._ui(is_arabic),
        })

    @http.route('/employee-app/start', type='http', auth='user', methods=['POST'], csrf=True)
    def start_shift(self):
        self._require_manager_app_access()
        employee = self._employee_for_current_user()
        if not employee:
            raise AccessError('You cannot start a shift without an active employee profile.')
        request.env['baseer.followup.shift'].sudo().with_company(employee.company_id).action_start_for_employee(employee)
        return request.redirect('/employee-app/shift/opening')

    @http.route('/employee-app/task/<int:line_id>/toggle', type='http', auth='user', methods=['POST'], csrf=True)
    def toggle_task(self, line_id):
        employee = self._employee_for_current_user()
        line = request.env['baseer.followup.opening.line'].sudo().with_company(employee.company_id).browse(line_id).exists() if employee else request.env['baseer.followup.opening.line']
        if not employee or not line or line.shift_id.employee_id != employee or line.shift_id.state not in self._stage_order or self._stage_order[line.stage] > self._stage_order[line.shift_id.state]:
            raise AccessError('You can only update your own checklist.')
        line.write({'done': not line.done})
        if request.httprequest.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return request.make_json_response({
                'done': line.done,
                'completion': getattr(line.shift_id, self._stage_details[line.stage]['completion']),
            })
        return request.redirect('/employee-app/shift/%s' % line.stage)

    @http.route('/employee-app/stage/<string:stage>', type='http', auth='user', methods=['POST'], csrf=True)
    def set_stage(self, stage):
        employee = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(employee.company_id).search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if employee else request.env['baseer.followup.shift']
        if not employee or not shift or (stage not in self._stage_details and stage != 'closed'):
            raise AccessError('You cannot update this shift stage.')
        shift.action_set_stage(stage)
        return request.redirect('/employee-app/shift' if stage == 'closed' else '/employee-app/shift/%s' % stage)

    @http.route('/employee-app/note', type='http', auth='user', methods=['GET'])
    def note_form(self, line_id=None):
        employee = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(employee.company_id).search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if employee else request.env['baseer.followup.shift']
        line = request.env['baseer.followup.opening.line'].sudo().with_company(employee.company_id).browse(int(line_id)).exists() if line_id and employee else request.env['baseer.followup.opening.line']
        if not employee or not shift or (line and (line.shift_id != shift or self._stage_order[line.stage] > self._stage_order[shift.state])):
            raise AccessError('You cannot add a note here.')
        is_arabic = self._is_arabic()
        return self._render_private('baseer_employee_followup.employee_app_note', {
            'employee': employee,
            'shift': shift,
            'line': line,
            'is_arabic': is_arabic,
            'ui': self._ui(is_arabic),
            'item_type': 'note',
            'form_action': '/employee-app/note',
            'stage_title': self._stage_details[shift.state]['title_ar'] if is_arabic else self._stage_details[shift.state]['title_en'],
            'back_url': '/employee-app/shift/%s' % (line.stage if line else shift.state),
            'back_label': self._ui(is_arabic)['back_followup'],
        })

    @http.route('/employee-app/follow-up', type='http', auth='user', methods=['GET'])
    def followup_chooser(self, tab='entry'):
        employee = self._employee_for_current_user()
        shift = self._current_shift(employee)
        if not employee:
            raise AccessError('You cannot add a follow-up here.')
        is_arabic = self._is_arabic()
        followup_cards = self._followup_cards(employee, is_arabic)
        return self._render_private('baseer_employee_followup.employee_app_followup_chooser', {
            'is_arabic': is_arabic, 'shift': shift,
            'active_tab': tab if tab in ('entry', 'history') else 'entry',
            **followup_cards,
        })

    @http.route('/employee-app/follow-up/<string:item_type>', type='http', auth='user', methods=['GET'])
    def followup_form(self, item_type):
        employee = self._employee_for_current_user()
        shift = self._current_shift(employee)
        if item_type not in ('note', 'task', 'reminder') or not employee or not shift:
            raise AccessError('You cannot add a follow-up here.')
        is_arabic = self._is_arabic()
        return self._render_private('baseer_employee_followup.employee_app_note', {
            'employee': employee, 'shift': shift, 'line': False,
            'is_arabic': is_arabic, 'ui': self._ui(is_arabic),
            'item_type': item_type, 'form_action': '/employee-app/follow-up/%s' % item_type,
            'stage_title': self._stage_details[shift.state]['title_ar'] if is_arabic else self._stage_details[shift.state]['title_en'],
            'back_url': '/employee-app/follow-up',
            'back_label': self._ui(is_arabic)['back_tasks'],
        })

    def _target_at_from_form(self, value):
        if not value:
            return False
        try:
            local_value = datetime.fromisoformat(value)
            timezone = pytz.timezone(request.env.user.tz or 'UTC')
            return timezone.localize(local_value).astimezone(pytz.UTC).replace(tzinfo=None)
        except (TypeError, ValueError, pytz.UnknownTimeZoneError) as exc:
            raise ValidationError('Invalid follow-up time.') from exc

    def _create_followup_item(self, employee, shift, item_type, title, description, line_id=None, target_at=None, recurrence='once', task_items=None):
        line = request.env['baseer.followup.opening.line'].sudo().with_company(employee.company_id).browse(int(line_id)).exists() if line_id else request.env['baseer.followup.opening.line']
        task_items = [item.strip() for item in (task_items or []) if item and item.strip()]
        if item_type == 'task' and not task_items:
            raise ValidationError('A task requires at least one checklist item.')
        if len(task_items) > 10:
            raise ValidationError('A task can have at most ten checklist items.')
        title = task_items[0] if item_type == 'task' else title
        if (not title or item_type not in ('note', 'task', 'reminder') or
                (line and (line.shift_id != shift or self._stage_order[line.stage] > self._stage_order[shift.state]))):
            raise AccessError('You cannot add this follow-up here.')
        target_value = self._target_at_from_form(target_at)
        if item_type == 'reminder' and not target_value:
            raise ValidationError('A reminder requires a scheduled time.')
        if recurrence not in ('once', 'daily', 'weekly', 'monthly'):
            raise AccessError('Invalid reminder recurrence.')
        if item_type != 'reminder' and recurrence != 'once':
            raise AccessError('Only reminders can repeat.')
        image_file = request.httprequest.files.get('camera_image') or request.httprequest.files.get('image')
        values = {
            'name': title.strip(), 'description': '' if item_type == 'task' else (description or '').strip(),
            'item_type': item_type, 'target_at': target_value, 'recurrence': recurrence,
            'employee_id': employee.id, 'shift_id': shift.id,
            'line_id': line.id if line else False, 'stage': shift.state,
        }
        if item_type == 'task':
            values['item_ids'] = [(0, 0, {'name': name, 'sequence': (index + 1) * 10}) for index, name in enumerate(task_items)]
        if image_file and image_file.filename:
            values['image'] = base64.b64encode(image_file.read())
        request.env['baseer.followup.note'].sudo().with_company(employee.company_id).create(values)

    @http.route('/employee-app/note', type='http', auth='user', methods=['POST'], csrf=True)
    def create_note(self, title=None, description=None, line_id=None, **kwargs):
        employee = self._employee_for_current_user()
        shift = self._current_shift(employee)
        if not employee or not shift:
            raise AccessError('You cannot add a note here.')
        line = request.env['baseer.followup.opening.line'].sudo().with_company(employee.company_id).browse(int(line_id)).exists() if line_id else request.env['baseer.followup.opening.line']
        self._create_followup_item(employee, shift, 'note', title, description, line_id=line_id)
        return request.redirect('/employee-app/shift/%s' % (line.stage if line else shift.state))

    @http.route('/employee-app/follow-up/<string:item_type>', type='http', auth='user', methods=['POST'], csrf=True)
    def create_followup(self, item_type, title=None, description=None, target_at=None, recurrence='once', **kwargs):
        employee = self._employee_for_current_user()
        shift = self._current_shift(employee)
        if not employee or not shift:
            raise AccessError('You cannot add a follow-up here.')
        self._create_followup_item(
            employee, shift, item_type, title, description, target_at=target_at, recurrence=recurrence,
            task_items=request.httprequest.form.getlist('task_item'),
        )
        return request.redirect('/employee-app/follow-up')

    @http.route('/employee-app/follow-up/<int:item_id>/resolve', type='http', auth='user', methods=['POST'], csrf=True)
    def resolve_followup(self, item_id, next_url=None):
        employee = self._employee_for_current_user()
        item = request.env['baseer.followup.note'].sudo().with_company(employee.company_id).search([
            ('id', '=', item_id), ('employee_id', '=', employee.id), ('company_id', '=', employee.company_id.id),
        ], limit=1) if employee else request.env['baseer.followup.note']
        if not item:
            raise AccessError('You cannot update this follow-up.')
        item.action_resolve()
        return request.redirect('/employee-app/' if next_url in ('/employee-app', '/employee-app/') else '/employee-app/follow-up?tab=history')

    @http.route('/employee-app/follow-up/item/<int:item_id>/toggle', type='http', auth='user', methods=['POST'], csrf=True)
    def toggle_followup_item(self, item_id):
        employee = self._employee_for_current_user()
        item = request.env['baseer.followup.note.item'].sudo().with_company(employee.company_id).search([
            ('id', '=', item_id), ('note_id.employee_id', '=', employee.id), ('company_id', '=', employee.company_id.id),
        ], limit=1) if employee else request.env['baseer.followup.note.item']
        if not item:
            raise AccessError('You cannot update this task item.')
        item.action_toggle_done()
        return request.redirect('/employee-app/follow-up?tab=history')

    @http.route('/employee-app/evaluation', type='http', auth='user', methods=['GET'])
    def evaluation_form(self, employee_id=None):
        evaluator = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(evaluator.company_id).search([
            ('employee_id', '=', evaluator.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if evaluator else request.env['baseer.followup.shift']
        staff = request.env['hr.employee'].sudo().search([
            ('company_id', '=', evaluator.company_id.id), ('active', '=', True), ('followup_excluded', '=', False),
        ], order='name') if evaluator else request.env['hr.employee']
        selected_employee = staff.filtered(lambda employee: employee.id == int(employee_id))[:1] if employee_id and str(employee_id).isdigit() else request.env['hr.employee']
        templates = request.env['baseer.followup.evaluation.template'].sudo().search([
            ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', evaluator.company_id.id),
        ], order='sequence, id') if evaluator else request.env['baseer.followup.evaluation.template']
        evaluations = request.env['baseer.followup.employee.evaluation'].sudo().with_company(evaluator.company_id).search([
            ('shift_id', '=', shift.id),
        ]) if shift else request.env['baseer.followup.employee.evaluation']
        absences = request.env['baseer.followup.shift.absence'].sudo().with_company(evaluator.company_id).search([
            ('shift_id', '=', shift.id),
        ]) if shift else request.env['baseer.followup.shift.absence']
        absent_employee_ids = absences.mapped('employee_id').ids
        selected_evaluation = evaluations.filtered(lambda evaluation: evaluation.employee_id == selected_employee)[:1]
        rating_by_template = {
            line.template_id.id: line.rating
            for line in selected_evaluation.line_ids
            if line.template_id
        }
        report_day = shift.operational_date if shift else fields.Date.context_today(request.env.user)
        report_month_start = report_day.replace(day=1)
        monthly_evaluations = request.env['baseer.followup.employee.evaluation'].sudo().with_company(evaluator.company_id).search([
            ('evaluator_id', '=', evaluator.id),
            ('shift_id.operational_date', '>=', report_month_start),
            ('shift_id.operational_date', '<=', report_day),
        ]) if evaluator else request.env['baseer.followup.employee.evaluation']
        performance_evaluations = monthly_evaluations.filtered(
            lambda evaluation: not selected_employee or evaluation.employee_id == selected_employee)
        performance_ratings = performance_evaluations.mapped('line_ids.rating')
        average_rating = round(sum(performance_ratings) / len(performance_ratings), 1) if performance_ratings else 0
        overall_percentage = round(sum(performance_ratings) * 100 / (len(performance_ratings) * 5)) if performance_ratings else 0
        selected_percentage = overall_percentage if selected_employee and performance_ratings else False
        evaluated_lines = performance_evaluations.mapped('line_ids')
        performance_indicators = []
        for template in templates:
            template_ratings = evaluated_lines.filtered(lambda line: line.template_id == template).mapped('rating')
            performance_indicators.append({
                'name': template.name if self._is_arabic() else (template.name_en or template.name),
                'percentage': round(sum(template_ratings) * 100 / (len(template_ratings) * 5)) if template_ratings else 0,
                'has_data': bool(template_ratings),
            })
        return self._render_private('baseer_employee_followup.employee_app_evaluation', {
            'evaluator': evaluator, 'shift': shift, 'staff': staff,
            'selected_employee': selected_employee, 'templates': templates,
            'evaluated_employee_ids': evaluations.mapped('employee_id').ids,
            'absent_employee_ids': absent_employee_ids,
            'evaluated_count': len(evaluations),
            'selected_evaluation': selected_evaluation,
            'rating_by_template': rating_by_template,
            'remaining_count': max(0, len(staff) - len(set(evaluations.mapped('employee_id').ids) | set(absent_employee_ids))),
            'average_rating': average_rating,
            'overall_percentage': overall_percentage,
            'selected_percentage': selected_percentage,
            'performance_indicators': performance_indicators,
            'performance_title': ('مؤشرات أداء %s' % selected_employee.name if selected_employee else 'مؤشرات أداء الفريق') if self._is_arabic() else ('%s performance indicators' % selected_employee.name if selected_employee else 'Team performance indicators'),
            'is_arabic': self._is_arabic(),
            'ui': self._ui(self._is_arabic()),
        })

    @http.route('/employee-app/evaluation', type='http', auth='user', methods=['POST'], csrf=True)
    def create_evaluation(self, employee_id=None, note=None, **kwargs):
        evaluator = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(evaluator.company_id).search([
            ('employee_id', '=', evaluator.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if evaluator else request.env['baseer.followup.shift']
        staff = request.env['hr.employee'].sudo().search([
            ('id', '=', int(employee_id)), ('company_id', '=', evaluator.company_id.id), ('active', '=', True), ('followup_excluded', '=', False),
        ], limit=1) if evaluator and employee_id and str(employee_id).isdigit() else request.env['hr.employee']
        if not evaluator or not shift or not staff:
            raise AccessError('You cannot add an employee evaluation here.')
        if request.env['baseer.followup.shift.absence'].sudo().with_company(evaluator.company_id).search_count([
            ('shift_id', '=', shift.id), ('employee_id', '=', staff.id),
        ]):
            raise AccessError('An absent employee cannot be evaluated in this shift.')
        templates = request.env['baseer.followup.evaluation.template'].sudo().search([
            ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', evaluator.company_id.id),
        ], order='sequence, id')
        lines = []
        for template in templates:
            raw_rating = kwargs.get('rating_%s' % template.id)
            if raw_rating is None or not str(raw_rating).isdigit():
                raise AccessError('Invalid employee rating.')
            rating = int(raw_rating)
            if rating not in range(1, 6):
                raise AccessError('Invalid employee rating.')
            lines.append((0, 0, {
                'template_id': template.id, 'sequence': template.sequence,
                'name': template.name, 'name_en': template.name_en, 'rating': rating,
            }))
        image_file = request.httprequest.files.get('camera_image') or request.httprequest.files.get('image')
        values = {
            'employee_id': staff.id, 'evaluator_id': evaluator.id, 'shift_id': shift.id,
            'note': (note or '').strip(), 'line_ids': lines,
        }
        if image_file and image_file.filename:
            values['image'] = base64.b64encode(image_file.read())
        evaluation_model = request.env['baseer.followup.employee.evaluation'].sudo().with_company(evaluator.company_id)
        existing = evaluation_model.search([('shift_id', '=', shift.id), ('employee_id', '=', staff.id)], limit=1)
        if existing:
            existing.line_ids.unlink()
            existing.write(values)
        else:
            evaluation_model.create(values)
        return request.redirect('/employee-app/evaluation?employee_id=%s' % staff.id)

    @http.route('/employee-app/evaluation/absence', type='http', auth='user', methods=['POST'], csrf=True)
    def mark_employee_absent(self, employee_id=None):
        evaluator = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(evaluator.company_id).search([
            ('employee_id', '=', evaluator.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if evaluator else request.env['baseer.followup.shift']
        staff = request.env['hr.employee'].sudo().search([
            ('id', '=', int(employee_id)), ('company_id', '=', evaluator.company_id.id),
            ('active', '=', True), ('followup_excluded', '=', False),
        ], limit=1) if evaluator and employee_id and str(employee_id).isdigit() else request.env['hr.employee']
        if not evaluator or not shift or not staff:
            raise AccessError('You cannot mark this employee absent here.')
        request.env['baseer.followup.shift.absence'].sudo().with_company(evaluator.company_id).create({
            'shift_id': shift.id,
            'employee_id': staff.id,
        })
        return request.redirect('/employee-app/evaluation?employee_id=%s' % staff.id)

    @http.route('/employee-app/evaluation/absence/remove', type='http', auth='user', methods=['POST'], csrf=True)
    def remove_employee_absence(self, employee_id=None):
        evaluator = self._employee_for_current_user()
        shift = request.env['baseer.followup.shift'].sudo().with_company(evaluator.company_id).search([
            ('employee_id', '=', evaluator.id),
            ('state', 'in', ('opening', 'midday', 'closing')),
        ], limit=1) if evaluator else request.env['baseer.followup.shift']
        if not evaluator or not shift or not employee_id or not str(employee_id).isdigit():
            raise AccessError('You cannot change this absence here.')
        absence = request.env['baseer.followup.shift.absence'].sudo().with_company(evaluator.company_id).search([
            ('shift_id', '=', shift.id), ('employee_id', '=', int(employee_id)),
        ], limit=1)
        if absence:
            absence.unlink()
        return request.redirect('/employee-app/evaluation?employee_id=%s' % employee_id)

    @http.route('/employee-app/manifest.webmanifest', type='http', auth='public', methods=['GET'], csrf=False, multilang=False)
    def manifest(self):
        is_arabic = self._is_arabic()
        manifest = {
            'name': 'بصير شِفت' if is_arabic else 'Baseer Shift',
            'short_name': 'بصير شِفت' if is_arabic else 'Baseer Shift',
            'start_url': '/employee-app',
            'display': 'standalone',
            'background_color': '#f5f7fa',
            'theme_color': '#0d4774',
            'icons': [{
                'src': '/baseer_employee_followup/static/description/app-icon-shift-time-check.png?v=1',
                'sizes': '1254x1254',
                'type': 'image/png',
                'purpose': 'any',
            }],
        }
        return request.make_response(json.dumps(manifest), headers=[('Content-Type', 'application/manifest+json')])

    @http.route('/employee-app/sw.js', type='http', auth='public', methods=['GET'], csrf=False, multilang=False)
    def service_worker(self):
        script = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));"""
        return request.make_response(script, headers=[('Content-Type', 'application/javascript')])
