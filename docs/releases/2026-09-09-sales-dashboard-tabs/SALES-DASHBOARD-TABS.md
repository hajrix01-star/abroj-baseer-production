# SD3 — Tabbed shift/payment cards and category footer

2026-09-09 user explicitly requests the changes after viewing SD2. SD2 delivered973395f87b62c8d09f1e6fdc301a7d89e2988d56; module19.0.1.1.0; original MAIN healthy. This is a narrow additive presentation/category-reporting delta; preserve accepted nativefilters/periods/financialsource/security.

G0: Remove permanent explanatory paragraphs (dailyaveragebasis, full-day splitting note, paymentallocationvssettlement note, general timeline marker legend paragraph). Preserve concise status/error/conditionalmissingcoverage warnings and honest empty illustrative label. Shift performance and Payment-method sales are two adjacent desktop cards (stack mobile). Each uses native-style tabs Chart(default) and Details, with only chosen content visible. The shift metricselector stays within Chart. Remove categorycolumn from paymentdetailtable. Add a compact footer at reportbottom: Sales by category, with backendformatted category totals. No new chart or separate categorytable requested.

G1: No new database query/source/materialized table, dependency or larger period. Derive categorytotals from already validatedpayment methodbuckets on backend; same100year/100000sourcebound. Empty/missingcoverage rules identical; totals reflect coveredallocations and conditionalwarning retained whenpartial. Existing75/34 evidence reused for unchangedpaths; focusednewcategoryarithmetic and tab/lifecycle/browser checks only.

G2: categoryid/kind/name from authoritative methodcategory, groupexactDecimal sales of existing validatedmethodbuckets. Sumcategorysales equalscovered_sales; no arbitrarydistribution foruncovered. Footer includes categoryname andserverformattedSARamount. Remove categorycolumn onlyfromvisiblemethoddetails, keepfieldinpayloadforsemanticgrouping. No changes to sources, totalKPIs, approvals/accounting orcompanies.

G3: same featurelocal Owl/XML/SCSS andChart.js/nativebuttons, native navtabs AR/EN/Westerndigits, no newlibrary. Renderhidden-chartcontentconditionally; destroy/recreate Chartinstances appropriately and retainperiodchangegenerationguards. Table/chart replaceeachother within eachcard. Two equal minmax0columns desktop; onecolumn mobile. Accessible tabs/tabpanels with explicitlabels/selectedstate and focusstyle; no duplicatedbusinessarithmetic.

Owners: rootcontract/integration/translations/QA/release; existingUIagentowns3sales_dashboardstaticfiles andfocusedtests; backendagentownsmodels/dashboard.pycategoryfooteronly andfocusedtests; independentreviewerownsaffectedgates anddeliveryreview. G0–G3 awaitfocusedGO before applicationcode. StandingMAINpromotionauthorization retained; quickQA+independentcandidate review beforeupdate.

Live log:
- SD3-01: NarrowG0–G3 independentlyapprovedSD3-R01 beforeappcode. Existing source parent973395. Moduleversionbumped19.0.1.1.1. RootpreparesisolatedQA/releasehelpers; agentsownbackendcategorygrouping andtabbedUI. No repetitions of completedERP/performanceaudit; onlydelta-specificchecks andactualbrowser.
