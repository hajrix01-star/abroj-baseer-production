\pset format unaligned
\pset tuples_only on
\echo SUMMARY_QUERY
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT id
FROM baseer_pos_summary
WHERE company_id = 54
  AND business_date >= DATE '2026-07-01'
  AND business_date <= DATE '2026-09-30'
  AND state <> 'cancelled';
\echo CLOSURE_QUERY
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT id
FROM baseer_pos_closure
WHERE company_id = 54
  AND state = 'confirmed'
  AND date_from <= DATE '2026-09-30'
  AND date_to >= DATE '2026-07-01';
