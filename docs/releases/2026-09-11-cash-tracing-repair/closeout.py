"""Record verified publication and update the local release index."""
import json
import subprocess
from pathlib import Path
import main_release as release

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
REPO = ROOT / '.local-backups/live1-20260909/repository'
PUBLIC = '7a79650118965b63bb2509271a25d92a4ad61a62'

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

candidate = release.verify_candidate()
assert run('git', '-C', str(REPO), 'rev-parse', 'HEAD') == PUBLIC
assert not run('git', '-C', str(REPO), 'status', '--porcelain')
assert run('git', '-C', str(REPO), 'ls-remote', 'origin', 'refs/heads/main').split()[0] == PUBLIC
lock = read(REPO / 'release-source.json')
assert lock['source_commit'] == candidate['commit'] and lock['files'] == candidate['files']
for relative, expected in candidate['files'].items():
    assert release.b.sha(REPO / relative) == expected
ci = json.loads(run('gh', 'run', 'view', '34534151549', '--repo', 'hajrix01-star/Odoo-Baseer', '--json', 'databaseId,headSha,status,conclusion,url,jobs'))
assert ci['headSha'] == PUBLIC and ci['status'] == 'completed' and ci['conclusion'] == 'success'
preservation = read(OUT / 'main-preservation.json')
smoke = read(OUT / 'main-smoke.json')
runtime = read(OUT / 'runtime.json')
assert all(preservation[k] for k in ('all_business_exact', 'security_exact', 'schema_exact', 'module_versions_exact'))
assert smoke['status'] == 'PASS' and len(smoke['checks']) == 39 and smoke['read_only']
assert runtime['candidate'] == candidate['commit'] and runtime['http'] == 200
release.b.save(OUT / 'github.json', {'status': 'PASS', 'commit': PUBLIC, 'source_commit': candidate['commit'], 'remote_main_exact': True, 'clean_checkout': True, 'source_files_verified': len(candidate['files']), 'source_inventory_exact': True, 'ci': ci})

handoff = '''# تطبيق إصلاح تقارير النقد والتحصيل على الأصلية

نُشر المرشح `0e2a0853d858ffc8760d009a34cf17dda68dde45` على MAIN بتاريخ 2026-09-11 بتفويض المستخدم «طبقة». الأصلية: http://127.0.0.1:18069 / `baseer_dev`، والتجريبية: http://127.0.0.1:18075 / `baseer_ic1_20260910`. تعملان بالمصدر المالي نفسه: SHA256 `1824578524e00788c8e35f7f23af0567e8252f93ac2bc583017e6502ddc79bfd`.

التغيير ستة ملفات من1183: نماذج وmanifests للموديولات `baseer_cash_categories19.0.1.3.2` و`baseer_pos_summary19.0.1.5.2` و`baseer_financial_register19.0.1.2.1`. يصلح تتبع الرواتب والسلف، وإثبات تحصيل واسترداد مبيعات POS الأصلية، والتحذير الخاطئ للتطبيقات ذات الصافي الصفري. لا تعديل جديد في المنتج أثناء الترقية؛ نفس الإصلاح المقبول في QA.

أُعيد استخدام [مقارنة QA المالية](../../audits/2026-09-10-90day-simulation/repair/COMPARISON.md) و[مراجعة واجهتها العربية](../../audits/2026-09-10-90day-simulation/repair/UI-REVIEW.md):969 فحصاً مستقلاً فريداً و26 فحص تشغيل QA، بأدلة المصدر المرتبطة في candidate.json. بيانات الاختبار لـ90 يوماً بقيت كما هي، ولم تُنقل إلى الأصلية. انخفض خطأ التصنيف والتحصيل دون تغيير القيود والأرصدة الأصلية.

سبق النشر تحديث نسخة مستعادة من MAIN وفحص39 حالة عليها، ثم إيقاف MAIN ونسخ قاعدة البيانات والمرفقات والمصدر والإعدادات باتساق. تحقق checksum لجميع664 مرجع مرفق وبصمات ملفات النسخة. النسخة الاحتياطية النهائية لها تحقق pg_dump/TOC وملفات؛ لم نُجر استعادة ثانية مستقلة لها، والاستعادة والترقية التجريبيتان موثقتان في clone-backup.json. مكان النسخة محفوظ محلياً في main-backup.json.

نجحت الترقية الفعلية للموديولات الثلاثة من المصدر المجمد للقراءة فقط وبصورة Odoo المثبتة. **405 جداول محمية: بيانات الأعمال ومعاني الصلاحيات والعلاقات وschema محفوظة**، و400 جدول متطابق بكل بايتات الصفوف. الاستثناء نفسه في clone وMAIN:88 سجل metadata فقط،50 قاعدة و32 ACL و3 مجموعات وشريكان وprivilege واحد. تغير write_date، وwrite_uid للشريكين181 و183 إلى1. لا تغيير مالي أو صلاحيات فعلية. التفاصيل في main-preservation.json وPREDEPLOY-GO.md.

نجحت39 حالة على MAIN الفعلية: استيراد المصدر وإصداراته، ومطابقة بطاقات All/Inout للصفوف وصافي النقد للدفتر، لثلاث شركات. التنفيذ بالمستخدم الأصلي2، `su=False`، READ ONLY وrollback. HTTP200، لا موديولات معلقة، والمصدر والمنافذ والمجلدات المثبتة صحيحة. لم تُكرر رحلة متصفح MAIN؛ قبول الواجهة هو فحص QA السابق، ولا تغيير واجهة في هذا الإصلاح. الدليل main-smoke.json وruntime.json.

GitHub main: [7a79650118965b63bb2509271a25d92a4ad61a62](https://github.com/hajrix01-star/Odoo-Baseer/commit/7a79650118965b63bb2509271a25d92a4ad61a62). جميع1183 ملف مصدر تطابق المرشح، وremote HEAD متطابق والcheckout نظيف. ثمانية ملفات منشورة فقط: الستة المعدلة وREADME وrelease-source.json؛ لا بيانات أو مرفقات أو أسرار أو تقارير داخلية. [CI34534151549](https://github.com/hajrix01-star/Odoo-Baseer/actions/runs/34534151549) نجح في بصمات المصدر وPython/XML syntax؛ الاختبارات المالية موثقة محلياً وليست ادعاء لاختبارات CI. الدليل github.json.

مرجع التشغيل الحالي في compose.yaml وcompose.main-release.yaml وenvironment_backups.py يشير إلى `.local-backups/cash-tracing-repair-20260911/candidate`. المصدر السابق وcompose والإعدادات السابقة محفوظة؛ أي تراجع يكون بإيقاف MAIN واستعادة المجموعة المتسقة كاملة وفق مسار المشروع، وليس بخفض إصدار الموديول فوق قاعدة محدثة. قفل الصيانة أُزيل بعد نجاح التشغيل. تفاصيل المراجعة المستقلة النهائية في FINAL-REVIEW.md.

حدود القبول: المصادر الغامضة تبقى غير مصنفة، ولا شهادة عامة لكل حالات split receipts أو العملات الأجنبية أو السعة. هذه الحدود لم تتغير بالنشر.
'''
(OUT / 'HANDOFF.md').write_text(handoff, encoding='utf8')
index = ROOT / 'docs/architecture/registry/INDEX.md'
content = index.read_text(encoding='utf8')
entry = 'Cash tracing repair current MAIN/GitHub (2026-09-11): `0e2a0853d858ffc8760d009a34cf17dda68dde45`, accepted QA SHA1824578524e00788c8e35f7f23af0567e8252f93ac2bc583017e6502ddc79bfd. 1183 source files/6 changes; cash19.0.1.3.2, POS19.0.1.5.2, register19.0.1.2.1. MAIN18069 upgraded with original data retained; QA18075 retains the 90-day dataset. Independent QA969 unique checks and26 runtime checks reused; MAIN clone39 and actual MAIN39 read-only checks PASS.405 protected tables preserve business/security/schema;400 raw exact,88 precisely allowed metadata-only rows. Coherent pre-upgrade backup and664 attachment refs verified. GitHub `7a79650118965b63bb2509271a25d92a4ad61a62`, CI34534151549 success. [Handoff](../../releases/2026-09-11-cash-tracing-repair/HANDOFF.md). Previous release entries below are historical.\n\n'
if not content.startswith('Cash tracing repair current MAIN/GitHub'):
    content = content.replace('MAIN and GitHub unchanged. [Before/after', 'MAIN and GitHub were unchanged at QA acceptance; promotion is recorded above. [Before/after', 1)
    content = content.replace('MAIN release below remains current.', 'The MAIN release below was current at baseline acceptance.', 1)
    content = content.replace('FL3/FL3B current MAIN release', 'FL3/FL3B previous MAIN release', 1)
    index.write_text(entry + content, encoding='utf8')
print('CLOSEOUT_PASS', PUBLIC, ci['conclusion'])
