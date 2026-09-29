import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
g=root/'docs/build-governance'
previous=json.loads((root/'docs/releases/2026-09-09-simple-work-schedules/candidate.json').read_text())
unchanged={r:hashlib.sha256((root/r).read_bytes()).hexdigest()==h for r,h in previous['files'].items()
    if r.startswith('custom_addons/baseer_work_schedule/models/') or r.startswith('custom_addons/baseer_work_schedule/security/')}
assert all(unchanged.values())
component=json.loads((g/'ws2-component-checks.json').read_text())
result=dict(status='passed',component_checks=component,unchanged_backend_and_acl=unchanged,
    ui_checks=[
    'Arabic desktop: start24hourchoices/end25hourchoices, all60minutes, western24h, no free-texttimeinput.',
    '21:00–03:00 serverpreview06:00(+1), sixdays36:00weekly/6.00daily.',
    '09:07–15:43 serverpreview06:36,39:36weekly/6.60daily; no rounding of minute selection.',
    'End24 forces00minutes, disabledminute; switching to23 restoresminutechoices.',
    'Keyboard ArrowUp changeshour and retainsfocus; finalTabfix movesfromhour to minute within samefield.',
    'English desktoplabels and nativeSave template succeeded; QAcalendar388 shows21:00–03:00(+1),36:00weekly.',
    'English mobile390x844: importedcalendar388 retains time, cardopenspicker, choosing03:15 andSave&Close produces06:15(+1),37:30weekly; parentcancelled.',
    'Arabic mobile: employee3Payroll openswizard thenperiodform with translatedhour/minute;21–03 produces06:00(+1). Child andparentcancelled, noemployeeassignment.',
    'Bothmobilelanguages: document390px/nohorizontaloverflow,selectheight44px; screenshotsinspected. Viewportreset anduserArabicrestored.'
    ],limits=['NativeHTMLselect appearance follows device; values remain literalASCII24h.',
              'No new fullbackendregression/loadsuite: backend/ACL filesexactlyacceptedWS1 with107+21 priorchecks; narrowrealUI/serverpreview/saveverified.',
              'Deferredcomponenttest stubsOwl/registry and record.update, not wholeOdoobrowser; actualkeyboard/selection testedseparately.'],
    qa_mutation='Only temporarytemplate388 WS2 UI time picker; no employee assigned; removed with nativeORM after tests.')
(g/'ws2-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
