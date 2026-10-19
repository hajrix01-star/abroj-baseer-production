import type { Language } from '../ui/dictionary';
const en = {
  tasks: 'Tasks', subtitle: 'Assign and follow up', mine: 'Assigned to me', created: 'Assigned by me', open: 'Active', done: 'Completed', cancelled: 'Cancelled',
  new: 'New', in_progress: 'In progress', newTask: 'New task', title: 'What needs doing?', titleExample: 'Repair the dining-room air conditioner',
  company: 'Company', assignee: 'Assigned to', creator: 'Assigned by', due: 'Due date (optional)', reminder: 'Reminder (optional)', moreDetails: 'Additional details',
  description: 'Description (optional)', assign: 'Assign task', chooseAssignee: 'Choose an assignee', searchAssignees: 'Search people', noAssignees: 'No eligible people found.',
  noTasks: 'No tasks in this list', emptyHelp: 'Try another filter or create a task.', start: 'Start task', complete: 'Mark completed', cancel: 'Cancel task', reassign: 'Reassign task',
  note: 'Execution note (optional)', lastNote: 'Latest note', completedBy: 'Completed by', completedAt: 'Completed at', completionNote: 'Completion note',
  back: 'Back', close: 'Close', retry: 'Try again', refresh: 'Refresh', loadMore: 'Load more', loading: 'Loading', chooseCompany: 'Choose a company first.',
  noDate: 'No due date', noDescription: 'No additional description.', noAccess: 'No permission to view tasks', offline: 'Connect to use tasks',
  permissionHelp: 'Task permissions come from the Odoo user settings.', verifying: 'Checking your access', error: 'Could not load tasks. Try again.',
  forbidden: 'Your task access changed. Refresh after your permissions are checked.', conflict: 'The task changed. Refresh before acting again.',
  serverUpdateRequired: 'Tasks require a server update.', validation: 'Check the title, company, assignee and dates.', storage: 'Could not safely save the attempt. Try again.',
  unknown: 'Result unknown. Retry the saved attempt to check the same operation.', pending: 'Unresolved attempts', retryAttempt: 'Retry saved attempt',
  pendingBlock: 'Resolve the saved attempt before repeating this action.', cancelQuestion: 'Cancel this task?', cancelHelp: 'Cancellation is final. The task cannot be reopened.',
  confirmCancel: 'Cancel task', keepTask: 'Keep task', reminderHelp: 'Choose a reminder no later than the due date. Closed-app notifications are not enabled.',
  reminderDue: 'Reminder is due', reminderDate: 'Reminder', unavailable: 'Unavailable', listLimit: 'Showing up to 200 tasks. Refresh to return to the newest.',
  assigneeLimit: 'Showing up to 200 people. Search to find another.', saving: 'Saving', taskSaved: 'Task assigned', taskUpdated: 'Task updated', allCompanies: 'All authorized companies',
  changeAssignee: 'Change assignee', nothingSelected: 'Choose a person', optionalNote: 'Note (optional)', noCompletionDetails: 'Completion details are unavailable for this older task.',
} as const;
const ar: Record<keyof typeof en, string> = {
  tasks: 'المهام', subtitle: 'تكليف ومتابعة', mine: 'مسندة إليّ', created: 'أسندتها', open: 'نشطة', done: 'منجزة', cancelled: 'ملغاة',
  new: 'جديدة', in_progress: 'قيد التنفيذ', newTask: 'مهمة جديدة', title: 'المطلوب', titleExample: 'إصلاح مكيف الصالة',
  company: 'الشركة', assignee: 'المكلّف', creator: 'أسندها', due: 'موعد الإنجاز (اختياري)', reminder: 'التذكير (اختياري)', moreDetails: 'تفاصيل إضافية',
  description: 'الوصف (اختياري)', assign: 'إسناد المهمة', chooseAssignee: 'اختيار المكلّف', searchAssignees: 'البحث عن موظف', noAssignees: 'لا يوجد موظفون مؤهلون مطابقون.',
  noTasks: 'لا توجد مهام في هذه القائمة', emptyHelp: 'غيّر التصفية أو أضف مهمة جديدة.', start: 'بدء التنفيذ', complete: 'تم التنفيذ', cancel: 'إلغاء المهمة', reassign: 'إعادة الإسناد',
  note: 'ملاحظة التنفيذ (اختياري)', lastNote: 'آخر ملاحظة', completedBy: 'أنجزها', completedAt: 'وقت الإنجاز', completionNote: 'ملاحظة الإنجاز',
  back: 'رجوع', close: 'إغلاق', retry: 'إعادة المحاولة', refresh: 'تحديث', loadMore: 'تحميل المزيد', loading: 'جارٍ التحميل', chooseCompany: 'اختر الشركة أولًا.',
  noDate: 'دون موعد', noDescription: 'لا يوجد وصف إضافي.', noAccess: 'ليس لديك صلاحية عرض المهام', offline: 'اتصل لاستخدام المهام',
  permissionHelp: 'صلاحيات المهام من إعدادات المستخدم في أودو.', verifying: 'جارٍ التحقق من صلاحياتك', error: 'تعذّر تحميل المهام. حاول مرة أخرى.',
  forbidden: 'تغيرت صلاحية المهام. حدّث القائمة بعد التحقق من حقوقك.', conflict: 'تغيرت المهمة. حدّثها قبل إجراء تعديل آخر.',
  serverUpdateRequired: 'يتطلب قسم المهام تحديث الخادم.', validation: 'راجع المطلوب والشركة والمكلّف والمواعيد.', storage: 'تعذّر حفظ المحاولة بأمان. حاول مرة أخرى.',
  unknown: 'النتيجة غير محسومة. أعد المحاولة المحفوظة للتحقق من العملية نفسها.', pending: 'محاولات غير محسومة', retryAttempt: 'إعادة المحاولة المحفوظة',
  pendingBlock: 'احسم المحاولة المحفوظة قبل تكرار الإجراء.', cancelQuestion: 'إلغاء المهمة؟', cancelHelp: 'الإلغاء نهائي. لا يمكن إعادة فتح المهمة.',
  confirmCancel: 'إلغاء المهمة', keepTask: 'إبقاء المهمة', reminderHelp: 'اختر تذكيرًا لا يتجاوز موعد الإنجاز. تنبيهات التطبيق المغلق غير مفعّلة.',
  reminderDue: 'حان موعد التذكير', reminderDate: 'التذكير', unavailable: 'غير متاح', listLimit: 'نعرض 200 مهمة كحد أقصى. حدّث القائمة للعودة إلى الأحدث.',
  assigneeLimit: 'نعرض 200 موظف كحد أقصى. ابحث عن الموظف المطلوب.', saving: 'جارٍ الحفظ', taskSaved: 'أُسندت المهمة', taskUpdated: 'حُدّثت المهمة', allCompanies: 'كل الشركات المصرح بها',
  changeAssignee: 'تغيير المكلّف', nothingSelected: 'اختر موظفًا', optionalNote: 'ملاحظة (اختياري)', noCompletionDetails: 'تفاصيل الإنجاز غير متاحة لهذه المهمة القديمة.',
};
export type TaskWord = keyof typeof en;
export const taskTranslator = (language: Language) => (word: TaskWord): string => (language === 'ar' ? ar : en)[word];
export function taskErrorWord(error: unknown): TaskWord {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  if (['unknown', 'outcome_unknown', 'write_in_progress'].includes(code)) return 'unknown';
  if (['pending_attempt', 'pending_capacity'].includes(code)) return 'pendingBlock';
  if (code === 'server_update_required') return 'serverUpdateRequired';
  if (code.includes('conflict')) return 'conflict';
  if (code.includes('storage') || code.includes('journal')) return 'storage';
  if (['forbidden', 'unauthorized', 'company_forbidden'].includes(code)) return 'forbidden';
  if (code === 'invalid_payload') return 'validation';
  if (code === 'stale') return 'verifying';
  return 'error';
}
