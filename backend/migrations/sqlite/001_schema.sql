-- 001_schema: tables (SYSTEM_DESIGN 8). Evidence tables are append-only (see 002).
-- Operational tables (users, sessions, login_attempts, builds) are mutable.
-- Review and conflict STATUS is never stored: it is derived by views (004).

-- ----------------------------------------------------------------------------- evidence
CREATE TABLE cases (
    case_id       TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    entities      TEXT NOT NULL,            -- JSON array
    window_start  TEXT NOT NULL,
    window_end    TEXT NOT NULL,
    plant_tz      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL
) STRICT;

CREATE TABLE sources (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    source_id     TEXT NOT NULL,
    modality      TEXT NOT NULL CHECK (modality IN ('text','table','image','sensor')),
    sha256        TEXT NOT NULL,
    origin        TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    synthetic     INTEGER NOT NULL CHECK (synthetic IN (0,1)),
    mime          TEXT NOT NULL,
    size          INTEGER NOT NULL CHECK (size >= 0),
    held_reason   TEXT,
    coverage_start TEXT,
    coverage_end   TEXT,
    derived_from_sources TEXT NOT NULL,     -- JSON array of source ids
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, source_id)
) STRICT;

CREATE TABLE claims (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    claim_id      TEXT NOT NULL,            -- content hash: clm_ + 24 hex
    label         TEXT,
    entity_key    TEXT,
    attribute     TEXT NOT NULL,
    valid_start   TEXT,                     -- NULL for UnknownTime; half-open [start, end)
    valid_end     TEXT,
    claim_type    TEXT NOT NULL CHECK (claim_type IN ('extracted','inferred')),
    modality      TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, claim_id),
    CHECK ((valid_start IS NULL) = (valid_end IS NULL))
    -- deliberately NO version column and NO status column (promise 6)
) STRICT;

CREATE TABLE comparisons (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    comparison_id TEXT NOT NULL,
    claim_a       TEXT NOT NULL,
    claim_b       TEXT NOT NULL,
    config_hash   TEXT NOT NULL,
    outcome       TEXT NOT NULL CHECK (outcome IN ('agree','disagree','cant_compare','cant_tell')),
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, comparison_id)
) STRICT;

CREATE TABLE conflicts (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    conflict_id   TEXT NOT NULL,
    sides         TEXT NOT NULL,            -- JSON array of claim ids
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, conflict_id)
    -- no status column: derived from review_events (004)
) STRICT;

CREATE TABLE envelopes (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    envelope_id   TEXT NOT NULL,
    machine       TEXT NOT NULL,
    series_id     TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, envelope_id)
) STRICT;

CREATE TABLE review_items (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    review_id     TEXT NOT NULL,
    type          TEXT NOT NULL,
    claim_ids     TEXT NOT NULL,            -- JSON array
    evidence_hash TEXT NOT NULL,
    opened_at     TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, review_id)
    -- no status column: derived from review_events (004)
) STRICT;

CREATE TABLE decisions (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    decision_id   TEXT NOT NULL,
    review_id     TEXT NOT NULL,
    choice_type   TEXT NOT NULL CHECK (choice_type IN ('entity','reading','explain','escalate')),
    principal_iss TEXT NOT NULL,
    principal_sub TEXT NOT NULL,
    role_snapshot TEXT NOT NULL,
    base_version  INTEGER NOT NULL,
    shown_evidence_hash TEXT NOT NULL,
    supersedes    TEXT,
    at            TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (case_id, decision_id),
    FOREIGN KEY (case_id, review_id) REFERENCES review_items(case_id, review_id)
) STRICT;

CREATE TABLE review_events (
    case_id       TEXT NOT NULL,
    review_id     TEXT NOT NULL,
    seq           INTEGER NOT NULL CHECK (seq >= 0),
    event_id      TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN ('opened','decided','stale','explained')),
    decision_id   TEXT,
    at            TEXT NOT NULL,
    record_hash   TEXT NOT NULL,
    body          TEXT NOT NULL,
    PRIMARY KEY (review_id, seq),
    FOREIGN KEY (case_id, review_id) REFERENCES review_items(case_id, review_id)
) STRICT;

CREATE TABLE versions (
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    version       INTEGER NOT NULL CHECK (version >= 1),
    parent_manifest_hash TEXT,
    manifest_hash TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    config_hash   TEXT NOT NULL,
    engine_sha    TEXT NOT NULL,
    snapshot      BLOB NOT NULL,            -- canonical JSON bytes; sha verified on read
    created_at    TEXT,
    PRIMARY KEY (case_id, version),
    UNIQUE (case_id, manifest_hash)
) STRICT;

CREATE TABLE version_claims (
    case_id       TEXT NOT NULL,
    version       INTEGER NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('claim','comparison','conflict')),
    record_id     TEXT NOT NULL,
    PRIMARY KEY (case_id, version, kind, record_id),
    FOREIGN KEY (case_id, version) REFERENCES versions(case_id, version)
) STRICT;

CREATE TABLE extraction_cache (
    input_sha         TEXT NOT NULL,
    extractor_id      TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    params_hash       TEXT NOT NULL,
    binary_version    TEXT NOT NULL,
    artifact_sha      TEXT NOT NULL,
    artifact          BLOB NOT NULL,
    PRIMARY KEY (input_sha, extractor_id, extractor_version, params_hash, binary_version)
) STRICT;

-- --------------------------------------------------------------------------- operational
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN
                    ('viewer','reviewer','senior_reviewer','ingestor','evaluator')),
    password_hash TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0,1)),
    created_at    TEXT NOT NULL
) STRICT;

CREATE TABLE sessions (
    token_sha256  TEXT PRIMARY KEY,         -- only the hash of the opaque token is stored
    user_id       TEXT NOT NULL REFERENCES users(user_id),
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    expires_at    TEXT NOT NULL
) STRICT;

CREATE TABLE login_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    at            TEXT NOT NULL,
    success       INTEGER NOT NULL CHECK (success IN (0,1))
) STRICT;

CREATE TABLE builds (
    build_id      TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    build_key     TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN
                    ('queued','running','done','failed','failed_stale','failed_timeout',
                     'failed_resource')),
    version       INTEGER,
    started_at    TEXT,
    heartbeat_at  TEXT,
    finished_at   TEXT,
    stage_ms      TEXT NOT NULL DEFAULT '{}',
    counters      TEXT NOT NULL DEFAULT '{}',
    error_code    TEXT
) STRICT;
