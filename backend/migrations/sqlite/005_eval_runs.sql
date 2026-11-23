-- 005_eval_runs: operational table (mutable, like builds). One evaluation run in flight at a time,
-- enforced by the database itself (T-34): a second INSERT with status 'running' violates the
-- partial unique index and the API answers 409.
CREATE TABLE eval_runs (
    run_id        TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK (status IN ('running','done','failed','failed_timeout')),
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    error_code    TEXT
) STRICT;

CREATE UNIQUE INDEX eval_one_in_flight ON eval_runs (status) WHERE status = 'running';
