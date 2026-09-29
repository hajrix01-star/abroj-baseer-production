# PRC-WHATSAPP-RESEND-001 — تسليم حي

**قرار التسليم:** GO

**المرشح والوجهة:** commit `c7696ec`، الوسم `procurement-whatsapp-resend-live-2026-09-15`، GitHub `main`، ثم Hostinger `/srv/abroj-baseer-production/releases/c7696ec`.

## النطاق

فرق المرشح عن خط اللايف السابق `9e6da7e` محصور في إضافة
`baseer_procurement_requests`: نص رسالة واتساب بلا رقم طلب (التاريخ بدلًا منه)،
وزر رمز واتساب فقط يعيد فتح الرسالة في `draft` و`sent` و`received` و`purchased`.
لا يغير الإجراء حالة الطلب أو الاستلام أو المخزون أو المحاسبة؛ حالة `cancel`
محجوبة من الواجهة والخادم.

## دليل القبول والتشغيل

- فحص Python و`git diff --check` نجحا، واختبار Odoo المستهدف
  `ProcurementFlowCase.test_whatsapp_can_be_resent_during_every_active_request_stage`
  نجح في قاعدة معزولة.
- مراجعة الأمن المستقلة: GO؛ مراجعة القبول: لا مانع وظيفي بعد تثبيت المرشح
  وتشغيل الاختبار.
- أرشيف النشر SHA-256:
  `ab40a177804bdc3094f5051f191fb69146bfd84cc22d1c99ca73e25dfebd18ab`.
- أُخذ زوج استرجاع جديد من قاعدة `baseer_prod` وfilestore قبل الترقية.
- رُقّيت إضافة `baseer_procurement_requests` فقط. أظهر اختبار الاستعادة
  المعزول من نسخة ما قبل الترقية أن عدادات الكيانات المحمية تطابق اللايف بعد
  الترقية: 8,558 قيود، 21,207 سطر قيد، 4,192 دفعة، 50 موظفًا، 0 مسير راتب،
  341 جهة اتصال، و4 طلبات مشتريات مع 4 أسطر.
- فحص `/web/login` نجح محليًا وعبر `https://baseer.abroj.sa/web/login`.

## الاسترجاع

نسخة الاسترجاع المتسقة محفوظة في Hostinger تحت بادئة
`procurement-whatsapp-20260915T095535Z`. الاسترجاع يعيد زوج قاعدة البيانات
والـfilestore مع إعادة الرابط `current` إلى `9e6da7e`.

## النطاق غير المعاد فحصه

لم نعد فحص موديولات أو رحلات سبق نشرها في `9e6da7e`؛ فرق هذا التسليم لا يمسها.
