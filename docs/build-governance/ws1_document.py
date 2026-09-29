"""Record WS1 acceptance evidence and release handoff from observed results."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / 'docs/build-governance'
OUT = ROOT / 'docs/releases/2026-09-09-simple-work-schedules'

def ui():
    data = dict(feature='WS1 simple work schedules', environment='QA localhost:18070',
        checked_at=datetime.now(timezone.utc).isoformat(), agent='root actual in-app browser',
        status='PASS', checks=[
        'Arabic desktop: six weekdays, 08:00-12:00 and 16:00-22:00 produce 60:00 weekly and 10.00 daily.',
        'QA template 262 saved using native UI, then imported with both periods and selected days intact.',
        'Simplified template form shows days/times, weekly/daily totals, company and timezone; no native FTE grid.',
        'Arabic mobile 390x844: native period cards, child period form, 22:00-06:00 produces 08:00 (+1), 48:00 weekly for six days.',
        'Mobile DOM measured viewport/document 390px and form 375px with no horizontal overflow.',
        'English desktop labels and weekday names verified after language switch.',
        'Native employee Payroll tab button opens wizard with correct employee, company, timezone and effective date; canceled without assignment.',
        'Final mobile labels and empty-state checked after final translation refresh.'],
        mutations=['Only QA test template WS1 UI دوام فترتين, calendar 262; no employee assigned.'],
        limitations=['No claim of English mobile visual verification; English desktop and Arabic mobile verified.',
                      'Native renderer selects mobile card mode when dialog opens; resize tests reopened dialog.'],
        screenshots='Inspected in root tool output; no standalone screenshot files retained.')
    (G/'ws1-ui.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')

def delivery():
    candidate=json.loads((OUT/'candidate.json').read_text(encoding='utf8'))
    preserved=json.loads((OUT/'main-preservation.json').read_text(encoding='utf8'))
    backup=json.loads((OUT/'main-backup.json').read_text(encoding='utf8'))
    commit=candidate['commit']
    text=f'''# WS1 — تبسيط جداول الدوام

نُشر `baseer_work_schedule 19.0.1.0.0` على الأصلية `baseer_dev`، المنفذ 18069، بتاريخ 2026-09-09. المصدر المجمد `{commit}` في `.local-backups/simple-work-schedules-20260909/candidate`. أضيف الموديول وحده إلى الإصدار المقبول PT1؛ جميع الموديولات السابقة محفوظة ببصماتها.

## الاستخدام

- **القوالب:** الموظفون ← التهيئة ← قوالب الدوام ← جدول جديد. اختر الأيام مرة واحدة وأضف فترات من/إلى. اختر أيامًا مختلفة للفترة عند الحاجة، واحفظ القالب.
- **الموظف:** ملف الموظف ← كشوف المرتبات ← تحديد جدول الدوام. أدخل الأوقات مباشرة أو ابدأ من جدول موجود، واختر تاريخ السريان. يمكن حفظ نسخة كقالب.
- يستعمل المساران تقويم أودو الأصلي. كل موظف يحصل على نسخة مستقلة، فلا يؤدي تعديل دوامه إلى تغيير دوام زملائه. تعديل القالب يتم بالنسخ مع بقاء التاريخ السابق.
- مثال 21:00 إلى 03:00 = 6 ساعات، والنهاية في اليوم التالي. تجمع الساعات آليًا ويُمنع التداخل حتى عبر نهاية الأسبوع.
- متاح لمدير الموارد البشرية ضمن الشركة الحالية؛ صلاحيات الحضور والإجازات الذاتية الأصلية باقية.

## التكامل وحدوده

الحضور والإجازات والرواتب تستخدم تقويم أودو ونسخ بيانات الموظف الأصلية، مع توافق للحساب التاريخي لأيام العمل في Odoo Mates. لا يضيف الموديول خصومات حضور أو سداد رواتب تلقائيًا، ولا يعدل مسيرات معتمدة.

السريان اليوم أو المستقبل ويُمنع عند تعارض سجلات في الفترة المتأثرة. إذا تغير تقسيم الراتب الأساسي والإضافي بسبب الساعات، يجب بدء التغيير أول الشهر. إجازات اليوم الكامل تعتمد تواريخ أودو المدنية، حتى إذا عبر الشفت منتصف الليل؛ ليس هذا محركًا جديدًا لاحتساب إجازات الشفت. القوالب القديمة التي تحتوي عدد ساعات فقط تحتاج إدخال أوقات فعلية. المنطقة الزمنية والإجازات الرسمية تُحفظ؛ لا يُقبل قالب بمنطقة زمنية مختلفة عن تقويم الموظف.

## الفحص والنقل

نجح 107/107 فحوص تكامل مع rollback و21/21 فحوص تزامن بمعاملتين وتنظيف البيانات. اختبرت العربية والإنجليزية على الكمبيوتر والعربية على الجوال، بما فيها إدخال فترتين، استيراد القالب، عبور الليل، فتح الإعداد من الموظف، وعدم التمرير الأفقي عند عرض 390px. ليست هذه شهادة حمل إنتاجي أو فحصًا بصريًا للجوال الإنجليزي.

قبل النقل أوقفت الأصلية وأُخذت نسخة متسقة من قاعدة البيانات والمرفقات والمصدر. مسار النسخة `{backup['directory']}`؛ فُحص {backup['attachment_references_verified']} مرجع مرفق. لم تُجرَ استعادة جديدة لهذه اللقطة؛ فُحص أرشيفها ومسار الاستعادة اختُبر في أعمال النسخ السابقة. بعد التثبيت تطابقت **كل الصفوف والأعمدة السابقة في {preserved['protected_tables']} جدولًا محميًا**، تشمل المحاسبة والرواتب والحضور والإجازات والشركات والشركاء وPOS والموارد. أضيفت حقول وجداول الموديول فقط؛ لم تُسند جداول جديدة لموظفين قائمين.

الأدلة: [المرشح](candidate.json)، [الفحوص](ws1_checks.json)، [التزامن](ws1_concurrency.json)، [الواجهة](ws1-ui.json)، [النسخة السابقة](main-backup.json)، [سلامة البيانات](main-preservation.json)، [التشغيل](runtime.json)، [قرار ما قبل النقل](PREDEPLOY-GO.md).

## التشغيل والرجوع وإعادة الاستخدام

حُدّث ربط المصدر الحي في compose وربط الأرشيف في برنامج النسخ اليومي إلى WS1. يُحفظ المجلد المجمد ولا يُحرر. دليل التشغيل المركزي في `docs/operations/2026-09-09-environments/README.md`.

الرجوع يتطلب إيقاف الأصلية واستعادة قاعدة البيانات والمرفقات والمصدر المتوافق من النسخة أعلاه، ثم استعادة إعدادات compose المحفوظة في `.local-backups/simple-work-schedules-20260909`. لا يكفي إرجاع ملفات المصدر بعد إضافة مخطط البيانات. إذا أُدخلت معاملات جديدة بعد النقل، لا تستعد اللقطة فوقها؛ يلزم ترحيل تصحيحي أو خطة لحفظ المعاملات الجديدة.

الموديول مستقل عن تعديل core/vendor، يعتمد `baseer_payroll` و`hr_attendance` وموديولات اعتمادهما على Odoo 19 Community. يمكن نقله مع الاعتمادات المقبولة؛ لا يعني ذلك التوافق مع جميع إصدارات أودو. تجميع حزمة بصير كاملة مؤجل إلى انتهاء التعديلات كما اتفق المستخدم.
'''
    (OUT/'HANDOFF.md').write_text(text,encoding='utf8')
    header=f'WS1 current MAIN release (2026-09-09): `{commit}`, frozen source `.local-backups/simple-work-schedules-20260909/candidate`; adds native simple schedule templates and employee setup. Earlier PT1/BN1/MP3 descriptions below are historical. Current evidence: `docs/releases/2026-09-09-simple-work-schedules/HANDOFF.md`.\n\n'
    for rel in ['README.md','docs/architecture/registry/INDEX.md','docs/operations/2026-09-09-environments/README.md']:
        p=ROOT/rel
        p.write_text(header+p.read_text(encoding='utf8'),encoding='utf8')
    with (G/'SIMPLE-WORK-SCHEDULES.md').open('a',encoding='utf8') as f:
        f.write(f'\n16. نقل WS1 إلى الأصلية: المرشح `{commit}`، مع نسخة متسقة ومطابقة {preserved["protected_tables"]} جدولًا محميًا وHTTP 200. المصدر وربط النسخ اليومي محدّثان. وثيقة التسليم في مسار الإصدار أعلاه؛ القرار المستقل النهائي في REVIEW.md.\n')

if __name__ == '__main__':
    {'ui':ui,'delivery':delivery}[sys.argv[1]]()
