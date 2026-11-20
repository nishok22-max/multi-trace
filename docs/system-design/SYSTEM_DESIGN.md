# TRACE — System Design

*Every fact has an address. Every conflict stays visible.*

| Field | Value |
|---|---|
| Version | 1.0 (binding: produced by a 3-agent adversarial debate plus an independent Judge) |
| Date | 2026-11-20 |
| Requirements | [`../TRACE_PRD.md`](../TRACE_PRD.md) v1.1 |
| Decisions | [`DECISIONS.md`](DECISIONS.md): 15 ADRs |
| Hardening | [`HARDENING.md`](HARDENING.md): 44 threats, each with a control and a named test |
| Debate record | [`DEBATE_LOG.md`](DEBATE_LOG.md) and the raw rounds in [`debate/`](debate/) |
| Stack | **Backend:** Python 3.11, FastAPI, Pydantic v2. **Frontend:** Astro (static), Tailwind CSS, React islands. |

> **Ruling principle (from the Judge).** TRACE's product *is* a set of promises:
> - "no data ≠ normal";
> - "never guess";
> - "every fact has an address";
> - "never averaged".
>
> A broken promise costs more than a missing feature. So hours go first to the **correctness floor**, then to the **security floor**, then to visible features, and only then to infrastructure.

---

## Contents
1. [Architecture at a glance](#1-architecture-at-a-glance)
2. [System context](#2-system-context-c4-level-1)
3. [Container view](#3-container-view-c4-level-2)
4. [Hexagonal core: ports and adapters](#4-hexagonal-core-ports-and-adapters)
5. [Repository layout](#5-repository-layout)
6. [The pipeline](#6-the-pipeline)
7. [The Comparability Gate and the correctness floor](#7-the-comparability-gate-and-the-correctness-floor)
8. [Data model and storage](#8-data-model-and-storage)
9. [Integrity and determinism](#9-integrity-and-determinism)
10. [Build execution and concurrency](#10-build-execution-and-concurrency)
11. [Human decision loop](#11-human-decision-loop)
12. [API design](#12-api-design)
13. [Authentication and authorisation](#13-authentication-and-authorisation)
14. [Frontend architecture](#14-frontend-architecture)
15. [Extraction subsystem](#15-extraction-subsystem)
16. [Observability](#16-observability)
17. [Testing strategy](#17-testing-strategy)
18. [Deployment](#18-deployment-hackathon-tier)
19. [Scale path: hackathon → production](#19-scale-path-hackathon--production)
20. [Performance budget (NFR-7)](#20-performance-budget-nfr-7)
21. [36-hour team plan](#21-36-hour-team-plan)
22. [Requirements traceability](#22-requirements-traceability)
23. [Judge Q&A: the ten hardest questions](#23-judge-qa-the-ten-hardest-questions)

---

## 1. Architecture at a glance

```
 +---------------------------------------------------------------------------------------------+
 |                                ONE CONTAINER  (Linux, non-root, RO rootfs)                  |
 |                                                                                             |
 |   Browser ──HTTPS/HTTP same-origin──►  FastAPI  (trace_api)                                 |
 |   Astro static pages +                  │  ├─ serves Astro dist/  (HTML shell, JS, CSS)     |
 |   React islands                         │  ├─ /api/v1  REST + OpenAPI 3.1                   |
 |   (TanStack Query, ECharts)             │  ├─ sessions, CSRF, RBAC, upload caps, CSP        |
 |                                         │  └─ sync decision re-run  (< 2 s)                 |
 |                                         │                                                   |
 |                                         ▼ spawn (killable, RLIMIT, 180 s)                   |
 |                                   Build child process  ── runs ──►  trace_core (PURE)       |
 |                                   read → normalise → compare → score → snapshot             |
 |                                         │                                                   |
 |        ┌────────────────────────────────┼───────────────────────────────┐                   |
 |        ▼                                ▼                               ▼                   |
 |   SQLite (WAL, 1 file)          Blob store (content-addressed)    Parquet per machine        |
 |   append-only triggers          blobs/sha256/ab/cd/<hash>         (derived telemetry)        |
 |   hash chain + version_claims   read-only, 'xb' writes            + frozen JSON snapshots    |
 +---------------------------------------------------------------------------------------------+
           anchors/demo_roots.txt  ──git push──►  remote repository  (external tamper anchor)
```

**The design in ten lines:**
1. **One deployable, a hexagonal modular monolith.** `trace_core` is a pure function of explicit inputs.
2. **Static Astro on the same origin as FastAPI.** One React island per page; no CORS and no second runtime.
3. **One SQLite file** with append-only triggers, a `version_claims` table, and status *derived*, never stored.
4. **SHA-256 everywhere.** Per source, per evidence pointer, per record and per version, chained, with the root **pushed to a remote**.
5. **Content-addressed claim IDs + cached reader outputs + a config hash** → byte-identical replay.
6. **Full builds** run in a killable child process with heartbeats. **Decision re-runs** are synchronous over cached claims.
7. **"Normal" is a split-conformal robust max-z threshold**, so quiet-day false alarms are ≤ 5% by construction.
8. **Telemetry units are `sensor_native`.** They are never converted and compared only against the same series.
9. **Per-user argon2id sessions.** Identity comes only from the session; uploads are hardened and role-gated.
10. **1M readers is a cache problem.** Frozen versions are cached at an authorised edge. Every other scale box must earn its place.

---

## 2. System context (C4 level 1)

```
   ┌────────────────────┐   reads story, proof     ┌──────────────────────────────────────┐
   │ Operator           │ ───────────────────────► │                                      │
   │ (non-specialist)   │                          │                TRACE                 │
   └────────────────────┘                          │                                      │
   ┌────────────────────┐   decides, with reason   │  Turns reports, photos, tables and   │
   │ Reviewer / Senior  │ ───────────────────────► │  sensor data into one inspectable    │
   └────────────────────┘                          │  case state of addressed claims;     │
   ┌────────────────────┐   inspects gate, envelope│  flags only genuine conflicts and    │
   │ Engineer / Expert  │ ───────────────────────► │  never averages them away.           │
   └────────────────────┘                          │                                      │
   ┌────────────────────┐   runs benchmark, reads  │                                      │
   │ Evaluator / Judge  │ ───────────────────────► │                                      │
   └────────────────────┘   integrity + replay     └───────┬───────────────────┬──────────┘
   ┌────────────────────┐   uploads files (role)           │                   │
   │ Ingestor           │ ─────────────────────────────────┘                   │ git push
   └────────────────────┘                                                      ▼ (anchor)
   ┌─────────────────────────────────────┐                            ┌───────────────────┐
   │ Microsoft PdM dataset (CSV, offline)│ ── seeded at build time ──►│ Remote git repo   │
   │ Authored evidence (PDF, PNG, CSV)   │                            │ demo_roots.txt    │
   └─────────────────────────────────────┘                            └───────────────────┘
   P1 only:  LLM / VLM provider  ◄── via offline-recorded cache; no network calls in P0
```

---

## 3. Container view (C4 level 2)

```
 ┌───────────────────────────────────── Browser ─────────────────────────────────────────┐
 │  Astro static HTML shells:  /  /case  /case/expert  /review  /eval  /login            │
 │  React island per page  (client:only="react")                                         │
 │    TanStack Query  ── keys always include {caseId, version}                           │
 │    RegionViewer (PNG + bbox overlay) · SensorChart (ECharts) · Timeline (ECharts)     │
 │  Typed client: openapi-typescript + openapi-fetch  (types generated from /openapi.json)│
 └──────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ same origin, cookie session, X-TRACE-CSRF
 ┌──────────────────────────────────────────▼────────────────────────────────────────────┐
 │  trace_api  (FastAPI, uvicorn, bound 127.0.0.1 by default)                            │
 │   middleware: request_id · upload stream caps · security headers/CSP · problem+json   │
 │   deps: current_user → resolve_case_and_authorize(case_id, role)                      │
 │   routers: auth · cases · versions · claims/evidence/recheck · review/decision ·      │
 │            integrity/replay · eval                                                    │
 │   services: DecisionService (sync re-run) · BuildService (spawns child) · SnapshotLRU │
 └───────┬──────────────────────────────┬───────────────────────────────┬────────────────┘
         │ spawn                        │ read/write                    │ read
 ┌───────▼────────────────┐   ┌─────────▼───────────────┐   ┌───────────▼────────────────┐
 │ Build child process    │   │ SQLite  data/trace.db   │   │ Files under data/          │
 │ (multiprocessing spawn)│──►│ WAL, busy_timeout 5000  │   │  blobs/sha256/…  (RO)      │
 │ trace_core.build_case()│   │ evidence tables: append │   │  telemetry/<machine>.parquet│
 │ heartbeat every 5 s    │   │ only (triggers)         │   │  pages/<sha>/<p>@150.png   │
 │ RLIMIT_AS 2 GiB        │   │ operational: builds,    │   │  snapshots/<case>/<v>.json │
 │ pytesseract timeout 20s│   │ sessions, users         │   │  (sha256 on versions row)  │
 └────────────────────────┘   └─────────────────────────┘   └────────────────────────────┘
```

---

## 4. Hexagonal core: ports and adapters

```
                         ┌─────────────────────────── trace_core (PURE) ───────────────────────────┐
                         │  no FastAPI · no sqlite3 · no filesystem · no datetime.now() · no network│
   driving side          │                                                                          │
 ┌──────────────┐        │   build_case(manifest, config_bundle, decisions, clock) -> CaseVersion  │
 │ trace_api    │──────► │                                                                          │
 │ build child  │──────► │   read/        normalise/          compare/          score/              │
 │ tests/golden │──────► │   text  table  units  entities    gate (6 checks)   trust  confidence   │
 │ P2: Temporal │──────► │   sensor image time   envelopes   quantifiers       independence       │
 │   activities │        │                        gaps        outcomes          snapshot           │
 └──────────────┘        │                                                                          │
                         │   Ports (typing.Protocol):                                               │
                         │   ClaimStore · BlobStore · PdfReader · OcrReader · ExtractionCache ·     │
                         │   Clock · LlmProposer                                                    │
                         └─────┬──────────┬──────────┬──────────┬──────────┬──────────┬────────────┘
                               │          │          │          │          │          │
   driven side (adapters)      ▼          ▼          ▼          ▼          ▼          ▼
                         SqliteClaim  FsBlob     PyMuPdf    Tesseract  SqliteExtr  FakeLlm (P0)
                         Store        Store      Reader     Reader     Cache       RecordedLlm (P1)
                         ── P2 swap ──────────────────────────────────────────────────────────────
                         PgClaimStore S3ObjLock  Pdfium     +VLM       PgCache     GatewayLlm
```

- An **`import-linter` contract** in pre-commit: `trace_core` must not import `trace_adapters` or `trace_api`.
- **Stage functions are the future Temporal activity boundary.** That makes the PRD's "the engine runs unchanged in workers" literally true.

---

## 5. Repository layout

```
trace/
├── backend/
│   ├── trace_core/            # pure domain: models.py (Pydantic), build.py, read/, normalise/,
│   │                          #   compare/, score/, canonical.py (JCS, fixed-6dp floats)
│   ├── trace_adapters/        # sqlite_store.py, blob_fs.py, pymupdf_reader.py, tesseract_ocr.py,
│   │                          #   extraction_cache.py, clock.py, llm_fake.py
│   ├── trace_api/             # main.py, deps.py, problems.py, security.py, routers/*, services/*
│   ├── trace_worker/          # build_runner.py (spawned child, heartbeat, rlimit)
│   ├── trace_eval/            # injector.py (seeded, dev/holdout), baselines.py, metrics.py
│   ├── config/                # tolerances.yaml, ontology.yaml (with quantifiers), phrases.yaml,
│   │                          #   aliases.yaml, shifts.yaml, envelope.yaml, case.yaml (plant_tz)
│   ├── migrations/            # 001_schema.sql (tables + append-only triggers)
│   └── tests/                 # golden/, properties/, hostile_corpus/, authz/, eval/
├── frontend/
│   ├── astro.config.mjs       # output:'static', @astrojs/react, Tailwind, inlineStylesheets:'never'
│   └── src/
│       ├── pages/             # index, case, case/expert, review, eval, login (.astro shells)
│       ├── islands/           # CaseWorkspace, ExpertView, ReviewQueue, EvalDashboard, LoginForm
│       ├── components/        # ConflictCard, GateTable, RegionViewer, SensorChart, Timeline,
│       │                      #   StoryStep, VersionBadge, IntegrityBadge
│       └── lib/api/           # schema.d.ts (generated), client.ts (openapi-fetch + CSRF header)
├── seed/                      # authored PDFs/photos/CSV, labels.yaml, credentials.local.txt (ignored)
├── data/                      # runtime volume (db, blobs, parquet, pages, snapshots)
├── anchors/demo_roots.txt     # manifest hashes, pushed before the demo
├── e2e/                       # Playwright (runs under the enforcing CSP)
├── Dockerfile  Makefile  uv.lock  package-lock.json  .importlinter
```

---

## 6. The pipeline

```
 upload (ingestor) ──► stream-capped, magic-byte check, sha256 ──► blobs/ (RO)  + sources row
                                                                             │
 POST /cases/{cid}/build ──► build_key = sha256(src shas‖config_hash‖decision ids‖engine_sha‖lock)
        │                    exists? ──yes──► return existing version (idempotent)
        ▼ no
 ┌──────────── build child process (trace_core.build_case) ──────────────────────────────────────┐
 │ 1 READ        text/PDF: pypdfium2 page text artifact (hashed) + offsets + char boxes; hidden │
 │               guard │ CSV: row/col + row_sha256 │ telemetry → Parquet per machine (derived    │
 │               source) │ image: exif_transpose → Tesseract words+bbox → re-read (consistency)  │
 │               → all raw reader outputs into extraction_cache                                  │
 │ 2 NORMALISE   units (pint; telemetry = sensor_native) │ entity resolver (ranked candidates,   │
 │               non-string feature, serial veto) │ time (plant_tz, half-open UTC) │ envelopes    │
 │               (conformal max-z) │ gaps / flatline / duplicate-ts                               │
 │   ── review gate: ambiguous links, reader disagreement, implausible values → HELD ──          │
 │ 3 COMPARE     candidate pairs by (entity, attribute, interval sweep) → 6 checks → 4 outcomes │
 │               → conflict grouping (C-17 + S-88 + error rows on one card)                      │
 │ 4 SCORE       confidence components, independence graph (declared provenance only)           │
 │ 5 SNAPSHOT    record_hash per record → version_claims → manifest_hash (chained) →            │
 │               snapshots/<case>/<v>.json (sha256 stored)                                       │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
        │ heartbeat every 5 s; per-stage ms + counters on the builds row
        ▼
 UI polls GET /builds/{id} (P1: SSE)  ──►  GET /cases/{cid}/versions/{v}/story  (immutable, ETag)
```

---

## 7. The Comparability Gate and the correctness floor

### 7.1 Gate flow

```
   claim A ─┐                                                       (pairs from interval sweep
            ├──► held for review? ──yes──► excluded until decided    on same entity+attribute)
   claim B ─┘          │ no
                       ▼
  ① same entity?  (resolved, not ambiguous) ───────── no ──► THEY CAN'T BE COMPARED
                       ▼ yes
  ② same attribute? (ontology mapping, e.g. "ran normally" ↔ operating_state) ─ no ──► CAN'T COMPARE
                       ▼ yes
  ③ same time?  max(start) < min(end), compatible granularity, time known ── no ──► CAN'T COMPARE
                       ▼ yes
  ④ comparable terms?  same dimension; telemetry: same series_id AND
     claim (statistic, granularity) == envelope (statistic, granularity) ─── no ──► CAN'T COMPARE
                       ▼ yes
  ⑤ any real data?  coverage > 0 on both sides ───────────────────────────── no ──► WE CAN'T TELL
                       ▼ yes                                                        (GapClaim)
  ⑥ beyond normal variation? — apply the phrase QUANTIFIER
       ∀ phrase ("ran normally"):  violation observed or error event ─────────────► THEY DISAGREE
                                   100% coverage AND T_D ≤ T* AND logs cover ────► THEY AGREE
                                   otherwise ───────────────────────────► WE CAN'T TELL (partial)
       ∃ phrase ("vibration noticed"): violation observed ─────────────────────────► THEY AGREE
                                   full coverage, no violation ───────────────────► THEY DISAGREE
       numeric vs numeric: |a−b| > max(abs_tol, rel_tol·|ref|, res_a+res_b) ─ yes ► DISAGREE / else AGREE

   Every outcome stores all six check results + reason + config_hash.  Nothing is ever averaged.
```

### 7.2 What "normal" means: split-conformal robust max-z (replaces PRD §10.3–10.6)

The PRD's rule is "every hourly value of 4 channels inside p5–p95". That is about 96 tests a day at about 10% each, so a **quiet day almost never passes**. The Red Team found this (T-01) and the Judge replaced the rule:

```
 Quiet days Q (machine m):  no error/maint/failure within ±3 d  ∧  every event log's coverage_period
                            covers the day (else build REFUSES: /problems/log-coverage)  ∧  telemetry
                            24/24 h every channel  ∧  outside case window ±3 d
                            policy: all_except_case_window (retrospective, demo) | before_only (live)

 Per channel c:   med_c = median(x_c,h over Q)        s_c = 1.4826 · MAD_c     (MAD=0 → channel excluded)

 Day statistic:   T_d = max over c∈scope, h∈d of |x_c,h − med_c| / s_c         (one test per day)

 Threshold:       T* = T_(k) of {T_d : d∈Q},  k = ⌈(1−α)(n+1)⌉,  α = 0.05
                  ⇒ P(false alarm on a new quiet day) ≤ α   (split conformal, exchangeability)
                  n < 19 → T* pooled across same-model machines (T_d is unitless)
                  n < 10 → med/MAD also model-level   → labelled "thin history / model-level"

 Displayed band:  med_c ± T*·s_c  (alarm band)   ·   p5–p95 shaded lighter: "typical, not threshold"
 Confidence:      1 − p,  p = (1 + #{d∈Q : T_d ≥ T_D}) / (n+1)   × coverage × history_factor
 Drift guard:     T* moves > 10 % between versions → review item
 envelope_id   =  sha256(machine, scope, "robust_max_z", "day", sorted Q, params, partition hashes)
```

**Consequences, all binding:**
- **S-88 is a day-level claim.** It covers [14 Mar 00:00, 15 Mar 00:00) plant-local, comparing T_D against T\*. The 14:00 peak is a **child claim, S-88.1**. Day is compared with day, so check ③ is well defined.
- **The demo numbers are computed, never typed.** "Peak 64 vs normal 34–47", "0.71", "0.94" and "0.62" are replaced by computed values (see the PRD change list in [`debate/r3_judge.md` Part 4](debate/r3_judge.md)). With the PRD's own formula, C-17 computes to **0.83**.
- **Telemetry units are `sensor_native`** ("sensor units, undocumented"). A gauge reading in bar vs. telemetry pressure gives **"They can't be compared"**. Assuming kPa would be exactly the unit guessing the PRD forbids.
- **Duplicate timestamps** with different values become `GapClaim(conflicting_readings)` and are never averaged.
- **A flatline** is variance ≤ ε over ≥ 6 h, *unless* a stop or maintenance event explains it.

---

## 8. Data model and storage

### 8.1 Entity relationships

```
  users ──< sessions                        builds (operational, mutable: status, heartbeat, ms)
    │
    └──< decisions >── review_items ──< review_events          (status DERIVED from events)
              │              │
              │              └── claim_ids ─────────────┐
              ▼                                         ▼
  cases ──< sources (sha256, coverage_period, derived_from_sources, synthetic)
    │          │
    │          └──< claims (case_id, claim_id=content hash, label, entity_key, attribute,
    │                       valid_start, valid_end [half-open UTC], claim_type, record_hash, body)
    │                  │  ▲ derived_from (inferred)              ▲
    │                  │  └──────────────────────────────────────┘
    │                  ├──< comparisons (6 checks, outcome, config_hash) ──< conflicts
    │                  └── evidence pointer: text_span | image_region | table_cell |
    │                                        sensor_window | human_decision   (+ per-pointer sha)
    ├──< versions (UNIQUE(case,version), parent_manifest_hash, manifest_hash, snapshot_sha256,
    │              config_hash, engine_sha, build_key UNIQUE)
    │        └──< version_claims (case_id, version, claim_id | comparison_id | conflict_id)
    ├──< envelopes (envelope_id = content hash)
    └──< extraction_cache (input_sha, extractor_id, extractor_version, params_hash → artifact sha)
```

### 8.2 Storage rules
| Rule | Mechanism |
|---|---|
| Append-only evidence | `BEFORE UPDATE` and `BEFORE DELETE` triggers with `RAISE(ABORT,'append-only')`, plus a repository with no update or delete methods, plus the hash chain |
| No version field inside immutable claims | Membership is recorded in `version_claims` |
| No mutable status inside evidence | `ReviewItem.status` and `ConflictRecord.status` are derived from `review_events` and decisions at snapshot time |
| Time ordering | Half-open `[start, end)` in fixed-width UTC `YYYY-MM-DDTHH:MM:SSZ`, so string order equals time order |
| Telemetry | Split once per machine into Parquet (pyarrow). Each split is a **derived source** with its own sha256. Raw hourly readings are **not** claims. |
| Snapshots | `snapshots/{case}/{v}.json`, with its sha256 on `versions`, verified when the LRU is filled |
| Concurrency | WAL, `busy_timeout=5000`, short `BEGIN IMMEDIATE` transactions, one build in flight per case (partial unique index) |

---

## 9. Integrity and determinism

```
  source bytes ──sha256──► source_sha ─────────────────────────────────────────────┐
  page text artifact ──sha256──► page_text_sha ─┐                                   │
  quote ──sha256──► quote_sha ──────────────────┤ per-pointer hashes                │
  image crop ──sha256──► crop_sha ──────────────┤ (recheck < 1 s)                   │
  CSV line bytes ──sha256──► row_sha ───────────┤                                   │
  Arrow IPC window slice ──sha256──► window_sha ┘                                   │
                                                                                    ▼
  record_hash = sha256( JCS(body − wall-clock fields) )   [RFC 8785, rfc8785 package]
                                                                                    │
  manifest_hash(v) = sha256( parent_manifest_hash ‖ sorted record_hashes ‖ config_hash ‖
                             engine_sha ‖ lockfile_hash ‖ sorted source shas ‖ snapshot_sha256 )
                                                                                    │
            v1 ──► v2 ──► v3 ──► …   (chain)          GET …/integrity re-walks → green/red badge
                                                                                    │
  anchors/demo_roots.txt ◄── append manifest_hash ── git commit ── git PUSH before stage ──► remote
  P1: Ed25519 signature over manifest, private key OFF the serving box (age-encrypted), key_id
```

**Three separate guarantees:**
1. **Triggers** stop accidental edits.
2. **The chain** detects a deliberate edit.
3. **The pushed anchor** detects someone rewriting the chain itself.

**Determinism:**
- `claim_id = "clm_" + sha256(JCS(semantic fields + pointer + method))[:24]`. Display labels (C-17, S-88) come from `seed/labels.yaml` by mention key.
- `config_hash` covers tolerances, τ, α, the ontology with quantifiers, phrases, aliases, shifts, `plant_tz` and envelope parameters.
- dateparser runs with `RELATIVE_BASE = observed_time`, a fixed `DATE_ORDER` and a fixed `TIMEZONE`.
- **Replay reads reader outputs only from `extraction_cache`. A cache miss under replay is an error.**
- Floats are serialised as fixed 6-decimal strings for hashing. Collections are sorted by `(valid_start, claim_id)`. Quantiles use an explicit `method`. `PYTHONHASHSEED=0`.
- **Honest claim:** replay from stored artifacts is byte-identical on any machine. Fresh OCR is reproducible inside the pinned image.

---

## 10. Build execution and concurrency

```
 POST /cases/{cid}/build ─► BuildService
     │  INSERT builds(status=queued, build_key)  ── partial UNIQUE(case_id) WHERE status∈{queued,running}
     │        conflict → 409 /problems/build-in-progress  (Retry-After: 5)
     ▼
  multiprocessing.get_context("spawn").Process(target=build_runner)
     │  child: setrlimit(RLIMIT_AS, 2 GiB) · pytesseract(timeout=20) · heartbeat_at every 5 s
     │  parent watchdog: wall 180 s → terminate() → status=failed_timeout
     ▼
  status=done (+ per-stage ms, counters)  ──►  UI poll 1 s (P1: SSE "version ready")

  startup sweep:  running ∧ heartbeat_at < now−60 s  →  failed_stale   (a crash never stays "running")
  re-POST is safe: same build_key → existing version returned
```

**Why not the other options?**
- **`BackgroundTasks`:** in-process, cannot be killed, and blocks the event loop.
- **`ProcessPoolExecutor`:** a hung worker cannot be killed without breaking the pool.
- **Postgres + Procrastinate / Celery:** a broker that no P0 requirement needs.

---

## 11. Human decision loop

```
 Reviewer (session: user_id, role)            FastAPI DecisionService               SQLite
   │ POST /cases/{cid}/review/{rid}/decision                                          │
   │ {choice, reason≥15, base_version, shown_evidence_hash}   + X-TRACE-CSRF          │
   ├───────────────────────────────────────────►│                                      │
   │                                            │ extra="forbid": "reviewer" field → 422│
   │                                            │ role ≥ reviewer else 403              │
   │                                            │ BEGIN IMMEDIATE ─────────────────────►│
   │                                            │ already decided?  → 409 already-decided
   │                                            │ evidence hash ≠ shown? → 409 evidence-changed
   │                                            │ build in flight?  → 409 build-in-progress
   │                                            │ INSERT HumanDecision claim + review_event
   │                                            │ re-run: link → gate → trust → snapshot│
   │                                            │ (cached claims only; no parse/OCR)    │
   │                                            │ new version + manifest_hash (chained) │
   │                                            │ COMMIT ──────────────────────────────►│
   │◄───────── 201 {version: v+1, story delta} ─│               p95 target < 2 s         │
   │ TanStack Query invalidates keys for v → fetches v+1 (all panels show same version)   │
```

- A stale `base_version` on an untouched item is **accepted** and recorded, so unrelated decisions don't block each other.
- **Supersede** needs `senior_reviewer` and an explicit `supersedes` field.
- **Escalate** is a decision type. Auto-escalation after 1 working day is computed at read time from the `Clock`.
- **"Mark conflict explained"** adds a badge and a reason. It never changes the outcome or hides the card.
- Decisions are keyed to a **stable mention key** `(source_sha256, locator)`. If the evidence under it changes, the decision becomes `stale` and the item re-opens.

---

## 12. API design

**Base:** `/api/v1`, REST, OpenAPI 3.1, errors as RFC 9457 `application/problem+json`. **Every route is case-scoped**, and a single `resolve_case_and_authorize` dependency maps every ID to its case and checks the role.

| Method | Path | Role | Cache |
|---|---|---|---|
| POST | `/auth/login`, `/auth/logout` | — | no-store |
| POST | `/cases` | ingestor | no-store |
| POST | `/cases/{cid}/sources` (multipart, streaming caps) | ingestor | no-store |
| POST | `/cases/{cid}/build` → `202 {build_id}` | ingestor | no-store |
| GET | `/cases/{cid}/builds/{bid}` | viewer | no-store |
| GET | `/cases/{cid}/latest` → `307` to the versioned path | viewer | no-store |
| GET | `/cases/{cid}/versions/{v}/{state\|story\|timeline\|claims\|comparisons\|conflicts\|review}` | viewer | private, immutable, ETag = manifest_hash, Vary: Cookie |
| GET | `/cases/{cid}/claims/{id}/evidence` | viewer | private, immutable |
| POST | `/cases/{cid}/claims/{id}/recheck` → `{match, source_sha_ok, value_ok}` | viewer | no-store |
| POST | `/cases/{cid}/review/{rid}/decision` | reviewer | no-store |
| GET | `/cases/{cid}/versions/{v}/{manifest\|integrity}` | viewer | private |
| POST | `/cases/{cid}/versions/{v}/replay` | evaluator | no-store |
| GET | `/cases/{cid}/entities/{eid}/envelope` | viewer | private, immutable |
| POST | `/eval/run` (one in flight) · GET `/eval/report` | evaluator | no-store |

**Problem types:**
- `evidence-changed`
- `already-decided`
- `build-in-progress`
- `unknown-unit`
- `quote-not-verified`
- `unsupported-media`
- `payload-too-large`
- `append-only`
- `log-coverage`

**Pagination:** offset/limit over frozen versions, which never shift.

**Typed client:** `openapi-typescript` generates `schema.d.ts`, and `tsc --noEmit` is the contract test.

---

## 13. Authentication and authorisation

```
  login ──► argon2id verify (argon2-cffi) ──► 5 fails / user / 5 min → 5 min lock
        ──► opaque session id = secrets.token_urlsafe(32)  (sessions table, rotate on login,
            8 h idle expiry)  ──► Set-Cookie: HttpOnly; SameSite=Strict; Path=/ (+Secure on TLS)
  every write: X-TRACE-CSRF header + Content-Type: application/json
  bind 127.0.0.1 by default; TRACE_LAN=1 requires TLS (mkcert)

  Roles:  viewer ⊂ reviewer ⊂ senior_reviewer        ingestor (uploads/build)    evaluator (eval/replay)
```

- **Accounts:** seeded per user, with passwords generated by `secrets.token_urlsafe(9)` and written to the git-ignored `seed/credentials.local.txt`.
- **Judges** get a printed card for the `judge-reviewer` account.
- **Why passwords and not per-role PINs:** a shared PIN breaks *individual* attribution (US-3).
- **Why not JWT:** there is no signing secret to leak.

---

## 14. Frontend architecture

### 14.1 Island map

```
  Page (Astro static shell)    React island (client:only="react")   Key components
  ───────────────────────────  ───────────────────────────────────  ──────────────────────────────────
  /login                       LoginForm                            —
  /            (case list)     CaseList                             VersionBadge
  /case?id=                    CaseWorkspace                        StoryStep ×5 · ConflictCard ·
                                                                     GateTable · RegionViewer ·
                                                                     SensorChart · Timeline ·
                                                                     IntegrityBadge · DecisionPanel
  /case/expert?id=             ExpertView                           claims/comparisons tables ·
                                                                     EnvelopeView · Replay button
  /review                      ReviewQueue                          candidate list + reasons ·
                                                                     DecisionPanel
  /eval                        EvalDashboard                        P/R per fault · reliability diagram ·
                                                                     false-alarm CI
```

### 14.2 Proof rendering (no PDF bytes ever reach the browser)

```
 text_span     → server page PNG (150 dpi) + bbox overlay  AND  React text-node slicing of
                 page_text[char_start:char_end]   (no dangerouslySetInnerHTML anywhere)
 image_region  → derived, EXIF-stripped image + bbox overlay (coord_space=oriented_px) + crop
 table_cell    → server window ±25 rows, cell highlighted, scrollIntoView
 sensor_window → ECharts line (LTTB sampling) + markArea window + alarm band (med ± T*·s)
                 + lighter p5–p95 "typical" band
 every proof   → "re-checked just now" badge from POST …/recheck   (red "evidence changed" on mismatch)
```

### 14.3 Frontend rules
- `astro.config.mjs` sets `output: 'static'`, includes `@astrojs/react` and Tailwind, and sets `build.inlineStylesheets: 'never'`. FastAPI serves `dist/` from the same origin; in dev, Vite proxies `/api`.
- TanStack Query keys **always** include the version, and every card shows a version badge (T-29).
- **CSP:** `default-src 'self'; script-src 'self' <hashes>; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`. It is checked in Report-Only at h30, and Playwright runs under the enforcing policy.
- The eslint rule `react/no-danger` is an error.
- Live updates use **SSE (P1)**. WebSocket is rejected because the stream is one-way and SSE needs no extra protocol.

---

## 15. Extraction subsystem

| Modality | P0 implementation | Guards |
|---|---|---|
| Text/PDF | **pypdfium2** behind `PdfReader` (text-page `get_text_range`, per-char boxes, font size via the raw PDFium API, PNG render at 150 dpi). Offsets index the **hashed page-text artifact**. | **Hidden-text guard:** held if span < 4 pt or outside the CropBox, **or** the PNG crop has greyscale std-dev < 8 |
| Tables | CSV only (XLSX is P1) with `file, row, column, raw_value, row_sha256` | Declared `coverage_period` per log |
| Telemetry | pandas/pyarrow → Parquet per machine (a derived source) | `sensor_native` units, duplicate-ts → gap, flatline rule |
| Images | `exif_transpose` + strip → **Tesseract 5 (pinned)** `image_to_data` → re-read of the crop (8 px pad, ×2, Otsu, `--psm 7`, whitelist), labelled a **"consistency check"** | Declared physical range per gauge; a dropped decimal (69 vs. 6.9) goes to review; analogue needles are out of scope |
| LLM (P1) | Schema output, temperature 0, no tools, offline recorded cache | **Verifier:** exact NFC match with an offset map; a unique quote of ≥ 12 characters; value and unit re-derived by the rule parser; entity only from the resolver; a class mismatch goes to review |
| VLM (P1) | The independent second photo reader | Disagreement with OCR → held for review |

**Licence:** the PDF library is **pypdfium2** (Apache-2.0/BSD), decided by the user (U-1 in [`DECISIONS.md`](DECISIONS.md)). It is used from day 1, so there is no AGPL obligation. The hidden-text pixel test does not depend on the PDF library, because it runs on the rendered PNG.

**AI provider:** **Groq** (OpenAI-compatible) behind `LlmProposer`, with a Groq vision model as the P1 second reader.
- The key comes only from `.env` (`GROQ_API_KEY`).
- Groq is opt-in by config, its responses are cached for replay, and a redaction hook plus a data-egress notice run before any document text leaves the machine.
- The P0 build makes no network calls.

---

## 16. Observability
- **Logs:** `structlog` JSON with `request_id, case_id, build_id, version, config_hash, stage`. **Document text, quotes and OCR text are never logged.**
- **Per-stage `ms` and counters** are stored on the `builds` row and shown in the expert view. This proves NFR-7 on screen. Counters cover claims by modality, held items, gaps, rejected quotes, re-check mismatches, stale builds, 409s and lockouts.
- Stage names equal the future OpenTelemetry span names. OTel and `/metrics` are **P1**; alerting and runbooks are **P2**.

---

## 17. Testing strategy

```
  ┌──────────────────────── Playwright e2e (under enforcing CSP) ───────────────────────┐
  │ proof < 1 s · decision → card < 2 s · byte-flip → red badge · XSS fixture no dialog │
  │ every panel same version                                                            │
  ├──────────── API: tsc contract on generated types · authz (403/404) · 409 race ──────┤
  │ hostile corpus ×7: bomb PNG, HTML-as-PDF, SVG, traversal name, white-text PDF,      │
  │ EXIF-6 photo, XSS text                                                              │
  ├──────────── Golden: Demos 0–6 from seed → outcomes, check tables, COMPUTED numbers, │
  │ manifest_hash (pre-commit from h16)                                                 │
  ├──────────── Hypothesis properties ──────────────────────────────────────────────────┤
  │ gate symmetry · totality (exactly 1 of 4) · NEVER-AVERAGE · unit round-trip ·       │
  │ unknown unit never converts · half-open overlap commutes · GAP MONOTONICITY         │
  │ (deleting readings never moves toward "agree") · hash-chain 1-byte detection        │
  ├──────────── Evaluation hygiene ─────────────────────────────────────────────────────┤
  │ seeded injector, dev/holdout disjoint · config hash PUSHED before holdout run ·     │
  │ ≥30 % faults by a non-builder · quiet-day false-alarm ≤ 5 % on ≥200 machine-days    │
  │ (Wilson CI) · ECE/Brier with bootstrap CI + bin counts · baselines computed         │
  └─────────────────────────────────────────────────────────────────────────────────────┘
```

Every threat in [`HARDENING.md`](HARDENING.md) names its test.

---

## 18. Deployment (hackathon tier)

```
  Dockerfile (multi-stage)
   stage 1  node:<pinned>   npm ci  →  astro build  →  dist/
   stage 2  python:3.11-slim@sha256:<digest>  + tesseract-ocr + tesseract-ocr-eng (pinned)
            uv sync --frozen  ·  COPY dist/  ·  USER trace (non-root)  ·  read-only rootfs
            volume: /app/data       network: none required       ENV PYTHONHASHSEED=0
  run:      docker run -p 127.0.0.1:8000:8000 -v trace-data:/app/data trace:<git-sha>
  fallback: uv run trace-api   (native Windows: documented "no memory cap")
  demo:     make demo  → seed users, ingest seed/, build Demos 0–6, print manifest hashes
            two laptops, pre-built cases, recorded backup video, anchors pushed at h35
```

---

## 19. Scale path: hackathon → production

```
 HACKATHON (built)                         PRODUCTION (planned; same trace_core)        TRIGGER
 ────────────────────────────────────────  ───────────────────────────────────────────  ────────────────────
 Browser → FastAPI (static + API)          Browser → CDN edge (authorised; cache key    1M readers
                                             (tenant, case, version); never `public`)
                                           → Gateway (OIDC, per-tenant limits)          multi-tenant
 FastAPI read routes + LRU snapshots       Stateless read tier ×N (~75 at peak) + Redis read QPS
 Build child process                       Temporal workflows → worker pools            paid OCR/VLM/LLM
                                             (stage fns = activities; GPU OCR pool)       need retries
 SQLite + triggers                         Postgres + same triggers + REVOKE + RLS      >2 writers/case
                                             + read replicas                             or multi-host
 FS blob store                             S3 Object Lock                               multi-host
 (none)                                    Transactional outbox → LISTEN/NOTIFY →       live updates
                                             snapshot builder + SSE fan-out
 Fake/recorded LLM                         AI gateway (cache, spend caps, failover)     real LLM use
 ───────── planned ONLY IF ───────────────────────────────────────────────────────────────────────
 Kafka         ≥ 3 independent consumers of the change log
 Citus         multi-TB per-tenant write volume
 TimescaleDB   real-time sensor ingest (not batch CSV)
 Cross-cutting: per-tenant keys + crypto-shredding (erasure vs append-only), signed images (cosign),
                SBOM, OTel traces + alerts + runbooks, backups + second region, canary releases
```

**Why this survives scrutiny:** a million *readers* is a cache problem, and immutable versions are perfectly cacheable. Every write-side component is tied to the trigger that would justify it, so nothing is there for show.

**Rough sizing:**
- 1M users at 1 request per 20 s is about 50k RPS.
- About 85% of that is served at the edge, leaving about 7.5k RPS at the origin.
- About 80% of the origin load is served from Redis, leaving about 1.5k RPS for the database and read tier.
- That works out to about 75 read pods with headroom.

---

## 20. Performance budget (NFR-7)

| Path | Budget | How it is met |
|---|---|---|
| Case build | < 60 s | Cached extraction artifacts; telemetry Parquet; only the case window is processed; the child process does not block the API |
| Proof view | < 1 s | Pointer-level hashes (no full-file re-hash); cached PNG pages; ±25-row table window; LTTB chart sampling |
| Decision → updated card | < 2 s | Synchronous re-run of link → gate → trust → snapshot over cached claims, inside one `BEGIN IMMEDIATE` |
| Versioned reads | ~ms | Immutable JSON snapshots in an LRU, `ETag` = manifest_hash, `304` on revalidation |

Per-stage timings are stored on every build and shown in the expert view, and Playwright asserts the < 1 s and < 2 s budgets.

---

## 21. 36-hour team plan

Each person works 30.5 h, for **122 h in total, including a 10 h buffer**. The correctness floor is about 13 h and the security floor about 8.5 h. The full ledger is in [`debate/r3_judge.md` Part 3](debate/r3_judge.md).

```
 h0 ─ h1 ──── h8 ───── h10 ─────── h16 ──────────────── h26 ─────── h30 ──── h33 ── h35 ─ h36
 │    │       │        │           │                    │           │        │      │
 │    │       │        │           │                    │           │        │      └ anchors pushed
 │    │       │        │           │                    │           │        └ rehearsal
 │    │       │        │           │                    │           └ freeze; CSP Report-Only check
 │    │       │        │           │                    └ P1 only if Demos 0–6 goldens green
 │    │       │        │           └ eval track starts; golden test in pre-commit
 │    │       │        └ walking skeleton: 1 text + 1 sensor claim → gate → card on screen
 │    │       └ Pydantic schemas frozen; TS types generated
 │    └ Tesseract smoke test on every laptop
 └ h0 data reality check: does M-21 on 14 Mar exceed T*? measure quiet-day counts

 A  Ingest + platform security : PDF/text, hidden-text, CSV, OCR+re-read, uploads, build child, auth
 B  Engine + correctness floor : telemetry, conformal envelopes, gaps, units, resolver, time, gate, trust
 C  Frontend                   : Astro/Tailwind, story, conflict card, RegionViewer, chart, timeline,
                                 review, expert, CSP
 D  Data, store, API, eval     : seed data, SQLite+triggers, chain/anchors/replay, API, injector,
                                 baselines, metrics
 Stretch order (if green at h26): SSE → Ed25519 (off-box key) → VLM 2nd reader → recalibration →
                                  load bins → LLM + verifier → XLSX
```

---

## 22. Requirements traceability

| PRD item | Design element |
|---|---|
| D1 engine for text, image and structured/time-series data | §6 READ stage, §15 |
| D2 unified state schema | §8, `/versions/{v}/state` |
| D3 ClaimRecord, extracted vs. inferred | §8.1 `claims.claim_type`, `derived_from` |
| D4 evidence pointers for every modality | §8.1 pointer kinds, §9 per-pointer hashes, §14.2 |
| D5 linking, timeline, conflicts | §6 NORMALISE, §7 |
| D6 confidence accuracy + calibration | §7.2 confidence, §17 eval hygiene (ECE/Brier CI, accuracy per bin) |
| D7 inspection interface | §14 |
| D8 demos (missing data, ambiguity, disagreement) | §17 goldens for Demos 0–6 |
| FR-ING-1…6 | §15, §6 |
| FR-NORM-1…5 | §6, §7.2 (`sensor_native`, conformal envelopes, gaps) |
| FR-GATE-1…5 | §7.1 |
| FR-TRUST-1…5 | §6 SCORE, §7.2 confidence, §11 review |
| FR-EVID-1…4 | §8, §9 |
| FR-UI-1…7 | §14 (FR-UI-7 is now SSE, P1) |
| FR-LOOP-1/2 | §11, §17 |
| NFR-1…3 traceability, integrity, immutability | §8.2, §9 |
| NFR-4 determinism | §9 |
| NFR-5 explainability | §7.1 (stored check results), §16 |
| NFR-6 no silent fusion | §7 never-average and the duplicate-ts rule; §17 property test |
| NFR-7 performance | §20 |
| NFR-8 production performance | §19 |
| NFR-9 privacy/tenancy | §13, §19 cross-cutting, [`HARDENING.md`](HARDENING.md) T-35/T-36 |
| NFR-10/11 usability, accessibility | §14 (text labels on badges, five-step story) |
| NFR-12 honest confidence | "uncalibrated" label, §17 |

---

## 23. Judge Q&A: the ten hardest questions

1. **"Pick a random quiet day. Does 'ran normally' say 'disagree'?"**
   Rarely, by construction. T\* is the conformal 95% quantile of the machine's own daily max-z, so quiet-day false alarms are ≤ 5% across all channels and hours together. The measured holdout rate is shown with its Wilson CI.
2. **"Is the alarm band computed or typed in?"**
   Computed. The Envelope view shows the quiet days with the reason each qualified, med/MAD, T\*, n and `envelope_id`. **Verify replay** produces the same hash, and a grep finds no demo literals in the engine.
3. **"Four hours are missing and the spike was in them."**
   The result is "We can't tell (partial: 4 h missing)". A ∀ claim agrees only with 100% coverage, and a property test proves that deleting readings never moves an outcome toward "agree".
4. **"What unit is the MS vibration channel?"**
   It is undocumented, so we never convert it and compare it only with the same series. That is why the gauge reading in bar is "can't be compared" with telemetry.
5. **"Your OCR re-read uses the same engine. How is that verification?"**
   It isn't verification, and we label it a consistency check. Implausible values go to review. The independent second reader (VLM) is P1.
6. **"Can I forge a decision as 'Senior Engineer'?"**
   No. Identity comes from an argon2 session, and a `reviewer` field returns 422. The decision records the evidence hash the reviewer was shown and is part of the hash chain. Two reviewers racing get one success and one 409.
7. **"Tamper with the PDF now."**
   A byte flip turns the proof badge red ("evidence changed"). A SQL UPDATE aborts at the trigger. Editing with the trigger dropped fails chain verification, and the root matches the anchor pushed to our remote before this session.
8. **"You wrote both the faults and the rules. Isn't P/R circular?"**
   We limit it. Seeds are split into dev and holdout, the config hash was pushed before the holdout run, and an outsider wrote at least 30% of the faults. We publish baselines, per-fault failures and ECE with its CI.
9. **"Same inputs on two laptops: identical?"**
   Replay from stored artifacts is byte-identical: content IDs, JCS hashing, and a manifest that records the code SHA, lockfile and Tesseract version. Fresh OCR is reproducible inside the pinned image.
10. **"How does this serve a million readers?"**
    Versions are immutable, so readers are served from an authorised edge cache keyed by (tenant, case, version), and the engine runs unchanged in workers. Kafka and Citus are planned only if write volume demands them, with an explicit trigger for each.
