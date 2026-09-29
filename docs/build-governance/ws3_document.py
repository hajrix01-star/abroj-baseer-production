import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=root/'docs/releases/2026-09-09-duration-display'
c=json.loads((out/'candidate.json').read_text())
p=json.loads((out/'main-preservation.json').read_text())
b=json.loads((out/'main-backup.json').read_text())
(out/'HANDOFF.md').write_text(f'''# WS3 — توحيد عرض مدد الدوام

نُشر الإصدار `baseer_work_schedule 19.0.1.0.2` على الأصلية `baseer_dev` بتاريخ 2026-09-09. المصدر المجمد `{c['commit']}` في `.local-backups/duration-display-20260909/candidate`.

يعرض المتوسط اليومي الآن **10:30** بدل **10.50**، في شاشة إدخال الدوام والقالب المحفوظ وقائمة القوالب. العنوان «متوسط الدوام اليومي — ساعات:دقائق». يستعمل النموذج والقالب متوسط الدقائق الأصلية نفسه، مع التقريب إلى أقرب دقيقة والنصف إلى الأعلى عند اختلاف الأيام. تبقى قيمة أودو العددية المستخدمة في الرواتب والحضور والإجازات كما هي؛ الحقل الجديد للعرض فقط وغير مخزن.

نجح 16 فحصًا محدودًا مع rollback في QA، تشمل مثال المستخدم بفترتين، عبور الليل، اختلاف أيام الدوام، التقريب، حد الساعة، حالة فارغة، وتطابق العرض مع بقاء القيمة المالية10.5 أو10.51. تحقق المتصفح العربي فعليًا من10:30 و63:00 والعنوان الجديد. لم تُكرر فحوص WS2 الشاملة للجوال والمنتقي؛ مكوناتهما لم تتغير.

أُخذت نسخة متسقة قبل النقل في `{b['directory']}` مع فحص {b['attachment_references_verified']} مرجع مرفق. تطابقت جميع الصفوف والأعمدة السابقة في {p['protected_tables']} جدولًا محميًا بعد ترقية الموديول. حُدّث ربط المصدر وبرنامج النسخ اليومي إلى WS3. لم تُعد تجربة الاستعادة لهذه اللقطة؛ مسار الاستعادة اختُبر سابقًا.

لرؤية التعديل، حدّث صفحة الموظف أو القالب. لا يلزم إعادة حفظ جدول قائم.

الرجوع المتسق يستعيد القاعدة والمرفقات والمصدر من النسخة السابقة بعد إيقاف الأصلية، مع ملفات compose المحفوظة في `.local-backups/duration-display-20260909`. لا تُستعد لقطة قديمة فوق معاملات لاحقة؛ عند وجودها يلزم تصحيح يحفظها.

الأدلة: [الفحوص](ws3-checks.json)، [الواجهة](ws3-ui.json)، [المرشح](candidate.json)، [قرار النقل](PREDEPLOY-GO.md)، [النسخة الاحتياطية](main-backup.json)، [سلامة البيانات](main-preservation.json)، [التشغيل](runtime.json).
''',encoding='utf8')
header=f'WS3 current MAIN release: `{c["commit"]}` (2026-09-09), frozen `.local-backups/duration-display-20260909/candidate`, HH:MM schedule averages, module19.0.1.0.2. Current evidence: `docs/releases/2026-09-09-duration-display/HANDOFF.md`. Earlier releases below are historical.\n\n'
for rel in ['README.md','docs/architecture/registry/INDEX.md','docs/operations/2026-09-09-environments/README.md']:
    path=root/rel
    path.write_text(header+path.read_text(encoding='utf8'),encoding='utf8')
