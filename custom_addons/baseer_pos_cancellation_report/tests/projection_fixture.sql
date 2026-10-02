-- Isolated PostgreSQL projection tests. Temp tables shadow real source tables.
BEGIN;
SET LOCAL search_path = pg_temp, public;
CREATE TEMP TABLE baseer_pos_substitution (
 id int, company_id int, order_id int, pos_config_id int, cashier_id int,
 event_at timestamp, order_reference text, source_snapshot jsonb,
 replacement_snapshot jsonb, source_quantity numeric, reason_note text, source_line_uuid text, session_id int DEFAULT 1, source_gross numeric DEFAULT NULL, currency_id int DEFAULT NULL
);
CREATE TEMP TABLE baseer_pos_protected_item_cancellation (
 id int, company_id int, order_id int, pos_config_id int, cashier_id int,
 event_at timestamp, order_reference text, source_snapshot jsonb, source_quantity numeric,
 reason_code text, reason_note text, source_line_uuid text, action_uuid text, session_id int DEFAULT 1, source_gross numeric DEFAULT NULL, currency_id int DEFAULT NULL
);
CREATE TEMP TABLE baseer_print_preparation_event (
 id int, company_id int, order_id int, pos_config_id int, requested_by int, create_date timestamp,
 order_reference text, action text, action_uuid text, line_uuid text, snapshot jsonb,
 delta_quantity numeric, reason_code text, reason_note text, session_id int DEFAULT 1, source_gross numeric DEFAULT NULL, currency_id int DEFAULT NULL
);
CREATE TEMP TABLE baseer_print_cancellation (
 id int, company_id int, order_id int, pos_config_id int, requested_by int, create_date timestamp,
 order_reference text, reason_code text, reason_note text, snapshot jsonb, session_id int DEFAULT 1, source_gross numeric DEFAULT NULL, currency_id int DEFAULT NULL
);
INSERT INTO baseer_pos_substitution VALUES
 (1,1,10,1,1,'2026-09-30 12:00','R10','{"product_name":"Tea"}', '[{"line_uuid":"replacement-1","product_name":"Coffee"}]',2,NULL,'original-1'),
 (2,2,10,2,2,'2026-09-30 12:00','R10','{"product_name":"Other company"}', '[]',1,NULL,'original-2'),
 (3,1,20,1,1,'2026-10-01 09:00','R20','{"product_name":"Milk"}', '[]',1,NULL,'original-3');
INSERT INTO baseer_pos_protected_item_cancellation VALUES
 (1,1,10,1,1,'2026-10-01 08:00','R10','{"product_name":"Coffee"}',2,'customer_cancelled',NULL,'replacement-1','action-1');
INSERT INTO baseer_print_preparation_event VALUES
 (1,1,10,1,1,'2026-10-01 07:59','R10','cancel','action-1','replacement-1','{"line":{"name":"Coffee"},"order":{"id":10}}',-2,'customer_cancelled',NULL),
 (2,1,10,1,1,'2026-10-01 08:00','R10','cancel','action-1','other-line','{"line":{"name":"Bread"},"order":{"id":10}}',-3,'customer_cancelled',NULL),
 (3,1,10,1,1,'2026-10-01 08:00','R10','reduce','action-1','replacement-1','{"line":{"name":"Coffee"},"order":{"id":10}}',-1,NULL,NULL),
 (4,1,NULL,1,1,'2026-10-01 10:00','R10','cancel','action-4','replacement-1','{"line":{"name":"Coffee"},"order":{"id":10}}',-2,'wrong_order',NULL),
 (5,1,NULL,1,1,'2026-10-01 11:00','R10','cancel','action-5','replacement-1','{"line":{"name":"Coffee"}}',-2,'wrong_order',NULL),
 (6,1,20,1,1,'2026-10-01 09:00','R20','cancel','action-6','x','{"line":{"name":"Milk"},"order":{"id":20}}',-1,'staff_error',NULL),
 (7,2,30,2,2,'2026-10-01 09:00','R30','cancel','action-7','replacement-1','{"line":{"name":"Other"},"order":{"id":30}}',-1,'staff_error',NULL);
INSERT INTO baseer_print_cancellation VALUES
 (1,1,NULL,1,1,'2026-10-01 12:00','R10','customer_cancelled',NULL,
  '{"order":{"id":10},"destinations":[{"copies":2,"lines":[{"line_uuid":"replacement-1","product_id":1,"name":"Coffee","quantity":2},{"line_uuid":"b","product_id":2,"name":"Bread","quantity":3}]},{"copies":3,"lines":[{"line_uuid":"replacement-1","product_id":1,"name":"Coffee","quantity":2}]}]}'),
 (2,1,40,1,1,'2026-10-01 12:00','R40','wrong_order',NULL,
  '{"order":{"id":40},"destinations":[{"lines":[{"line_uuid":"c","product_id":1,"name":"Coffee","quantity":2}]},{"lines":[{"line_uuid":"c","product_id":1,"name":"Coffee","quantity":4}]}]}'),
 (3,1,50,1,1,'2026-10-01 12:00','R50','wrong_order',NULL,
  '{"order":{"id":50},"destinations":[]}'),
 (4,1,60,1,1,'2026-10-01 12:00','R60','wrong_order',NULL,
  '{"order":{"id":60},"destinations":[{"lines":[{"line_uuid":"z","product_id":1,"name":"Coffee","quantity":2}]},{"lines":"bad"}]}'),
 (5,1,70,1,1,'2026-10-01 12:00','R70','wrong_order',NULL,
  '{"order":{"id":70},"destinations":[{"lines":[{"line_uuid":"z","product_id":1,"name":"Coffee","quantity":2}]},{"lines":[{"line_uuid":"z","name":"Coffee","quantity":2}]}]}');

-- REPORT_VIEW_PLACEHOLDER

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM report_test WHERE source_model='baseer.print.preparation.event' AND source_record_id=1)
 THEN RAISE EXCEPTION 'protected/preparation duplicate survived'; END IF;
 IF (SELECT quantity FROM report_test WHERE id=7) <> 5
 THEN RAISE EXCEPTION 'printer destinations multiplied quantity'; END IF;
 IF (SELECT count(DISTINCT operation_key) FROM report_test WHERE company_id=1 AND event_type='item_cancel'
      AND event_at='2026-10-01 08:00') <> 1
 THEN RAISE EXCEPTION 'multiline action counted twice'; END IF;
 IF (SELECT count(DISTINCT operation_key) FROM report_test WHERE company_id=1 AND event_at='2026-10-01 08:00') <> 2
 THEN RAISE EXCEPTION 'quantity reduction merged into cancellation'; END IF;
 IF NOT (SELECT replacement_cancelled AND same_order_review AND prior_substitution_id=1 FROM report_test WHERE id=5)
 THEN RAISE EXCEPTION 'prior substitution outside range missing'; END IF;
 IF NOT (SELECT same_order_review AND NOT replacement_cancelled FROM report_test WHERE id=10)
 THEN RAISE EXCEPTION 'other item incorrectly marked replacement'; END IF;
 IF NOT (SELECT replacement_cancelled AND order_identity=10 FROM report_test WHERE id=18)
 THEN RAISE EXCEPTION 'deleted order identity not recovered'; END IF;
 IF NOT (SELECT data_gap AND NOT same_order_review FROM report_test WHERE id=22)
 THEN RAISE EXCEPTION 'unknown order linked by reference'; END IF;
 IF NOT (SELECT sequence_uncertain AND NOT same_order_review FROM report_test WHERE id=26)
 THEN RAISE EXCEPTION 'equal timestamp treated as earlier'; END IF;
 IF (SELECT same_order_review FROM report_test WHERE id=30)
 THEN RAISE EXCEPTION 'cross-company substitution association'; END IF;
 IF NOT (SELECT data_gap AND quantity IS NULL FROM report_test WHERE id=11)
 THEN RAISE EXCEPTION 'conflicting quantities guessed'; END IF;
 IF NOT (SELECT data_gap AND quantity IS NULL FROM report_test WHERE id=15)
 THEN RAISE EXCEPTION 'empty snapshot guessed'; END IF;
 IF (SELECT count(*) FROM report_test) <> (SELECT count(DISTINCT id) FROM report_test)
 THEN RAISE EXCEPTION 'unstable or overlapping projection IDs'; END IF;
 IF (SELECT same_order_review OR replacement_cancelled OR sequence_uncertain FROM report_test WHERE id=14)
 THEN RAISE EXCEPTION 'quantity reduction labelled cancellation review'; END IF;
 IF NOT (SELECT data_gap AND quantity IS NULL FROM report_test WHERE id=19)
 THEN RAISE EXCEPTION 'partial malformed destination silently dropped'; END IF;
 IF NOT (SELECT data_gap AND quantity IS NULL FROM report_test WHERE id=23)
 THEN RAISE EXCEPTION 'missing product in duplicate silently ignored'; END IF;
 IF EXISTS (SELECT 1 FROM report_test WHERE event_at >= '2026-10-01 07:59' AND event_at < '2026-10-01 08:00')
 THEN RAISE EXCEPTION 'deduplication performed after period filter'; END IF;
END $$;
SELECT 'PROJECTION_TESTS=PASS CASES=17' AS result;
ROLLBACK;
