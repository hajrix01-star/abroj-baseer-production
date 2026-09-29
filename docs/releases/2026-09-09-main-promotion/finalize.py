"""Write the factual MP3 handoff only after successful live verification."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import mp3_ops as m
c=json.loads((m.OUT/'candidate.json').read_text())
applied=json.loads((m.OUT/'main-applied.json').read_text());assert applied['success']
runtime=json.loads((m.OUT/'runtime-final.json').read_text());assert runtime['qa_business_unchanged']
result=json.loads((m.OUT/'acceptance-baseer_dev.json').read_text());assert result['status']=='passed'
assert json.loads((m.OUT/'cleanup.json').read_text())['main_and_qa_retained']
before={r['name']:r['latest_version'] for r in json.loads((m.OUT/'baseer_dev-modules.json').read_text())}
after={r['name']:r['latest_version'] for r in json.loads((m.OUT/'main-modules-final.json').read_text())}
new={k:v for k,v in after.items() if k not in before};updated={k:{'before':before[k],'after':v} for k,v in after.items() if k in before and before[k]!=v}
rehearsal=json.loads((m.OUT/'acceptance-baseer_main_rehearsal_20260909.json').read_text());assert rehearsal['status']=='passed'
preservation=json.loads((m.OUT/'preservation-baseer_dev.json').read_text());assert preservation['passed']
added=json.loads((m.OUT/'main-diff.json').read_text())['added_rows']
payment_fills=sum('payment_account_id' in row['columns'] for row in preservation['reviewed_original_changes'] if row['table']=='account_payment_method_line')
previous=json.loads((m.OUT/'previous-source.json').read_text())
main_checks=len(result['checks']);rehearsal_checks=len(rehearsal['checks'])
m.save('module-changes.json',{'installed':new,'upgraded':updated,'removed':list(before.keys()-after.keys()),'before_count':len(before),'after_count':len(after)})
lines=['| الإضافة | السابق | المثبت |','|---|---|---|']
for name,version in new.items():lines.append(f'| {name} | غير مثبتة | {version} |')
for name,versions in updated.items():lines.append(f'| {name} | {versions["before"]} | {versions["after"]} |')
text=f'''# التعديلات المعتمدة على الأصلية — MP3

**نُقلت التعديلات المعتمدة إلى قاعدة `baseer_dev` بنجاح** في {applied['utc']} (UTC). الأصلية متاحة عبر [أودو على 18069](http://127.0.0.1:18069/odoo). بقيت التجريبية على المنفذ 18070 مستقلة، ولم تُنسخ بياناتها إلى الأصلية.

المصدر المعتمد هو `{c['commit']}`، ويضم FA2 وPB2 مع إصدار الرواتب `{after['baseer_payroll']}`، بإجمالي {len(c['files'])} ملفًا. المحرك المثبت: `{m.IMAGE}`. [أرشيف المصدر](candidate-source.zip) وبصمته `{c['archive_sha256']}` محفوظان مع الأدلة. يحدد [القبول المستقل](ACCEPTANCE.md) و[خطة النقل](PLAN.md) نطاق التسليم؛ لم تتضمن المهمة رفعًا إلى GitHub أو نشرًا خارجيًا.

## ما طُبق

ثُبتت {len(new)} إضافات جديدة، ورُقيت {len(updated)} إضافات؛ أصبح العدد المثبت {len(after)} بدلًا من {len(before)}. تشمل الحزمة الرواتب والسلف ونهاية الخدمة وخدمات الموظفين، وبيانات تهيئة الحسابات والموردين، وتحديثات المشتريات والملخصات التي اجتازت المراجعة السابقة.

{chr(10).join(lines)}

## التحقق والحفظ

نجح {rehearsal_checks} فحصًا على نسخة مستقلة من الأصلية، ثم {main_checks} فحصًا على الأصلية، داخل معاملة PostgreSQL للقراءة فقط انتهت بالتراجع (rollback). تضاف هذه النتائج إلى أدلة FA2 و228 اختبارًا سابقًا لـPB2. شملت الفحوص النماذج العربية والإنجليزية وتهيئة المحاسبة والرواتب والخدمات في {len(result['companies'])} شركات. وفُحص {result['attachments']['filestore_rows']} مرجع مرفق و{result['attachments']['unique_files_read']} ملفًا مميزًا؛ لم يظهر ملف مفقود أو اختلاف في SHA1 أو الحجم. التفاصيل في [الفحص الحي](acceptance-baseer_dev.json).

قبل التحديث، أُخذت نسخة متماسكة من الأصلية باسم `cutover`، واستُعيدت فعليًا مع المرفقات في قاعدة منفصلة، مع مطابقة الصفوف والبصمات. وبعد التحديث أُخذت نسخة إنجاز متماسكة قبل إعادة الفتح. أعاد فحص HTTP الحالة 200 للأصلية والتجريبية، ولم تبقَ عمليات تثبيت معلقة. أكد [فحص التشغيل](runtime-final.json) المحرك وفلتر `baseer_dev` وربط المصدر المجمد للقراءة فقط؛ ويحفظ `compose.yaml` هذا الإعداد للتشغيل لاحقًا.

حُفظت قيم الأعمال الأصلية ضمن [مطابقة الحفظ](preservation-baseer_dev.json). اقتصرت الاستثناءات المعتمدة على تعبئة {payment_fills} حقول حساب دفع كانت فارغة، باستخدام حساب اليومية الموجود أصلًا، وبيانات التعديل الوصفية المحددة في التقرير؛ ولم تنشأ عنها معاملات مالية. أُضيفت بيانات التهيئة المجربة: {added.get('account_account',0)} حسابًا، و{added.get('account_journal',0)} يوميات، و{added.get('account_payment_method_line',0)} طرق دفع، و{added.get('baseer_purchase_category_map',0)} ربط تصنيف مع {added.get('product_product',0)} منتجًا، و{added.get('product_category',0)} تصنيفًا، و{added.get('res_partner',0)} موردًا مشتركًا. انحصرت الصلاحيات الجديدة في حسابي root وadmin للرواتب عبر تثبيت OdooMates الأصلي، دون إضافة وصول إلى شركات. انظر [الفروق الفعلية](main-diff.json).

لم يكن حقل الإدراج في رواتب بصير موجودًا لدى الموظف الأصلي رقم 1 قبل التثبيت. أُنشئ الحقل بالقيمة الافتراضية `True` عند التثبيت الأول؛ ولم تُستبدل قيمة `False` محفوظة سابقًا. لا ينشئ هذا الإعداد راتبًا أو اعتمادًا تلقائيًا: إذا نقص تاريخ العقد، يظهر الموظف معلقًا بلا أجر محتسب حتى استكمال البيانات وتحديث المسير. لم تُنشأ فواتير أو مسيرات أو ملخصات تجريبية على الأصلية. وكانت المعاملات المالية صفرًا عند النقل، لذا لا تمثل هذه التجربة وحدها دليلًا على ترقية تاريخ مالي غير فارغ.

## النسخ والتشغيل والرجوع

المجلد الخاص `.local-backups/main-promotion-20260909/` مستبعد من Git، ويضم:

- `cutover/`: قاعدة البيانات والمرفقات وإعدادات التشغيل عند نقطة الرجوع الحديثة. استُعيدت هذه النسخة واختُبرت؛ انظر [البصمات](cutover-backup.json) و[نتيجة الاستعادة](cutover-restore.json).
- `completed/`: نسخة الإنجاز من قاعدة البيانات والمرفقات وإعداد Compose المثبت. تحققت [بصماتها](completed-backup.json)، ولم تُختبر استعادتها مجددًا.
- `previous-source/`: {len(previous['files'])} ملفًا من الإصدار السابق للرجوع. أما `candidate/` فهو المصدر الذي تعتمد عليه الأصلية حاليًا، ويجب الاحتفاظ به.

التشغيل المعتاد من جذر المشروع: `docker compose -p baseer_odoo_dev -f compose.yaml up -d --no-deps odoo`. إعداد التجريبية في ملف منفصل. تعتمد الأصلية على المصدر المجمد، ولا تقرأ مجلد التطوير الجاري.

للرجوع قبل تسجيل عمليات جديدة: أوقف الأصلية وكل الكتابات، واستعد نسخة `cutover` ومرفقاتها في قاعدة ومجلد مستقلين. اختبرهما باستخدام `previous-source` والمحرك المثبت، ثم اضبط التشغيل على القاعدة المستعادة والمصدر السابق. تجنب استعادة جداول منفردة أو نسخ التجريبية أو إزالة الإضافات عشوائيًا. إذا سُجلت عمليات جديدة، فيجب حفظها ووضع خطة تصحيح أو استعادة تشملها قبل الرجوع؛ لا تستبدلها بلقطة قديمة. تبقى الإعدادات الخاصة والأسرار محليًا.

بعد اكتمال فحص التشغيل، أُزيلت قواعد التجربتين ومرفقاتهما فقط. بقيت الأصلية والتجريبية والنسخ الاحتياطية والأدلة محفوظة. النسخ موجودة على الجهاز؛ ولم تشمل المهمة نسخًا خارجية أو جدولة نسخ دورية.
'''
(m.OUT/'HANDOFF.md').write_text(text,encoding='utf8')
readme=m.ROOT/'README.md';body=readme.read_text(encoding='utf8');body=body.split('## نقطة التثبيت الحالية')[0]+'''## نقطة التثبيت الحالية

نُقلت التعديلات المعتمدة FA2 وPB2 إلى الأصلية بتاريخ 2026-09-09، بعد تجربة استعادة وترقية مستقلة ونسخة احتياطية حديثة ومراجعة قبول. التفاصيل والإصدارات والفحوص والرجوع في [توثيق MP3](docs/releases/2026-09-09-main-promotion/HANDOFF.md).

الأصلية `baseer_dev` على [18069](http://127.0.0.1:18069/odoo)، والتجريبية على 18070. يربط `compose.yaml` الأصلية بالمصدر المجمد في `.local-backups/main-promotion-20260909/candidate` للقراءة فقط. يبقى `custom_addons` مصدر التطوير للتجريبية؛ لا تحذف مجلد المرشح الذي تعتمد عليه الأصلية.
''';readme.write_text(body,encoding='utf8')
m.save('evidence-index.json',{'commit':c['commit'],'files':{f.relative_to(m.OUT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in m.OUT.rglob('*') if f.is_file() and f.name!='evidence-index.json' and '__pycache__' not in f.parts}})
print('Documented',len(new),'new',len(updated),'upgraded modules; MAIN',len(after),'verified',main_checks)
