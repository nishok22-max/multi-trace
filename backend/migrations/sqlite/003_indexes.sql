-- 003_indexes

-- One build in flight per case (SYSTEM_DESIGN 8.2, 10).
CREATE UNIQUE INDEX builds_one_in_flight
    ON builds(case_id) WHERE status IN ('queued', 'running');

-- Idempotency: the same build_key is unique while queued, running or done.
-- Failed builds fall outside the index, so the same key can be retried.
CREATE UNIQUE INDEX builds_key_active
    ON builds(build_key) WHERE status IN ('queued', 'running', 'done');

CREATE INDEX claims_by_time ON claims(case_id, valid_start, claim_id);
CREATE INDEX claims_by_attribute ON claims(case_id, attribute);
CREATE INDEX claims_by_entity ON claims(case_id, entity_key);
CREATE INDEX comparisons_by_claim_a ON comparisons(case_id, claim_a);
CREATE INDEX comparisons_by_claim_b ON comparisons(case_id, claim_b);
CREATE INDEX review_events_by_review ON review_events(review_id, seq);
CREATE INDEX decisions_by_review ON decisions(case_id, review_id);
CREATE INDEX version_claims_by_version ON version_claims(case_id, version, kind);
CREATE INDEX sessions_by_user ON sessions(user_id);
CREATE INDEX login_attempts_by_user ON login_attempts(username, at);
CREATE INDEX builds_by_case ON builds(case_id, status);
