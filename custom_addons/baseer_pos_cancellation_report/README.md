# Baseer POS Cancellation Follow-up

Read-only managerial report in Baseer POS Suite. The action combines documented
product substitutions, protected item cancellations, kitchen item cancellations,
quantity reductions and whole kitchen-order cancellations. It does not change
orders, payments, kitchen messages or accounting.

The selected day, month or custom local datetime interval controls all totals.
Intervals include the start and exclude the end. Morning and evening boundaries
are configurable; evening may cross midnight. Details are paginated, while totals
cover the entire filtered selection. Backend aggregation owns every displayed
count, quantity, percentage, shift and review indicator.

Operation counts differ from detail-line counts. Matching protected and kitchen
cancellations represent one operation, and repeated printer destinations or
copies do not multiply cancelled item quantities. Quantity reductions remain
separate from complete item cancellations. Quantities are POS units, not a
homogeneous inventory unit across products. Percentages describe documented
operations, not revenue or sales percentages.

A substitution followed by cancellation in the same order is a review indicator.
Cancelling an actual replacement is distinguished by its saved line UUID.
Equal or missing timestamps and conflicting snapshots do not prove chronology
or quantities. Existing source records stay immutable and can be inspected with
their original access controls.

Coverage is limited to stored audit sources. An ordinary unprotected item deleted
before kitchen submission may have no cancellation history. Current order lines
cannot reconstruct all deleted items or prove a historical count of items never
substituted. The report must not present such an inferred number as complete.

Access remains limited to POS managers and system administrators, within their
active allowed companies. This addon grants no cashier access to printer hardware
or audit management.

Validation and preview status are recorded in
`docs/build-governance/POS-CANCELLATION-FOLLOWUP-20261002.md`. Standalone frontend
request tests run with:

```sh
node custom_addons/baseer_pos_cancellation_report/static/tests/report_requests.test.mjs
```

Odoo integration tests require an explicitly isolated local test database. A
synthetic layout screenshot does not establish ORM, native-widget, permissions or
production readiness.

Pure filter/time/number helper tests execute the actual functions from the model:

```sh
python custom_addons/baseer_pos_cancellation_report/tests/test_filters_standalone.py
```

Projection tests use PostgreSQL temporary tables which shadow the audit source
tables, then roll back. They do not test Odoo ACL enforcement or registry install:

```sh
python custom_addons/baseer_pos_cancellation_report/tests/run_projection.py \
  --container LOCAL_TEST_POSTGRES --database baseer_cancellation_report_test_20261002 --user LOCAL_TEST_ROLE
```

Odoo integration test tag after installing on an isolated test database:
`--test-enable --test-tags /baseer_pos_cancellation_report --stop-after-init`.
Keep `max_cron_threads = 0` on a restored preview database.

Local acceptance on 2026-10-02: 11 Odoo integration tests passed, including
cashier denial, active-company isolation, operation counts, grouping, exact
decimal formatting, stale-page handling and overnight shifts. Arabic and English
journeys used the actual Odoo calendar and pager on desktop and a 390px viewport.
Screenshots contain explicitly synthetic preview data, not production totals.

The backend materializes the ORM-filtered audit projection once within one SQL
statement for totals, charts, grouping and details. No persistent cache or changes
to audit sources or database configuration are introduced. A 100,000-event TEMP
fixture took 3.85–3.96 seconds for the complete monthly request on the local test
environment. The original two-second target was not met; 20 simultaneous users
and production data were not tested. Acceptance is for local preview only.

`tests/benchmark_report.py` runs through Odoo shell on the exact isolated preview
database after preparing the synthetic preview manager/configuration. It creates
only temporary tables/views and rolls back. Indexes precede inserted/updated
load data so a repeatable-read snapshot does not invalidate index usability.
