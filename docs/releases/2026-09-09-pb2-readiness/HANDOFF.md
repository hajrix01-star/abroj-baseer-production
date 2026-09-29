# PB2 — Employee payroll readiness

**QA applied and verified; MAIN was not updated.** Independent acceptance: [ACCEPTANCE.md](ACCEPTANCE.md).

Version `19.0.1.5.0`, commit `807712c3dd78db4bdbec15d6a264b5b72feec951`, archiveSHA256 `6906f3ea5116d677c65d8649a5cb896d1522d25ce881238d198df5573b37d937`. Overlay [baseer-payroll-pb2.zip](baseer-payroll-pb2.zip) replaces only baseer_payroll in the accepted FA2 source; all other FA2 source files match their baseline. Do not deploy the whole dirty workspace. QA's actual158 installed modules were used for testing.

New employees default to payroll inclusion, with explicit authorized exclusion preserved. Employees with incomplete contract start/salary remain visible in draft with zero effective amounts, a bilingual warning, and approval blocked until setup and refresh. Authorized HR changes invalidate derived draft amounts under employee locks; manual inputs and posted historical records are preserved. Native open-ended contracts remain start date plus empty end date, now with a clear hint. No new HR permissions, dependency, ledger or invented contract dates.

Tests: 228 assertions across 5 suites; details in test-summary.json. Includes HR/Payroll roles, defaults and forged context, eligibility boundaries, repeat refresh, manual deductions, six-month financial regression,50mixed employees and concurrent requests. Browser proof: [UI-REVIEW.md](UI-REVIEW.md), Arabic/English desktop/mobile and default inclusion.

Deployment kept all93 discovered account_* tables exactly equal, all employee records and all salary/contract versions equal. Existing inclusion flags were not bulk enabled. A coherent PostgreSQL+filestore backup is retained under .local-backups/pb2-20260909/deployment/preinstall; backup configuration remains private. apply-result.json and postcheck.json bind QA verification to this source. The isolated clone was removed after acceptance; backup and evidence retained. No test-generated payroll postings were added to QA.

For older draft runs use Refresh Employees. Complete the real start date and salary before approval; missing start never becomes an inferred start. An ended or future contract is not made eligible merely to populate a row. Printable-contract capabilities and the current PDF attachment workflow are documented in [CONTRACTS.md](CONTRACTS.md); no legal template or automatic employment-contract PDF was added.
