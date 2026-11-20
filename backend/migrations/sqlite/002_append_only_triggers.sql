-- 002_append_only_triggers: every EVIDENCE table rejects UPDATE and DELETE (promise 6).
-- Operational tables (users, sessions, login_attempts, builds) are intentionally excluded.
-- Connections set PRAGMA recursive_triggers=ON so INSERT OR REPLACE (which deletes the old
-- row) also fires the delete trigger.

CREATE TRIGGER cases_no_update BEFORE UPDATE ON cases
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER cases_no_delete BEFORE DELETE ON cases
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER sources_no_update BEFORE UPDATE ON sources
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER sources_no_delete BEFORE DELETE ON sources
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER claims_no_update BEFORE UPDATE ON claims
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER comparisons_no_update BEFORE UPDATE ON comparisons
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER comparisons_no_delete BEFORE DELETE ON comparisons
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER conflicts_no_update BEFORE UPDATE ON conflicts
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER conflicts_no_delete BEFORE DELETE ON conflicts
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER envelopes_no_update BEFORE UPDATE ON envelopes
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER envelopes_no_delete BEFORE DELETE ON envelopes
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER review_items_no_update BEFORE UPDATE ON review_items
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER review_items_no_delete BEFORE DELETE ON review_items
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER review_events_no_update BEFORE UPDATE ON review_events
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER review_events_no_delete BEFORE DELETE ON review_events
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER versions_no_update BEFORE UPDATE ON versions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER versions_no_delete BEFORE DELETE ON versions
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER version_claims_no_update BEFORE UPDATE ON version_claims
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER version_claims_no_delete BEFORE DELETE ON version_claims
BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE TRIGGER extraction_cache_no_update BEFORE UPDATE ON extraction_cache
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER extraction_cache_no_delete BEFORE DELETE ON extraction_cache
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
