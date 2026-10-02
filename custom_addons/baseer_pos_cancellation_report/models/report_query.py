"""Read-only audit projection. Deduplication precedes every report filter."""

REPORT_QUERY = r"""
WITH events AS (
    SELECT s.id::bigint * 4 AS id, s.company_id, s.order_id, s.order_id::bigint AS order_identity,
           s.order_reference, s.pos_config_id, s.session_id, s.cashier_id, s.event_at,
           'substitution'::text AS event_type, 'baseer.pos.substitution'::text AS source_model,
           s.id AS source_record_id, 's:' || s.company_id || ':' || s.id AS operation_key,
           s.source_snapshot->>'product_name' AS source_name,
           names.value AS replacement_names, s.source_quantity::numeric AS quantity,
           NULL::text AS reason_code, s.reason_note, ARRAY[s.source_line_uuid]::text[] AS line_uuids,
           false AS data_gap
    FROM baseer_pos_substitution s
    LEFT JOIN LATERAL (
        SELECT string_agg(x->>'product_name', ', ' ORDER BY x->>'line_uuid') AS value
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(s.replacement_snapshot) = 'array'
                                     THEN s.replacement_snapshot ELSE '[]'::jsonb END) x
    ) names ON true
    UNION ALL
    SELECT c.id::bigint * 4 + 1, c.company_id, c.order_id, c.order_id::bigint,
           c.order_reference, c.pos_config_id, c.session_id, c.cashier_id, c.event_at,
           'item_cancel', 'baseer.pos.protected_item_cancellation', c.id,
           'a:cancel:' || c.company_id || ':' || c.order_id || ':' || c.action_uuid,
           c.source_snapshot->>'product_name', NULL, c.source_quantity::numeric,
           c.reason_code, c.reason_note, ARRAY[c.source_line_uuid]::text[], false
    FROM baseer_pos_protected_item_cancellation c
    UNION ALL
    SELECT p.id::bigint * 4 + 2, p.company_id, p.order_id, identity.value,
           p.order_reference, p.pos_config_id, p.session_id, p.requested_by, p.create_date,
           CASE WHEN p.action = 'cancel' THEN 'item_cancel' ELSE 'quantity_reduce' END,
           'baseer.print.preparation.event', p.id,
           'a:' || CASE WHEN p.action = 'cancel' THEN 'cancel:' ELSE 'reduce:' END
                || p.company_id || ':' || COALESCE(identity.value::text, 'unknown:' || p.id)
                || ':' || p.action_uuid,
           p.snapshot->'line'->>'name', NULL, abs(p.delta_quantity)::numeric,
           p.reason_code, p.reason_note, ARRAY[p.line_uuid]::text[], identity.value IS NULL
    FROM baseer_print_preparation_event p
    CROSS JOIN LATERAL (
        SELECT COALESCE(p.order_id::bigint,
               CASE WHEN p.snapshot->'order'->>'id' ~ '^[1-9][0-9]{0,17}$'
                    THEN (p.snapshot->'order'->>'id')::bigint END) AS value
    ) identity
    WHERE p.action IN ('cancel', 'reduce') AND NOT EXISTS (
        SELECT 1 FROM baseer_pos_protected_item_cancellation c
        WHERE p.action = 'cancel' AND c.company_id = p.company_id
          AND c.order_id = identity.value AND c.action_uuid = p.action_uuid
          AND c.source_line_uuid = p.line_uuid
    )
    UNION ALL
    SELECT c.id::bigint * 4 + 3, c.company_id, c.order_id, identity.value,
           c.order_reference, c.pos_config_id, c.session_id, c.requested_by, c.create_date,
           'order_cancel', 'baseer.print.cancellation', c.id,
           'o:' || c.company_id || ':' || c.id,
           lines.names, NULL, CASE WHEN lines.gap THEN NULL ELSE lines.quantity END,
           c.reason_code, c.reason_note, lines.uuids,
           identity.value IS NULL OR COALESCE(lines.gap, true)
    FROM baseer_print_cancellation c
    CROSS JOIN LATERAL (
        SELECT COALESCE(c.order_id::bigint,
               CASE WHEN c.snapshot->'order'->>'id' ~ '^[1-9][0-9]{0,17}$'
                    THEN (c.snapshot->'order'->>'id')::bigint END) AS value
    ) identity
    LEFT JOIN LATERAL (
        SELECT sum(l.quantity) AS quantity, array_agg(l.uuid) FILTER (WHERE l.uuid IS NOT NULL) AS uuids,
               string_agg(l.name, ', ' ORDER BY l.uuid) AS names,
               bool_or(l.gap) OR count(*) = 0 OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements(
                       CASE WHEN jsonb_typeof(c.snapshot->'destinations') = 'array'
                            THEN c.snapshot->'destinations' ELSE '[]'::jsonb END) bad
                   WHERE COALESCE(jsonb_typeof(bad->'lines') <> 'array', true)
               ) AS gap
        FROM (
            SELECT NULLIF(x->>'line_uuid', '') AS uuid, min(x->>'name') AS name,
                   min(CASE WHEN jsonb_typeof(x->'quantity') = 'number'
                                 AND (x->>'quantity')::numeric >= 0
                            THEN (x->>'quantity')::numeric END) AS quantity,
                   NULLIF(x->>'line_uuid', '') IS NULL
                   OR count(DISTINCT x->>'product_id') <> 1
                   OR count(DISTINCT x->>'quantity') <> 1
                   OR bool_or(COALESCE(jsonb_typeof(x->'product_id') <> 'number', true)
                              OR COALESCE(x->>'product_id' !~ '^[1-9][0-9]*$', true))
                   OR bool_or(COALESCE(jsonb_typeof(x->'quantity') <> 'number', true))
                   OR bool_or(CASE WHEN jsonb_typeof(x->'quantity') = 'number'
                                   THEN (x->>'quantity')::numeric < 0 ELSE false END) AS gap
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(c.snapshot->'destinations') = 'array'
                                          THEN c.snapshot->'destinations' ELSE '[]'::jsonb END) d
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(d->'lines') = 'array' THEN d->'lines' ELSE '[]'::jsonb END) x
            GROUP BY NULLIF(x->>'line_uuid', '')
        ) l
    ) lines ON true
)
SELECT e.id, e.company_id, e.order_id, e.order_identity, e.order_reference, e.pos_config_id, e.session_id,
       e.cashier_id, e.event_at, e.event_type, e.source_model, e.source_record_id,
       e.operation_key, e.source_name, e.replacement_names, e.quantity,
       e.reason_code, e.reason_note, e.data_gap OR e.event_at IS NULL AS data_gap,
       prior.id IS NOT NULL AS same_order_review,
       COALESCE(prior.exact, false) AS replacement_cancelled,
       prior.id AS prior_substitution_id, prior.event_at AS prior_substitution_at,
       prior.source_name AS prior_source_name,
       EXISTS (
           SELECT 1 FROM baseer_pos_substitution s
           WHERE e.event_type IN ('item_cancel', 'order_cancel') AND s.company_id = e.company_id
             AND s.order_id = e.order_identity AND s.event_at = e.event_at
       ) AS sequence_uncertain
FROM events e
LEFT JOIN LATERAL (
    SELECT s.id, s.event_at, s.source_snapshot->>'product_name' AS source_name,
           EXISTS (
               SELECT 1 FROM jsonb_array_elements(
                   CASE WHEN jsonb_typeof(s.replacement_snapshot) = 'array'
                        THEN s.replacement_snapshot ELSE '[]'::jsonb END) x
               WHERE NULLIF(x->>'line_uuid', '') = ANY(e.line_uuids)
           ) AS exact
    FROM baseer_pos_substitution s
    WHERE e.event_type IN ('item_cancel', 'order_cancel') AND s.company_id = e.company_id
      AND s.order_id = e.order_identity AND s.event_at < e.event_at
    ORDER BY exact DESC, s.event_at DESC, s.id DESC LIMIT 1
) prior ON true
"""
