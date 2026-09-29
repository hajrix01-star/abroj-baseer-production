import json
import re
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=root/'docs/releases/2026-09-09-work-schedule-time-picker'
c=json.loads((out/'candidate.json').read_text())
p=json.loads((out/'main-preservation.json').read_text())
b=json.loads((out/'main-backup.json').read_text())
text=f'''# WS2 — اختيار وقت الدوام بنظام 24 ساعة

نُشر `baseer_work_schedule 19.0.1.0.1` على الأصلية `baseer_dev` في 2026-09-09. المرشح `{c['commit']}`، والمصدر المجمد `.local-backups/work-schedule-time-picker-20260909/candidate`.

استُبدل النص الحر في «من» و«إلى» باختيار الساعة والدقيقة، في قوالب الدوام وإعداد الموظف، على الكمبيوتر والجوال. الساعات00–23 والدقائق00–59 بأرقام غربية في العربية والإنجليزية. يسمح وقت النهاية وحده بـ24:00 ويثبت الدقيقة00. مثال21:00–03:00 يعطي06:00 في الخلفية مع علامة اليوم التالي.

وقت الإدخال يحفظ بصيغةHH:MM الحالية. لم تتغير ملفات الخلفية أو الصلاحيات أو حسابات الرواتب أو جداول الدوام القائمة. لا مكتبة إضافية أو تعديلcore؛ عنصر مشترك يعتمد أدواتHTML الأصلية داخل حقلOdoo. مظهر قائمة الاختيار يتبع الجهاز. تتعطل القائمتان أثناء رد onchange ثم تعودان، لحماية الاختيار من ردود قديمة.

## الفحص

نجحت12فحوص للمكون تشمل تحديثًا مؤجلًا ومرفوضًا، منع التداخل،24:00، والتنقل بـTab. اختُبرت الواجهة الفعلية بالعربية والإنجليزية على الكمبيوتر والجوال390px، والارتفاع44px دون تمرير أفقي. أثبت الحفظ والاستيراد فيQA بقاء وقت الشفت الليلي.09:07–15:43يعطي06:36دون تقريب. حُذف قالب الاختبار388 ولم يُغيّر دوام أي موظف. اختباراتWS1 السابقة107+21 تخص الخلفية المطابقة بالبصمة؛ لا يدّعي هذا الإصدار إعادة تشغيلها أو اختبار حمل جديد.

## النقل والتشغيل

أُخذت نسخة متسقة قبل الترقية في `{b['directory']}`، مع فحص{b['attachment_references_verified']}مرجع مرفق. لم تُعد تجربة الاستعادة لهذه اللقطة؛ مسار الاستعادة اختُبر سابقًا. بعد تحديث الموديول تطابقت كل الصفوف والأعمدة السابقة في{p['protected_tables']}جدولًا محميًا. فُحصHTTP200 والصورة المثبتة ومجلدات المصدر للقراءة فقط وإصدار الموديول وعدم وجود ترقيات معلقة. حُدّث ربط النسخ اليومي إلىWS2.

يمكن الوصول من الموظفون ← التهيئة ← قوالب الدوام، أو ملف الموظف ← كشوف المرتبات ← تحديد جدول الدوام. أعد تحميل الصفحة بعد الترقية لتحميل منتقي الوقت.

الرجوع المتسق يستعيد قاعدة البيانات والمرفقات والمصدر المحفوظة قبل الترقية بعد إيقاف الأصلية. لا تُستعد لقطة قديمة فوق معاملات جديدة؛ عند وجودها يلزم تصحيح مرحلي يحفظها. ملفاcompose وبرنامج النسخ السابقان محفوظان في `.local-backups/work-schedule-time-picker-20260909`.

الأدلة: [فحوص التغيير](ws2-checks.json)، [بيان المرشح](candidate.json)، [النسخة الاحتياطية](main-backup.json)، [سلامة البيانات](main-preservation.json)، [التشغيل](runtime.json)، [قرار النقل](PREDEPLOY-GO.md).
'''
text=re.sub(r'(?<=[\u0600-\u06ff])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[\u0600-\u06ff])', ' ', text)
(out/'HANDOFF.md').write_text(text,encoding='utf8')
header=f'WS2 current MAIN release: `{c["commit"]}` (2026-09-09), frozen `.local-backups/work-schedule-time-picker-20260909/candidate`, 24-hour work schedule picker, module19.0.1.0.1. Evidence: `docs/releases/2026-09-09-work-schedule-time-picker/HANDOFF.md`. Earlier release descriptions below are historical.\n\n'
for rel in ['README.md','docs/architecture/registry/INDEX.md','docs/operations/2026-09-09-environments/README.md']:
    path=root/rel
    path.write_text(header+path.read_text(encoding='utf8'),encoding='utf8')
