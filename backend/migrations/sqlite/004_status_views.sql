-- 004_status_views: status is DERIVED from append-only events, never stored (N-1).
--
-- review_status.status:
--   last event among (opened, decided, stale) decides:
--     stale                                  -> 'stale'
--     decided with an 'escalate' decision    -> 'escalated' (manual escalation)
--     decided otherwise                      -> 'decided'
--     opened (or no event yet)               -> 'open'
--   'explained' events never change status; they only set the `explained` flag.
-- Auto-escalation after one working day is computed at read time in Python (Clock port).

CREATE VIEW review_status AS
SELECT
    ri.case_id,
    ri.review_id,
    CASE le.kind
        WHEN 'stale' THEN 'stale'
        WHEN 'decided' THEN
            CASE d.choice_type WHEN 'escalate' THEN 'escalated' ELSE 'decided' END
        ELSE 'open'
    END AS status,
    EXISTS (
        SELECT 1 FROM review_events x
        WHERE x.review_id = ri.review_id AND x.kind = 'explained'
    ) AS explained
FROM review_items ri
LEFT JOIN review_events le
    ON le.review_id = ri.review_id
   AND le.seq = (
        SELECT MAX(y.seq) FROM review_events y
        WHERE y.review_id = ri.review_id AND y.kind IN ('opened', 'decided', 'stale')
   )
LEFT JOIN decisions d
    ON d.case_id = ri.case_id AND d.decision_id = le.decision_id;

-- conflict_status: 'explained' when a conflict_explain review item covering one of the
-- conflict's sides has an 'explained' event; otherwise 'open'. Never changes the outcome.
CREATE VIEW conflict_status AS
SELECT
    c.case_id,
    c.conflict_id,
    CASE WHEN EXISTS (
        SELECT 1
        FROM review_items ri
        JOIN review_events e ON e.review_id = ri.review_id AND e.kind = 'explained'
        WHERE ri.case_id = c.case_id
          AND ri.type = 'conflict_explain'
          AND EXISTS (
              SELECT 1 FROM json_each(ri.claim_ids) a
              JOIN json_each(c.sides) s ON a.value = s.value
          )
    ) THEN 'explained' ELSE 'open' END AS status
FROM conflicts c;

CREATE VIEW latest_versions AS
SELECT case_id, MAX(version) AS version FROM versions GROUP BY case_id;
