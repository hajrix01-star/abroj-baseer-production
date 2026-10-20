import type { Language } from '../ui/dictionary';
const en = {
  gallery: 'Photos and files', storage: 'Device storage', all: 'All', image: 'Photos', file: 'Files', audio: 'Audio',
  newest: 'Newest', oldest: 'Oldest', largest: 'Largest', more: 'Load more', empty: 'No shared media in this view.',
  cached: 'Saved page only. Connect to browse more media.', failed: 'Unable to load. Try again.',
  forbidden: 'This media is no longer available to your account.', unavailable: 'Connect to browse shared media.',
  keep: 'Keep offline', unkeep: 'Release offline copy', kept: 'Kept on this device', missing: 'Offline copy unavailable',
  pinFailed: 'Could not save offline. Check free space and try again.', message: 'Open message',
  total: 'Cached on this device', protected: 'Protected from cleanup', files: 'Files', size: 'Size',
  clean: 'Clean temporary copies', preview: 'Review cleanup', confirm: 'Clean from device', cancel: 'Cancel',
  warning: 'Only temporary copies on this device will be removed. They will need a connection to download again. Messages and server originals stay unchanged.',
  auto: 'Clean unused copies after 30 days', autoHint: 'Based on last use. Offline copies and pending sends are protected.',
  previewHint: 'This plan expires after 5 minutes. Files in use or newly protected will be skipped.',
  deleted: 'Removed', skipped: 'Skipped', errors: 'Could not remove', partial: 'Some copies were not removed. Review the result below.',
  complete: 'Temporary copies cleaned', nothing: 'No temporary copies are eligible for cleanup.',
  cleanupFailed: 'Cleanup could not finish. Refresh storage and review a new plan.',
  deviceOnly: 'These figures describe app copies on this device, not server storage.', refresh: 'Refresh',
};
const ar: Record<keyof typeof en, string> = {
  gallery: 'الصور والملفات', storage: 'تخزين الجهاز', all: 'الكل', image: 'الصور', file: 'الملفات', audio: 'الصوتيات',
  newest: 'الأحدث', oldest: 'الأقدم', largest: 'الأكبر', more: 'عرض المزيد', empty: 'لا مرفقات مشتركة ضمن هذا العرض.',
  cached: 'هذه صفحة محفوظة فقط. اتصل بالإنترنت لاستعراض المزيد.', failed: 'تعذّر التحميل. حاول مرة أخرى.',
  forbidden: 'لم تعد هذه المرفقات متاحة لحسابك.', unavailable: 'اتصل بالإنترنت لاستعراض المرفقات.',
  keep: 'الاحتفاظ دون اتصال', unkeep: 'إلغاء الاحتفاظ', kept: 'محفوظ على هذا الجهاز', missing: 'النسخة دون اتصال غير متاحة',
  pinFailed: 'تعذّر الاحتفاظ بالملف. تحقق من المساحة وحاول مجددًا.', message: 'فتح الرسالة',
  total: 'النسخ المؤقتة على الجهاز', protected: 'محمي من التنظيف', files: 'الملفات', size: 'الحجم',
  clean: 'تنظيف النسخ المؤقتة', preview: 'مراجعة التنظيف', confirm: 'تنظيف من الجهاز', cancel: 'إلغاء',
  warning: 'تُزال النسخ المؤقتة من هذا الجهاز فقط، وستحتاج اتصالًا لتنزيلها مجددًا. تبقى الرسائل والأصول على الخادم دون تغيير.',
  auto: 'تنظيف النسخ غير المستخدمة بعد 30 يومًا', autoHint: 'حسب آخر استخدام. تُحمى نسخ الأوفلاين والملفات التي تنتظر الإرسال.',
  previewHint: 'تنتهي الخطة بعد 5 دقائق. تُستثنى الملفات المستخدمة أو المحمية بعد المراجعة.',
  deleted: 'أُزيل', skipped: 'مستثنى', errors: 'تعذّرت إزالته', partial: 'لم تُزل بعض النسخ. راجع النتيجة أدناه.',
  complete: 'اكتمل تنظيف النسخ المؤقتة', nothing: 'لا نسخ مؤقتة مؤهلة للتنظيف.',
  cleanupFailed: 'تعذّر إكمال التنظيف. حدّث المساحة وراجع خطة جديدة.',
  deviceOnly: 'هذه مساحة نسخ التطبيق على الجهاز، وليست مساحة الخادم.', refresh: 'تحديث',
};
export type MediaWord = keyof typeof en;
export const mediaTranslator = (language: Language) => (key: MediaWord): string => language === 'ar' ? ar[key] : en[key];
