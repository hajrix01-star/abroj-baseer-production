# LOCAL-ODOO-CONNECTION-1 — 2026-11-05

## Contract and impact (G0)
Owner request: prepare safe API-key entry for direct Baseer Odoo access, choosing the best route. Preparation is authorized; no existing user permissions, API keys, deployed MCP service, business data or production source may be changed. Existing report identity remains unchanged. The owner's new integration identity supplies its own Odoo key. This slice prepares local connection and read-only diagnostics; specific mutation tools require a separately reviewed owner-approved change. Do not imply this utility implements an approval-backed write executor.

Reference: BASEER-MCP-1, registry INDEX.md; original revision 85524d9ef. Existing service services/baseer_mcp accepts fixed reports only, so extending its production identity is unnecessary for credential entry. Classification: ARCHITECTURAL integration boundary, locally contained.

Acceptance: masked native credential entry; secret never in chat/arguments/logs/Git/plaintext files; DPAPI CurrentUser encrypted key and user-only directory ACL; exact HTTPS origin https://baseer.abroj.sa only; no redirects; finite timeout and response size; connection validation before atomic save; retain prior working credentials if validation fails; sanitized errors; bounded explicitly read-only JSON-2 calls; live access waits for owner input. No arbitrary upstream method, context or impersonation. Odoo remains authoritative for ACL/record/field access, company scope and all financial numbers. No financial calculation or posting in the client.

## Capacity (G1)
One owner on this Windows computer, one local process; no server/listener/background schedule. One request per invocation; timeout 15 seconds, result cap 2 MiB, read page limit 100, offset nonnegative. No stored HR/financial results, no traffic/load testing. Credential store is replaceable by rerunning setup; lost Windows profile requires re-entry. No promise of production availability; prior browser returned 502.

## Architecture (G2)
Owner -> native PowerShell Windows Forms key entry -> exact HTTPS JSON-2 res.users/context_get -> encrypted .private connection file outside the tracked file set. CLI -> decrypt in memory -> fixed read-method allowlist -> Odoo ACLs -> JSON stdout. Never print raw upstream errors or headers. Credentials and config bound together in a DPAPI-encrypted document. Pin baseer.abroj.sa, no redirects, verify normal Windows TLS trust. No writes or arbitrary method switch; scripts never enable elevated Odoo groups. Read-only calls may be used with a broad identity but are client-enforced, not a claim that the API key itself is read-only.

Methods: context (res.users/context_get only), fields_get, search_read, search_count, read. CLI accepts model identifier, fields, domain JSON, IDs and company IDs; validates shapes/limits; constructs only allowed body keys. Reject non-read methods and caller contexts. Model ACLs stay in Odoo. Exclude attachment/binary data and API-key/security/automation models from generic reads; cap responses. Test before sending any key to any URL; URL is a constant, not user-provided.

G2 correction after independent review: the above exclusion approach is superseded by a strict model AND field allowlist: res.company identity fields; hr.employee salary/readiness identity fields; hr.version effective-date/contract/wage fields; hr.payslip/run period, readiness and amount fields. Fields must be explicit, unknown fields rejected. fields_get is also restricted to allowlisted names and metadata attributes. read accepts at most 100 positive IDs. No generic business-model access is enabled. The API key retains the owner's account rights, but this first consumer exposes only payroll diagnostics.

## Stack and direct route (G3)
Windows PowerShell 5.1, built-in .NET Windows Forms, System.Security DPAPI, HttpClient, ACL APIs. No packages, model SDK, browser form, web server, GUI framework or deployment. Native single-dialog setup utility, not an application redesign; G4 web/mobile/catalog not applicable. English labels with Arabic instructions, Western digits. No new numerical logic. Prefer direct API utility to modifying deployed report MCP, installing a third-party Odoo MCP or creating a generic write endpoint.

## Gates
G0–G3: pending independent gatekeeper review before code. G4: native utility only, no web UI. G5: offline credential roundtrip, ACL/validation/redirect/limit/error checks plus parser validation. G6: no new load environment justified for one request and owner input. G7: bounded final diff; G8: independent scoped acceptance, live verification pending owner key.

## Live log
- L01: Read AGENTS.md, existing MCP README/pyproject/read adapter, registry BASEER-MCP-1, and build/security/ERP/capacity references. No app changes or dependencies.
- L02: Created separate branch codex/baseer-api-access-20261105 in a sparse worktree to preserve the dirty main workspace. Sandbox initially denied config.worktree write; approved escalation succeeded. No production connection or user change.
- L03: Selected local encrypted credential bootstrap and bounded read client. Existing production reports and identity remain unchanged. Waiting for independent G0–G3 decision.
- L04: Independent connection_gatekeeper approved G0/G1/G3; requested strict field/model allowlists for G2, now incorporated above. No code yet. No load environment justified: one owner, one bounded API request; existing unit checks cover timeout/limits.
- L05: Independent gatekeeper approved corrected G2; G0–G3 approved for local credential setup and bounded read-only payroll diagnostics. Begin implementation; no new package or Odoo change.
- L06: Offline tests found that current-user-only file ACL blocks the intended Codex restricted token even though DPAPI works. G2 reopened for a scoped ACL adjustment: current Windows user + SYSTEM + existing machine-local CodexSandboxUsers group on this credential directory only. DPAPI remains CurrentUser, so a different Windows user cannot decrypt the key. No global group or permission change. Await independent review; no real secret has been entered.
- L07: Supersedes L06 and the initial custom secret-file design: independent gatekeeper approved Windows Credential Manager instead, with fixed real target, unique TEST targets only, cleared native buffers/CredFree, fail closed and no ACL/MIC changes. Official CredWriteW/CredReadW contracts consulted. G2 approved for this replacement; G3 unchanged (built-in Windows, no dependencies). Removed custom secret-file code. Corrected one-term JSON domain handling and scheduled UTF-8 BOM conversion for Windows PowerShell compatibility. No real key or live call.
- L08: Credential Manager is unavailable inside the tools' restricted Windows token; no sandbox, groups or integrity restrictions were relaxed. Independent gatekeeper approved owner-opened native setup plus a host-launched stdio MCP reader and config template. Only status/identity/bounded payroll reads. MCP primary stdio/lifecycle specification checked. Actual Windows store and host-MCP/Odoo checks await owner action.
- L09: Windows pwsh 7.6.5: Test-Connection.ps1 PASS 30 offline checks (NativeStore=False); Test-Mcp.ps1 PASS protocol framing/lifecycle, three-tool catalog, notifications/status, unsafe tool calls, invalid/oversized frames and sanitized errors. No Odoo requests or real key. Windows PowerShell 5.1 runtime check blocked by restricted execution-policy registry access; primary launcher prefers pwsh. Native storage acceptance remains open.
- L10: Independent alpha-delivery-team scope review by connection_gatekeeper: CONDITIONAL GO for preparation; actual connection, native storage, Odoo permissions and host integration unverified. Identified empty worktree index from --no-checkout; repaired with read-tree HEAD and sparse reapply. Confirmed staged diff empty before staging only exact new bundle/contract paths; unrelated sparse paths excluded from candidate. No deployment or writes to Odoo.
- L11: Source candidate committed as 2cc5080e2 (12 new scoped files, no unrelated deletes). Registered baseer_owner_local with official codex mcp add into local Codex global config; command succeeded and get --json confirmed enabled stdio command/args with no env/secrets. No server with that name existed before. Current conversation tool catalog does not yet include it; host reload/new session is pending. Rollback registration with codex mcp remove baseer_owner_local; no Odoo effect. Updated README accordingly; no implementation change or repeat tests required.

## Current acceptance
Prepared candidate only: CONDITIONAL GO. G0–G3 approved with L07/L08 architecture superseding initial secret-file design; G4 native utility only; G5 offline transport/validation verified, real credential probe pending; G6 no load test justified; G7 scoped source; G8 independent conditional acceptance above. Financial numbers and document states remain entirely authoritative in Odoo; client does not calculate or post. No mutation or approval executor exists in this slice.

Owner completes setup by opening tools/odoo-connection/Open-Connection.cmd in their normal Windows session, entering the API key in the masked field, and selecting Test & save. If database cannot be selected by Host, supply its actual name. Do not put the key in chat, commands or the MCP config. MCP is a local stdio process using the same Windows credential set; its actual host execution must be verified after registration. Existing report identity/MCP stays unchanged.
- L08: Credential Manager is unavailable inside the tools' restricted Windows token; did not relax any sandbox or permissions. Independent gatekeeper approved owner-opened native setup plus a host-launched stdio MCP reader. Added only status/identity/bounded payroll-read tools and config template; no global config modification. MCP stdio/lifecycle primary specification checked. Actual Windows user-store and host-MCP/Odoo acceptance await owner input; offline protocol checks must not claim native-store success.

## PAYROLL-ADVANCE-READ-1 — تفصيل سلف وأقساط أودو/نوركس (2026-11-06)

### عقد البناء — G0 (مصحح بعد مراجعة مستقلة؛ بانتظار الاعتماد)

- **الهدف:** تمكين مطابقة قراءة فقط لسلف الموظفين وأقساطها عند **نهاية يوم تاريخ قطع شامل** (أول استعمال: 2026-10-31)، من دون تعديل أودو أو نوركس أو إنشاء قيد أو صرف أو خصم راتب. لا يجوز تسمية رصيد حالي بأنه رصيد تاريخي.
- **المستخدم والتفويض:** مالك النظام فقط، عبر موصل Codex المحلي الموجود وحساب نوركس المقيد للقراءة. يصرح طلب المالك السابق بـ«أنشئ حساب» ثم «اجعله فقط قراءة وليس تعديل» بإنشاء **هوية أودو تقنية جديدة** ومفتاح API لها وبمنحها مجموعة قراءة اللقطة فقط عند النشر؛ لا يستعمل مفتاح المالك ولا تتغير أدوار المستخدمين القائمين. كلمة المرور/المفتاح لا يدخلان Git أو المحادثة، ويُدخلان محليًا في Windows Credential Manager.
- **النطاق في أودو:** أداة MCP مسماة منفصلة فقط (`baseer_advance_snapshot_read`) تتلقى مفتاح شركة ثابتًا وتاريخ قطع وموظفًا اختياريًا؛ ولا تفتح `search_read` عامًا لأي نموذج سلف. تعيد حدث السلفة (الموظف/الشركة/المبلغ/تاريخ الصرف)، وجدول الأقساط (التسلسل/المبلغ/الاستحقاق الأصلي)، وحدث الاسترداد (المبلغ/التاريخ/النوع) حتى تاريخ القطع. حساب الرصيد التاريخي يتم في طبقة خادم أودو موثوقة، ويصنف السجل غير القابل للإثبات عند وجود عكس أو تصحيح غير مؤرخ قبل الإرجاع. لا تُكشف دفاتر أو حسابات أو خزائن أو قيود أو مرفقات أو مستخدمو التأجيل أو أسبابها.
- **النطاق في نوركس:** استعمال `/api/v1/hr/advances` فقط مع `x-company-id` ثابت ومصادقة JWT لحساب قراءة وخطوة تحقق لـ`/api/v1/auth/me`؛ يثبت معنى الرصيد/التاريخ واختيار السنة من استجابة فعلية قبل إدخاله في المطابقة. لا نسخ بيانات الأعمال ولا إعادة حساب الرصيد في العميل.
- **خارج النطاق:** أي `create` أو `write` أو `unlink` أو اعتماد أو صرف أو جدولة قسط أو ترحيل رصيد افتتاحي؛ فتح صلاحية ORM عامة؛ تغيير صلاحيات أودو أو بياناتها؛ أي API key أو كلمة مرور أو رمز في Git أو السجل.
- **مصدر الحقيقة والرقابة:** نوركس هو دليل السلف التاريخية حتى تاريخ القطع، وأودو هو دليل ما سجل لديه. يعرض خادم أودو لقطة قابلة للتدقيق بتاريخ القطع؛ ولا يحسب العميل أو يقرب أو يرحل أرقامًا. لا تتحول نتيجة المطابقة إلى إجراء تعديل؛ النقل يحتاج عقد ترحيل منفصل وموافقة المالك.
- **معايير القبول:** (1) لا يظهر في سطح MCP إلا الأداة المحددة، (2) يرفض أي حقل أو موديل أو method أو سياق أو شركة غير مصرح، (3) يرفض كل مسار كتابة، (4) تتحقق ACL وقاعدة سجل أودو لحساب تقني مقيد فعليًا، (5) لا تظهر أسرار أو أجسام أخطاء upstream، (6) تثبت الاختبارات أن حدث سلفة/قسط/استرداد وعكس بعد تاريخ القطع لا يغير لقطة القطع، (7) تجربة الحساب المقيد تثبت عدم إمكانية الكتابة.

### ملف السعة والنمو — G1 (مسودة)

- مستخدم واحد وجلسة واحدة؛ رحلة حرجة واحدة: قراءة لقطة سلف لشركة مسماة عند تاريخ قطع، بحد 100 سجل و2 MiB و15 ثانية كما في الموصل القائم. يعيد الخادم `snapshot_token` قصير العمر مع cursor؛ أي صفحة تالية لا تقبل إلا بالرمز نفسه كي تنتمي إلى لقطة واحدة. لا يسجل الرمز أسماء أو مبالغ ولا يُعاد استخدامه كرمز دخول.
- النمو المتوقع عشرات إلى مئات السلف والأقساط لكل شركة؛ القراءة مرقمة ولا تحمل المرفقات أو القيود أو تاريخ كل الشركات بلا حد.
- لا توجد كتابة أو عملية قابلة للتكرار في هذه الشريحة. الرصد يبقى منقحًا: نجاح/فشل ومدة فقط، بلا رواتب أو مفاتيح أو أسماء موظفين في السجل.

### المعمارية والعقود — G2 (مسودة)

```text
Codex -> MCP محلي مقيد (قراءة فقط) -> Odoo snapshot endpoint / Noorix HR API
      -> لقطة خادمية وحدث سلف/أقساط/استردادات محدودة
      -> تقرير مطابقة لاحق منفصل، بلا كتابة
```

- Odoo: حساب تقني جديد مقيد للقراءة فقط ومجموعة/قواعد سجل دقيقة للسلفة المطلوبة؛ لا يستعمل مفتاح المالك. مسار HTTPS ثابت `POST /baseer/api/v1/payroll/advance-snapshot` (`auth='user'`، بلا `sudo` أو bypass للقواعد) يقبل schema ثابتًا فقط: `{company_key, cutoff, employee_id?, cursor?, snapshot_token?}`. يحتفظ الخادم بخريطة `company_key → res.company` في إعداد موديول محمي، ويتحقق أن الموظف الاختياري تابع للشركة قبل قراءة أي صف. يرد بـ`{snapshot_token, next_cursor?, rows[]}`؛ ويضم كل مبلغ `amount` مع `currency`، وتضم كل سلفة/قسط/استرداد `proof_status` و`proof_reason?`.
- **دلالة اللقطة:** تشمل حركة صرف أو استرداد مرحّلة بتاريخ فعلي `<= cutoff` حتى 23:59:59 في منطقة الشركة. لا يستعمل المسار `balance` أو `paid_amount` المحسوبين اليوم. الحركة المدخلة بعد إنشاء اللقطة بتاريخ سابق، أو عكس لا يملك تاريخًا مثبتًا، أو أي اختلاف يمنع إثباتها، يعاد كـ`proof_status='unverified'` ولا يدخل إجمالي المطابقة تلقائيًا. لا يخفي ذلك الخطأ ولا يحوله إلى صفر.
- Noorix: يستعمل حساب القراءة الحالي ولا يقبل عنوانًا أو context أو endpoint حرًا من النموذج. المصادقة `POST /api/v1/auth/login` ثم Bearer JWT، مع عدم تخزين النتيجة خارج Windows Credential Manager. عقده يحتاج تحققًا فعليًا من response/pagination/معنى الرصيد قبل اعتباره جاهزًا.
- لا تُقرأ `account.move` أو `account.move.line` أو `account.journal` أو الرسائل/المرفقات؛ لذلك لا يستنتج الموصل حركة نقدية أو قيدًا محاسبيًا.
- التراجع: حذف النماذج والحقول الجديدة من allowlist وإعادة تسجيل موصل Codex إن لزم؛ لا توجد ترحيلات أو بيانات أعمال لتراجعها.

### التقنية والمسار المباشر — G3 (مسودة)

- إعادة استخدام PowerShell/.NET وMCP stdio الحاليين وواجهات Noorix HR الموجودة، مع إضافة مسار لقطة خادمي صغير في موديول الرواتب وقواعد وصول صريحة؛ لا مكتبة أو قاعدة بيانات أو واجهة جديدة.
- البديل المرفوض: كشف ORM عام أو إنشاء أداة تنفيذ/ترحيل؛ لأنه يمنح صلاحية مالية أعلى من الحاجة إلى المطابقة، كما أن عرض `balance`/`paid_amount` الحاليين لا يثبت لقطة تاريخية.
- **سؤال المسار المباشر:** نعم؛ مسار لقطة خادمية مقيد هو الأقل مخاطرة من نقل قيود أو كشف ثلاثة موديلات مالية للبحث الحر.

### سجل البوابات — PAYROLL-ADVANCE-READ-1

| البوابة | الحالة | المالك | المراجع المستقل | دليل الدخول/الخروج |
|---|---|---|---|---|
| G0 | أعيد فتحها | قائد البناء/خبير ERP | حارس البوابات | تعريف تاريخ القطع ومعالجة العكس أعلاه |
| G1 | مشروط | مهندس السعة | كبير المعماريين | حدود الموصل + ترقيم خادمي ثابت |
| G2 | أعيد فتحها | كبير المعماريين/ERP | حارس الجودة | حساب تقني مقيد + endpoint لقطة ثابت |
| G3 | أعيد فتحها | أمين المكتبات | كبير المعماريين | مسار Odoo صغير بلا اعتماد جديد |
| G4 | غير منطبق | — | حارس الجودة | لا واجهة جديدة |
| G5–G8 | غير مبدوءة | — | — | بعد إقفال G0–G3 فقط |

### دفتر العمليات الحي — PAYROLL-ADVANCE-READ-1

| المعرّف/الوقت | البوابة | النوع | النية/الأمر | النتيجة والدليل | الأثر والتراجع | المنفذ/المراجع |
|---|---|---|---|---|---|---|
| PA-01 / 2026-11-06 | قبل G0 | قراءة | جرد سلف نوركس وأودو يدويًا حتى 31 أكتوبر بناء على طلب المالك | كشفنا أن موصل أودو لا يتيح حقول السلف الحالية، وأن الواجهة تعرض بيانات تفصيلية؛ لم يُعدل سجل | قراءة فقط؛ لا بيانات أو صلاحيات تغيرت | قائد البناء / — |
| PA-02 / 2026-11-06 | G0–G3 | توثيق | فتح عقد تقييد قراءة السلف والأقساط قبل أي تغيير | هذا القسم؛ نطاقه لا يسمح بالكتابة أو ترحيل الأرصدة | تغيير وثائقي قابل للعكس عبر Git | أمين السجل / بانتظار حارس البوابات |
| PA-03 / 2026-11-06 | مراجعة مستقلة | قرار بوابة | فحص تعريف تاريخ القطع وحقول السلف المقترحة | NO-GO: الأرصدة المحسوبة الحالية لا تثبت رصيد 31 أكتوبر، وحساب المدير يملك CRUD كاملًا؛ يلزم لقطة خادمية وحساب تقني مقيد | لا كود أو بيانات أو صلاحيات تغيرت | حارس البوابات / قائد البناء |
| PA-04 / 2026-11-06 | G0–G3 | توثيق | استبدال كشف ORM العام بعقد لقطة تاريخية وحساب تقني مقيد | العقد المصحح أعلاه؛ بانتظار مراجعة مستقلة ثانية قبل الكود | تغيير وثائقي قابل للعكس عبر Git | قائد البناء / بانتظار حارس البوابات |
| PA-05 / 2026-11-06 | مراجعة مستقلة | قرار بوابة | فحص عقد اللقطة المصحح | NO-GO مؤقت: تثبيت تفويض هوية القراءة، schema endpoint، خريطة الشركة، دلالة الإثبات، وتحقق نوركس الفعلي | لا كود أو بيانات أو صلاحيات تغيرت | حارس البوابات / قائد البناء |
| PA-06 / 2026-11-06 | G0–G3 | توثيق | تثبيت تفويض الحساب الفني وعقد endpoint/اللقطة/cursor | العقد أعلاه؛ نوركس يبقى خارج الاعتماد حتى اختبار response للحساب المقيد | تغيير وثائقي قابل للعكس عبر Git | قائد البناء / بانتظار حارس البوابات |
