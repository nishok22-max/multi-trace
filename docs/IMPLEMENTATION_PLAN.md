# TRACE — Implementation Plan (MVP → Plant-Pilot Product)

*Every fact has an address. Every conflict stays visible.*

| Field | Value |
|---|---|
| Version | 1.0 (binding for the build) |
| Date | 2026-11-20 |
| Inputs | [`TRACE_PRD.md`](TRACE_PRD.md) v1.2 · [`system-design/`](system-design/README.md) · [`TEST_PLAN.md`](TEST_PLAN.md) |
| Stack | Python 3.11 · FastAPI · Pydantic v2 · SQLite (MVP) → Postgres (pilot) · pypdfium2 · Tesseract 5 · Astro (static) + Tailwind + React islands · Groq (opt-in, P1+) |
| Team (MVP) | **A** Ingest + platform security · **B** Engine + correctness floor · **C** Frontend + e2e · **D** Data, store, API, eval |

## How this plan was produced
```
 Technician ──draft──► QA-1 (correctness/architecture: 3 BLOCKER, 23 MAJOR, 22 MINOR)
     ▲                 QA-2 (security/perf/ops:      3 BLOCKER, 15 MAJOR, 14 MINOR)
     │                          │ 80 findings
     └──── revision ◄───────────┘   78 accepted (4 re-scoped) · 2 rebutted · all 6 BLOCKERs fixed
                 │
                 ▼
             Tester ──► TEST_PLAN.md (acceptance matrix, goldens, perf, security, gates)
```
Raw records: [`reviews/technician_plan.md`](reviews/technician_plan.md) ·
[`reviews/qa1_review.md`](reviews/qa1_review.md) · [`reviews/qa2_review.md`](reviews/qa2_review.md) ·
[`reviews/technician_revision.md`](reviews/technician_revision.md) (contains the 80-row disposition table) ·
[`reviews/tester_plan.md`](reviews/tester_plan.md).

**The six blockers and their fixes:**
| Blocker | Fix in this plan |
|---|---|
| Q1-01 Holdout data used during development | A dev-only false-alarm test runs in pre-commit. The holdout test runs **once, at h31**, through `make eval-holdout` |
| Q1-02 False-alarm rate measured on the same quiet days that set T\* (≤ 5% by construction) | Leave-block-out: each tested day ±3 d is excluded from calibration, and the number is reported on **holdout machines** |
| Q1-22 Hidden text checked per span, so visible "had issues" plus a hidden "no " reads as "no issues" | A **per-character** visibility test: remove the text object, re-render, diff the pixels. Any invisible char holds the whole span |
| Q2-01 Groq key leak (T-39) not covered; secrets could be baked into the image | `.dockerignore` and `.gitignore` deny `.env`, credentials, `data/` and DBs; gitleaks; log scrubbing; sentinel test `test_no_secret_in_logs_or_responses` |
| Q2-02 Untrusted PDFs parsed in the API process | Pages are rendered **only in the build child**; import-linter bans pdfium, Tesseract and PIL from `trace_api`; the API serves cached PNGs only |
| Q2-03 Upload body read in full before the cap | ASGI byte-counting middleware with a streaming multipart parser, enforced **before** the body is read |

**Decisions taken at synthesis** (details in [`TEST_PLAN.md`](TEST_PLAN.md) §0):
- **Goldens pin a `semantic_root`**, a manifest with the engine, lockfile and binary versions set to `"golden"`. The real chained `manifest_hash` is still anchored and verified.
- **The 13-file hostile corpus** is binding.

## Roadmap at a glance
```
 MVP (36 h, 4 people, 122 h incl. 5.25 h buffer)
 h0 ──M0── h2.5 ──M1── h8 ──M2── h10 ──────M3────── h24 ──M4── h28 ──M5── h31 ──M6── h36
   setup +    contracts   walking       full ingest +          UI       eval +    freeze, holdout h31,
   h0 reality frozen      skeleton      engine + goldens       complete hardening rehearsal, anchors h35
   check      (CCR after) (C-17→S-88    (correctness floor)    (h26 stretch gate:
              + CSP spike  → card)                              only if goldens green)

 PLANT PILOT (~25 weeks, single tenant, on-prem VM)
 wk 1───4  P1 Hardening + stretch: Groq LLM proposer + verifier, Groq VLM 2nd reader, SSE, Ed25519,
           calibration, load bins, XLSX, Schemathesis/fuzz/SBOM/cosign, rotated + scanned PDFs
 wk 5───9  P2 Platform: Postgres (same triggers + REVOKE), byte-exact migration, MinIO Object Lock,
           OIDC, job table (no Temporal: ADR-16), outbox + SSE, pgBackRest, Prometheus/Grafana, egress proxy
 wk 9──13  P3 Onboarding: asset register, historian tags, real logs (A8), datasheet tolerances (A5),
           readiness check A1–A8, labeller programme (κ ≥ 0.7), plant phrase ontology, runbooks
 wk 13─25  P4 Operations + go/no-go at week 12 of ops (7 measurable criteria)
 later     P5 Optional multi-tenant SaaS (outline only)
```

## Coding strategy (summary; full detail in §A)
| Goal | Practices |
|---|---|
| **Fast delivery** | Contracts first (frozen at h8, then changes only through a Contract Change Request); walking skeleton at h10; fakes before adapters behind `Protocol` ports with shared contract tests; seed bytes committed once; trunk-based, PRs under 300 lines; `make` one-liners that also work from PowerShell |
| **Low latency** | Pre-serialised orjson snapshots in an LRU; ETag/304; projections precomputed at snapshot time; pages pre-rendered in the build child; pyarrow predicate reads; decision re-run computed *outside* the write lock and committed in under 50 ms; perf tests on the image and native Windows |
| **Reliable** | Pure deterministic core; content-addressed IDs + JCS; every reader output cached (a replay miss is an error); a hardened killable build child (allowlisted env, self-deadline, `killpg`, heartbeat sweep); fail closed; goldens also under random hash seeds |
| **Modular** | Hexagonal core; import-linter contracts (core forbids I/O modules; the API forbids parsers); one `ConfigBundle`; adapters swap for the pilot (SQLite→Postgres, FS→MinIO, fake→Groq) without touching the core |
| **Secure** | Floor S1–S11; no untrusted decoding in the API; streaming upload caps; argon2id + hashed opaque sessions + CSRF + Origin checks; strict CSP header; secrets only in `.env`, with gitleaks and log scrubbing; zero network by default (pytest-socket, `--network none`); supply-chain pins and audit |

---

# Detailed plan

## 0. Binding user decisions

| # | Decision | Effect |
|---|---|---|
| U-A | The product after the MVP is a **plant pilot**: one plant, ~40 machines, single tenant, VM/on-prem, with Postgres (same triggers plus REVOKE), MinIO object lock, OIDC, LLM/VLM, backups and monitoring. SaaS is P5, an outline only. | §E |
| U-B | **pypdfium2** from h0 (ADR-06). There is no AGPL caveat. | §D.2 |
| U-C | Docker Desktop (WSL2) for the demo image; native `uv`/`npm` on Windows for dev loops. | §A.7 |
| U-D (U-3) | **Groq** behind `LlmProposer`/`VlmReader` in P1 and the pilot. The MVP makes zero network calls. Groq is opt-in, cached, key only from `.env`, with an egress notice and a redaction hook. Covers T-39 and T-40. | §A.5, §E P1-03/04 |
| U-E | Python 3.11 + FastAPI + Pydantic v2; Astro static + Tailwind + React islands. | — |

All judge verdicts stand unchanged.

---

## A. Coding strategy

### A.1 Fast delivery
1. **Contracts first.**
   - B owns the models (B-01, 3.0 h) and A owns ports, fakes and port contract tests (A-01b, 1.25 h). D owns `ConfigBundle` inside D-03.
   - B drafts the models and port signatures at h3. Freeze tag **`contracts-v1` at h8**, exporting `schemas/*.json`, `openapi.json` and `schema.d.ts`. Fakes plus contract tests follow by h8.5.
   - After h8, any change needs a **Contract Change Request**: B approves, then `make contracts`. `make contracts-check` runs in pre-commit (`git diff --exit-code`).
2. **Walking skeleton at h10.** C-17 (text) + S-88 (sensor, real envelope) → gate → snapshot → API → card in the browser.
3. **Fakes first.**
   - The fakes are `FakePdfReader`, `FakeOcr`, `FakeTelemetryReader`, `FixedClock`, `MemClaimStore`, `MemBlobStore`, `FakeLlm` and `DictExtractionCache`.
   - Real adapters pass the same parametrised contract tests (`tests/unit/ports/test_<port>_contract.py`).
4. **Oracle, then goldens.** B's `test_conformal_oracle.py` holds hand-computed k, pooling branches, MAD = 0 and p-values, reviewed by D. Only when it is green may `make golden-bless` (`CONFIRM=1`, diff printed) pin the computed demo values.
5. **Seeds are bytes, not scripts on each laptop.** `tools/gen_seed_*` runs once **inside the image** (reportlab `invariant=1`, vendored DejaVu TTF, fixed RNG seeds). The bytes plus `seed/SHA256SUMS` are committed, and `make seed` only verifies them.
6. **Trunk-based development.**
   - Branches live under 4 h and PRs stay under about 300 lines.
   - Review rules: B's floor PRs are reviewed by D, and A's security PRs by B.
   - Standups at h2, h6, h10, h14, h20, h24, h28 and h32.
   - A task 50% over its estimate is escalated, and the buffer owner decides.
   - **h6 pypdfium2 checkpoint:** offsets, boxes and render round-trip must be green, otherwise C's reserve is pulled to A.
7. **Stretch is flag-gated** (`TRACE_FEATURE_SSE`, `TRACE_LLM_MODE=off`, `TRACE_VLM_MODE=off`, `TRACE_LOAD_BINS=0`). It starts only at the h26 gate and only from buffer.

### A.2 Low latency (NFR-7)
- **Serialisation:** `ORJSONResponse`, with snapshots stored and served as pre-serialised bytes.
- **`SnapshotLRU`** is keyed `(case, v, view)`, capped at 256 entries or 64 MB, and filled after a sha256 check.
- **HTTP caching:** `ETag = "<manifest_hash>"`, and `If-None-Match` returns 304 first. Versioned JSON is `private, max-age=31536000, immutable` with `Vary: Cookie`. `latest`, `recheck` and writes are `no-store`.
- **Projections precomputed in `snapshot()`:** state, story, timeline and review.
- **Rendering happens only in the build child** (Q2-02):
  - every page or crop that a claim or review item cites is pre-rendered;
  - non-cited pages are not rendered at all;
  - `compress_level=1`;
  - the hidden-text std-dev comes from `bitmap.to_numpy()`.

  The API serves cached PNGs, and a miss returns `404 render-missing`.
- **Recheck** (Q1-25 / Q2-11), with no parsing of untrusted bytes in the API:
  1. stream the source sha256 (≤ 25 MB documents; telemetry cites the derived Parquet partition);
  2. check the artifact sha;
  3. check that the artifact's cache `input_sha` == source sha;
  4. re-derive the value: the pure rule parser on `page_text[s:e]`, the CSV line at its stored byte offset re-parsed, the Parquet partition re-sliced with the statistic recomputed, or the crop re-hashed with the cached OCR value compared.

  Results are coalesced per `(claim, source)` for 10 s, with a limit of 30 per minute per session.
- **Telemetry:** `TelemetryReader` uses `pyarrow.dataset` predicates. Envelope learning reads the full-year partitions of the machine and its pool. Proof and recheck read only the window.
- **Decision re-run, compute-then-commit** (Q2-10):
  1. read the parent version;
  2. compute v+1 in the threadpool (link → gate → trust → snapshot, over cached claims and attribute-group sweep pairs);
  3. a short `BEGIN IMMEDIATE` re-checks latest == parent, the item is undecided and the evidence hash still matches, then inserts and commits (< 50 ms held);
  4. at most 3 recomputes if latest has moved.
- **SQLite:** `isolation_level=None` everywhere, with an explicit `BEGIN IMMEDIATE` for every write. `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; foreign_keys=ON; mmap_size=64MiB` (the smaller mmap is RLIMIT-friendly). The child commits every record in one final transaction.
- **Budgets are tested** in `tests/perf/`:
  - `test_build_demo_all_under_60s_image`, which records `spawn_import_ms`;
  - `test_proof_evidence_p95_under_400ms_cold_lru`;
  - `test_decision_rerun_p95_under_1500ms`;
  - `test_versioned_read_p95_under_50ms_warm`;
  - `test_recheck_under_300ms`.

  They run on the image and on native Windows at the M3 and M4 exits and in D-11, and write `data/perf_report.json` with the reference laptop specs. Playwright asserts medians of 5 runs.

### A.3 Reliability
- **Build child:**
  - spawn target `trace_worker.build_runner`, which never imports `trace_api`;
  - the env is built from an **allowlist** (no `GROQ_API_KEY`, and `ARROW_DEFAULT_MEMORY_POOL=system`, `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MALLOC_ARENA_MAX=2` set before imports);
  - `RLIMIT_AS` = the peak VM measured in smoke + 1 GiB (Linux);
  - its own process group;
  - a self-deadline thread (`os._exit(124)` at 180 s);
  - a parent-liveness pipe (exit on EOF);
  - the parent watchdog sends `killpg` on timeout, which also kills `tesseract` grandchildren;
  - a heartbeat every 5 s and a sweep **every 30 s** (stale > 60 s → `failed_stale`);
  - `exitcode` checked (OOM → `failed_resource`).
- **Container:** `--memory 3g --pids-limit 256 --read-only --tmpfs /tmp:size=128m --cap-drop ALL --security-opt no-new-privileges`.
- **Idempotency:** `build_key` is unique where `status IN (queued, running, done)`, so failed builds can be retried. Blob `put` onto an existing hash is a no-op.
- **Fail closed.** Unknown becomes "can't compare" or "can't tell". `assert_never` on every enum match.
- **Determinism:**
  - content-addressed IDs (§C.1a);
  - JCS through `canonical.py` (Decimal quantise to 6 dp with ROUND_HALF_EVEN, `-0.0`→`0`, NaN/Inf rejected);
  - explicit sorts and `quantile(method="linear")`;
  - dateparser with a fixed base, order and timezone;
  - `PYTHONTZPATH=` (empty) with tzdata from the wheel, its version in the manifest;
  - **every** reader output cached, including `PageText`;
  - a replay miss is an error;
  - goldens also run under `PYTHONHASHSEED=random`;
  - `snapshot_sha256` excludes wall-clock fields.
- **Verification:** `/integrity` verifies **stored bytes against stored hashes** and walks the chain. It never re-derives objects to verify them, and `canon_version` is frozen (Q2-27).
- **Probes:** `/healthz` and `/readyz` (DB writable, blob dir writable, Tesseract present, free disk > 1 GB).

### A.4 Modularity — `.importlinter`
1. `trace_core` is independent of `trace_adapters`, `trace_api`, `trace_worker` and `trace_eval`.
2. **Forbidden external modules in `trace_core`:** `sqlite3, pyarrow.dataset, pyarrow.parquet, pypdfium2, pytesseract, PIL, openai, httpx, socket, subprocess, requests`.
3. Layers run `trace_api` → `trace_worker` → `trace_adapters` → `trace_core`. In addition, **`trace_worker` must not import `trace_api`**.
4. **`trace_api` must not import `pypdfium2`, `pytesseract`, `PIL`, `trace_adapters.pdfium_reader` or `trace_adapters.tesseract_ocr`** (Q2-02). This is also checked at runtime by `test_api_never_imports_pdfium`.
5. `trace_eval` must not import `trace_api`.
6. `trace_core.compare` must not import `trace_core.read`.

Config is one `ConfigBundle` (`extra="forbid"`), and `config_hash = sha256(JCS)`. Each resource has its own router. Stage names = OTel span names = future activity names.

### A.5 Security
- **Floor S1–S11** (task map in §H.5).
- **No untrusted decoding in the API** (Q2-02). **Streaming upload caps** in ASGI middleware (Q2-03).
- **Ruff:** `S`, `DTZ`, and `TID251` banned APIs in core (`datetime.now`, `time.time`, `os.environ`, `open`, `requests`). `numpy.mean/average` and `statistics.mean` are banned outside `read/sensor.py`. In addition, the **AST check `tools/check_no_mean.py`** covers `.mean(`, `pivot_table(` without an explicit non-mean `aggfunc`, and `.resample(` across core and adapters.
- **Secrets (T-39):**
  - `pydantic-settings` `SecretStr`;
  - `.env` and `.env.*` (except `.env.example`) in `.gitignore` **and** `.dockerignore`;
  - `.dockerignore` also denies `seed/credentials.local.txt`, `data/`, `**/*.db*`, `.git` and `**/__pycache__`;
  - gitleaks pre-commit with a `gsk_[A-Za-z0-9]{20,}` rule;
  - a structlog processor drops `quote`, `text`, `page_text`, `ocr_text`, `prompt`, `completion`, `authorization`, `password` and `cookie`, and regex-scrubs key patterns;
  - `show_locals=False`;
  - the `openai`, `httpx` and `httpcore` loggers are set to WARNING;
  - a custom `RequestValidationError` handler strips `input` and `ctx`;
  - problem bodies never carry exception text;
  - test: `test_no_secret_in_logs_or_responses`.
- **Egress (T-40, P0 part):** the default config is `TRACE_LLM_MODE=off` and `TRACE_VLM_MODE=off`, and the Groq package is never imported. Test: `test_groq_disabled_by_default_no_egress` (pytest-socket). The whole MVP suite also runs in Docker with `--network none` (`test_network_off_build_succeeds`).
- **Auth hardening:**
  - argon2id with `t=2, m=19456 KiB, p=1`, verified in the threadpool under `Semaphore(4)`, with a dummy hash for unknown users;
  - session tokens stored as sha256, 8 h idle and 12 h absolute expiry, `__Host-` name on TLS;
  - CSRF header and JSON rules on every write, including login;
  - Origin/`Sec-Fetch-Site` check;
  - `TrustedHostMiddleware`;
  - loopback binding in compose and native, and `TRACE_LAN=1` without TLS refuses to start.
- **HTTP headers** come from FastAPI on every HTML response:
  - the CSP **header**, built from `dist/csp-hashes.json`: `default-src 'self'; script-src 'self' <hashes>; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`;
  - `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin` and `Permissions-Policy`.

  Originals are served as `attachment; filename="<source_id>.<ext>"`, octet-stream, nosniff, `CSP: sandbox` and CORP same-origin.
- **Frontend:** `react/no-danger` is an error, and `no-restricted-syntax` bans string ECharts `formatter` returns unless they are wrapped in `encodeHTML`.
- **Supply chain (T-37):** lockfiles, with `test_lockfiles_in_sync` in pre-commit; `npm ci --ignore-scripts`; digest-pinned bases; apt via `snapshot.debian.org/<date>`; a one-shot `pip-audit`, `npm audit` and `trivy` at M5.

### A.6 Typing strictness
- `mypy --strict` with the pydantic plugin on core, api and worker.
- Models are frozen with `extra="forbid"`, and core-internal models are also `strict`.
- ID types use regex constraints (which also back T-19).
- TypeScript runs with `strict`, `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`, and `tsc --noEmit` is the contract test.
- `DecisionRequest.choice` is a discriminated union per review type.

### A.7 Windows and Docker
- **`.gitattributes`:** `* text=auto eol=lf`; `seed/** -text`; `tests/**/fixtures/** -text`; `*.pdf *.png *.jpg *.jpeg *.parquet binary`.
- **Setup:** `git config core.longpaths true` plus the Windows long-path setting, both checked by `make smoke`. `tzdata` with `PYTHONTZPATH=`.
- **Tesseract on Windows:** `winget install UB-Mannheim.TesseractOCR` and `TRACE_TESSERACT_CMD`. Native runs use **replay** mode against `seed/cache/`, and `make record-cache` runs only in the image.
- **Smoke checks:** `make smoke` checks the pinned versions (image). `make smoke --native` checks only that Tesseract is present and replay mode is on, and **rejects** a DB on `9p`/`drvfs`/`grpcfuse` or a `\\wsl…` path.
- **Docker Desktop:** clone inside the WSL2 filesystem. `data/` is a **named volume**, never bind-mounted from `C:\`.
- **Dev server:** `uvicorn --reload --reload-dir backend --reload-exclude 'data/*' --reload-exclude '.venv/*'`.
- **Spawn and memory caps:** spawn is native on Windows. RLIMIT is skipped with a one-time "no memory cap" log line (the Job Object is P1-12).
- **Defender:** a README note, measured with and without real-time scanning, never changed automatically.
- Makefile targets are one-liners around `uv run python -m tools.<task>` or `npm run`, so they also work from PowerShell.

---

## B. Repository scaffold, Makefile, dependencies

### B.1 Tree
```
trace/
├── .gitattributes .gitignore .dockerignore .editorconfig .env.example .pre-commit-config.yaml .importlinter
│   # .env.example: GROQ_API_KEY=  TRACE_LLM_MODE=off  TRACE_VLM_MODE=off  TRACE_LLM_EGRESS_ACK=false
│   #   TRACE_GROQ_BASE_URL=https://api.groq.com/openai/v1  TRACE_GROQ_TEXT_MODEL=  TRACE_GROQ_VISION_MODEL=
│   #   TRACE_TESSERACT_CMD=  TRACE_LAN=0  TRACE_DATA_DIR=./data  TRACE_PUBLIC_HOST=localhost
├── Makefile  Dockerfile  compose.demo.yml   (ports "127.0.0.1:8000:8000", read-only, tmpfs, cap_drop ALL)
├── LICENSE (Apache-2.0)  THIRD_PARTY_NOTICES.md (pypdfium2/PDFium BSD-3/Apache-2.0, Tesseract, DejaVu, MS dataset)
├── backend/
│   ├── pyproject.toml  uv.lock
│   ├── trace_core/
│   │   ├── models/ base.py time.py evidence.py claims.py records.py case.py config.py api_io.py eval.py
│   │   ├── ports.py canonical.py ids.py errors.py build.py rerun.py
│   │   ├── read/ text_rules.py numunit.py dates.py mentions.py textnorm.py text.py hidden_text.py
│   │   │         table.py sensor.py image.py llm_verify.py(P1)
│   │   ├── normalise/ units.py entities.py time.py envelopes.py gaps.py sensor_state.py
│   │   ├── review/ holds.py status.py escalation.py
│   │   ├── compare/ groups.py pairs.py gate.py quantifiers.py tolerance.py conflicts.py
│   │   ├── score/ confidence.py independence.py calibration.py(P1)
│   │   └── snapshot/ records.py manifest.py projections.py   (state, story, timeline, review)
│   ├── trace_adapters/
│   │   ├── sqlite/ store.py migrate.py   blob_fs.py  pdfium_reader.py  tesseract_ocr.py  telemetry_parquet.py
│   │   ├── telemetry_split.py extraction_cache.py clock.py llm_fake.py redactor.py
│   │   └── groq/ llm_groq.py vlm_groq.py   (P1; never imported when modes are off)
│   ├── trace_api/
│   │   ├── main.py settings.py deps.py problems.py logging.py
│   │   ├── security/ sessions.py passwords.py csrf.py origin.py csp.py headers.py upload_asgi.py magic.py
│   │   ├── routers/ health auth cases sources builds versions claims review eval
│   │   └── services/ build_service.py decision_service.py snapshot_lru.py evidence_render.py recheck.py
│   ├── trace_worker/ build_runner.py child_guard.py sweep.py
│   ├── trace_eval/ injector.py faults/ baselines/{tfidf,fusion,nogate}.py metrics.py protocol.py holdout.py
│   │               report.py label_kit.py
│   ├── tools/ smoke.py h0_reality.py gen_seed_pdfs.py gen_gauges.py fetch_dataset.py seed_users.py seed_build.py
│   │          export_contracts.py anchor.py record_cache.py check_no_mean.py verify_seed.py
│   ├── config/ case.yaml ontology.yaml phrases.yaml aliases.yaml tolerances.yaml gauges.yaml shifts.yaml
│   │           envelope.yaml gate.yaml llm.yaml
│   ├── migrations/sqlite/ 001_schema.sql 002_append_only_triggers.sql 003_indexes.sql 004_status_views.sql
│   └── tests/ unit/ ports/ golden/ properties/ hostile_corpus/ authz/ api/ perf/ eval/ fixtures/
├── frontend/ package.json package-lock.json astro.config.mjs tsconfig.json eslint.config.js
│   ├── scripts/csp-hash.mjs      (always writes dist/csp-hashes.json)
│   └── src/ pages/ islands/ components/ lib/{api,query,geom}/ styles/
├── e2e/ playwright.config.ts specs/{proof,decision,tamper,xss,versions}.spec.ts
├── seed/ dataset/(fetched) authored/{reports,photos,logs} fonts/DejaVuSans.ttf labels.yaml cache/
│         faults/{dev,holdout}/ SHA256SUMS credentials.local.txt(ignored)
├── schemas/  data/(volume, ignored)  anchors/demo_roots.txt
└── ops/ (P2) compose.pilot.yml caddy/ squid/ prometheus/ grafana/ alertmanager/ pgbackrest/
```

### B.2 Makefile targets
| Target | Does |
|---|---|
| `setup` | `uv sync`, `npm ci --ignore-scripts`, `pre-commit install`, `git config core.longpaths true` |
| `smoke` / `smoke-native` | Image: pinned Tesseract, pypdfium2 char/box/render round-trip, tz, trigger abort, peak VM measured. Native: tool presence, replay mode, DB filesystem check |
| `h0` | M-21 / 14 Mar T_D vs T\*, error rows, quiet-day histogram → `data/h0_report.json` |
| `contracts` / `contracts-check` | Export and regenerate; fail on diff |
| `lint` `type` `imports` `nomean` | ruff+eslint / mypy+tsc / lint-imports / `check_no_mean.py` |
| `test-fast` / `test` | Unit + ports + golden / all except `holdout`, `perf` and e2e |
| `golden` / `golden-bless` / `golden-randseed` | Run / bless (oracle green + `CONFIRM=1`) / run with `PYTHONHASHSEED=random` |
| `props` `hostile` `authz` | Subsets |
| `check-perf` | `tests/perf` → `data/perf_report.json` |
| `e2e` | Playwright against the image under the enforcing CSP header |
| `check` | lint, type, imports, nomean, contracts-check, lockfiles-in-sync, test, golden-randseed |
| `seed` / `seed-gen` | Verify `SHA256SUMS` / regenerate (image only) |
| `record-cache` | Image only |
| `demo`, `replay-verify` | Build Demos 0–6; rebuild from the cache and compare hashes |
| `eval-dev` / `eval-holdout` | Holdout requires a clean tree and config, engine and lock hashes on the remote |
| `audit` | pip-audit, npm audit, trivy (M5 one-shot) |
| `anchor` | Append roots, commit, **push** |
| `image` `run-docker` `run-native` | Build; run hardened on 127.0.0.1; `uv run trace-api` on 127.0.0.1 |

### B.3 Backend dependencies (ranges; **exact pins at h0 via `uv lock`**)
| Group | Package | Range |
|---|---|---|
| runtime | fastapi | `>=0.115,<1.0` |
| | starlette (explicit) | `>=0.40` (CVE-2024-47874) |
| | uvicorn[standard] | `>=0.32,<1.0` |
| | pydantic / pydantic-settings | `>=2.9,<3` / `>=2.6,<3` |
| | orjson, structlog | `>=3.10,<4`, `>=24.4` |
| | pandas / pyarrow / numpy | `>=2.2,<3` / `>=17,<22` / `>=1.26,<3` |
| | pint, rapidfuzz | `>=0.24,<1`, `>=3.10,<4` |
| | dateparser, python-dateutil, tzdata | `>=1.2,<2`, `>=2.9`, `>=2024.2` |
| | rfc8785 | `>=0.1.4` |
| | **pypdfium2** | `>=4.30,<5` (assess v5 at h0; the version goes into the cache key) |
| | pytesseract, Pillow | `>=0.3.13`, `>=11.0,<12` |
| | argon2-cffi, python-multipart, PyYAML | `>=23.1`, `>=0.0.18`, `>=6.0.2` |
| eval | scikit-learn | `>=1.5,<2` |
| dev | pytest, pytest-xdist, pytest-cov, pytest-socket, hypothesis, httpx | `>=8.3`, `>=3.6`, `>=5`, `>=0.7`, `>=6.112`, `>=0.27` |
| | mypy, ruff, import-linter, pre-commit, reportlab | `>=1.13`, `>=0.7`, `>=2.1`, `>=4.0`, `>=4.2` |
| llm (P1 extra) | openai (OpenAI-compatible client → Groq) | `>=1.50,<2` |
| pilot (P2 extra) | psycopg[binary,pool], boto3, authlib, opentelemetry-sdk, opentelemetry-instrumentation-fastapi, prometheus-client | `>=3.2`, `>=1.35`, `>=1.3`, `>=1.27`, `>=0.48b0`, `>=0.21` |
| P1 tools | schemathesis, pip-audit, cyclonedx-bom, openpyxl, defusedxml | `>=3.36`, `>=2.7`, `>=5`, `>=3.1.5`, `>=0.7.1` |

**System pins:**
- `python:3.11-slim-bookworm@sha256:<digest>`;
- apt from `snapshot.debian.org/archive/debian/<date>`: `tesseract-ocr=5.3.0-*` and `tesseract-ocr-eng` (exact strings recorded in the manifest and cache key);
- `node:20-bookworm-slim@sha256:<digest>`.

### B.4 Frontend dependencies (`package-lock.json` at h0, `npm ci --ignore-scripts`)
| Package | Range |
|---|---|
| astro | `^5.9` |
| @astrojs/react | `^4.2` |
| react, react-dom | `^18.3.1` |
| tailwindcss, @tailwindcss/vite | `^4.0` |
| @tanstack/react-query | `^5.59` |
| echarts, echarts-for-react | `^5.5`, `^3.0.2` |
| openapi-fetch, openapi-typescript | `^0.13`, `^7.4` |
| typescript | `^5.6` |
| eslint, typescript-eslint, eslint-plugin-react, eslint-plugin-react-hooks | `^9`, `^8`, `^7.37`, `^5` |
| vitest, @testing-library/react | `^2.1`, `^16` |
| @playwright/test | `^1.48` |

---

## C. Interfaces

### C.1 Core models (`frozen=True, extra="forbid"`; `UtcStr` = fixed-width `YYYY-MM-DDTHH:MM:SSZ`)
| Model | Key fields |
|---|---|
| `Interval` | `start, end` (half-open, `start < end`), `granularity: hour\|shift\|day`, `resolved_from` |
| `UnknownTime` | `granularity: Literal["unknown"]`, `reason` (no bounds) |
| `ObservedTime` | `at?, basis: document_date\|sensor_timestamp\|ingest_time` (never `file_timestamp`) |
| `Temporal` | `valid_time: Interval \| UnknownTime`, `observed_time`, `timezone_original` |
| `Candidate` / `Subject` | `entity_id, score, features, reasons, vetoed` / `mention, entity_id?, link_status, candidates, mention_key=(source_sha256, locator)` |
| `TextSpanPointer` | `source_id, sha256, page?(None for txt/md), line?, page_text_sha256, text_canon_version, char_start, char_end, quote, quote_sha256, line_rects_pt: list[Rect]?, line_rects_px?` |
| `ImageRegionPointer` | `source_id, sha256 (derived), bbox, coord_space="oriented_px", reader, read_text, reread_text?, crop_sha256` |
| `TableCellPointer` | `source_id, sha256, row, column, raw_value, row_sha256, row_byte_offset, sheet?` |
| `SensorWindowPointer` | `source_id, series_id, partition_sha256, channels, start, end, n_points, expected_points, statistic, granularity, window_sha256, envelope_id?` |
| `HumanDecisionPointer` | `decision_id, principal=(iss, sub)` (MVP `iss="local"`), `display_name_snapshot, role_snapshot, reason, base_version, shown_evidence_hash, timestamp` |
| `Method` / `Confidence` | `extractor, extractor_version, rule_id, llm_used, model_id?` / `value, calibrated, components{…}, stage: pre\|final, calibration_fit_id?` |
| `ClaimRecord` | As in v1, plus validators: inferred ⇒ `derived_from` + `rule_id`; extracted ⇒ evidence; `sensor_native` ⇒ no `normalized_*`; `UnknownTime` ⇔ granularity unknown |
| `Source` | `source_id, case_id, modality, sha256, origin, ingested_at, derived_from_sources, coverage_period?, synthetic, mime, size, held_reason?` |
| `Envelope` | `envelope_id, machine, series_id, scope, statistic="robust_max_z", granularity="day", quiet_days: list[QuietDay(date, reasons, t_d)], n, med, mad, T_star, pooled: none\|t_star_model\|model_level, pool_members, degenerate_channels, params, partition_hashes` |
| `GateCheck` / `ComparisonRecord` / `ConflictRecord` | As in v1 (`averaged: Literal[False]`, no status) |
| `ReviewItem` | `review_id, type: ambiguous_entity\|reader_disagreement\|implausible_value\|hidden_text\|envelope_drift\|low_confidence\|unknown_unit\|llm_only_interpretation\|no_text_layer\|unsupported_page\|pdf_page_cap\|conflict_explain, claim_ids, mention_keys, candidates?, evidence_hash, opened_at` |
| `ReviewEvent` | `event_id, seq, review_id, kind: opened\|decided\|stale\|explained, decision_id?, at`. `escalated` is **derived at read time**, never stored |
| `DecisionRequest` | `choice: EntityChoice \| ReadingChoice(accept\|reject) \| ExplainChoice \| EscalateChoice` (discriminated, validated against the item), `reason (≥15)`, `base_version`, `shown_evidence_hash`, `supersedes?`. `extra="forbid"`, so `reviewer` returns 422 |
| `ConfigBundle` | Case (`plant_tz`, shifts, working calendar), ontology (phrases → class, quantifier, **attribute group**, scope channels), aliases, tolerances, gauges, envelope (α, ±3 d, `training_policy`, abs ε), gate (τ_link, δ_link, τ_review, λ), llm (modes, models, budgets) |
| `CaseVersion` | `case_id, version, parent_manifest_hash, manifest_hash, config_hash, engine_sha, lockfile_hash, canon_version, tesseract_version, traineddata_sha, pdfium_version, tzdata_version, llm_mode, ai_status`, records, `views{state, story, timeline, review}` |
| `PageText` | `text, page_text_sha256, text_canon_version, char_to_offset, char_boxes_pt, loose_boxes_pt, font_sizes, generated, text_object_ids, render_mode?, fill_alpha?, capabilities: set[str], cropbox, rotation` |
| Others | `BuildStatus`, `OcrResult`, `VlmReading`, `ProposalBatch`, `Story`, `TimelineEntry`, `EvidenceRender`, `RecheckResult`, `IntegrityResult`, `EvalReport`, `Problem` |

### C.1a ID derivation (`ids.py`; `h` = sha256(JCS(…))[:24])
| Record | ID |
|---|---|
| claim | `clm_` + h(semantic fields + pointer + method) |
| comparison | `cmp_` + h(sorted claim_ids, config_hash) |
| conflict | `cf_` + h(sorted side claim_ids) |
| review item | `rv_` + h(type, sorted mention_keys) (stable across extractor versions) |
| review event | `rve_` + h(review_id, kind, seq) |
| decision | `dec_` + h(review_id, principal, base_version, choice) |
| envelope | `env_` + h(machine, series, scope, statistic, granularity, sorted Q, params, pool_members, partition hashes) |

### C.2 Ports (`typing.Protocol`)
```text
BlobStore:       put(stream, *, max_bytes) -> BlobRef  (existing hash → no-op) ; open(sha) ; exists(sha)
PdfReader:       page_count(pdf) -> int ; page_text(pdf, page) -> PageText
                 render_png(pdf, page, dpi=150, *, without_objects: frozenset[int] = ∅) -> RenderResult(png, gray: ndarray)
                 pt_to_px(meta, rect, dpi) -> RectPx                       # child-only adapter
OcrReader:       read_words(png, cfg) -> OcrResult ; reread_region(png, bbox, cfg) -> OcrResult
TelemetryReader: read(series_id, start, end) -> pa.Table ; partition_sha(series_id) -> Sha256
VlmReader (P1):  read_region(crop_png, prompt_id, gauge) -> VlmReading
LlmProposer:     propose(doc: RedactedDocument, prompt_id) -> ProposalBatch
Redactor:        redact(text) -> RedactedDocument (reversible span map; numbers/units never redacted)
ExtractionCache: get(key) -> bytes|None ; put(key, artifact) -> Sha256 (write-once) ; mode: record|replay
                 CacheKey = (input_sha, extractor_id, extractor_version, params_hash, binary_version)
Clock:           now_utc() -> datetime
ClaimStore:      append(case_id, records) ; put_version(v, members) ; get_version ; latest ; load_claims ;
                 review_events ; commit_decision(case_id, expected_latest, decision, event, version) -> Committed|Moved
EnginePorts:     dataclass(blobs, pdf, ocr, telemetry, cache, clock, llm, redactor, vlm|None)
```

### C.3 Stage functions (pure)
```text
read_text(src, blob, cfg, ports) -> ReadResult ; read_plaintext(src, blob, cfg) -> ReadResult
read_table(src, blob, cfg) -> ReadResult ; read_image(src, blob, cfg, ports) -> ReadResult
read_sensor(telemetry: TelemetryReader, case, cfg) -> SensorWindows          # duplicates → gap
normalise_units / resolve_entities / resolve_time                            (as v1)
learn_envelopes(telemetry, events, sources, case, ontology, cfg) -> list[Envelope]   # per scope; LogCoverageError
detect_gaps(windows, events, envelopes, cfg) ; derive_sensor_state(windows, envelopes, cfg)
score_pre(claims, cfg) -> list[ClaimRecord]                                  # corroboration = 0
apply_holds(claims, review_items, events, decisions, cfg) -> (eligible, held)   # uses pre-confidence
candidate_pairs(eligible, ontology_groups) -> Iterator[pair]                 # attribute-group interval sweep
gate(a, b, ctx) -> ComparisonRecord ; group_conflicts(comparisons, claims) -> list[ConflictRecord]
score(claims, comparisons, provenance, cfg) -> list[ClaimRecord]             # final; never alters holds
derive_review_status(items, events, clock, calendar) -> statuses             # open|decided|stale|escalated
snapshot(case, parent, parts, hashes, clock) -> CaseVersion                   # hash excludes wall-clock
build_case(manifest, config, decisions, ports) -> CaseVersion
rerun_after_decision(parent, decisions, config, clock) -> CaseVersion
```

### C.3b Adapter-side steps (not pure)
- `split_telemetry(csv) -> list[DerivedSource]` (duplicates preserved; `test_split_preserves_duplicate_rows`).
- `prerender_cited(version, ports)` (in the child).
- `record_cache`.

### C.4 API (`/api/v1`, case-scoped via `resolve_case_and_authorize`)
| Router | Routes |
|---|---|
| health | `GET /healthz`, `GET /readyz` |
| auth | `POST /auth/login` (CSRF + JSON), `POST /auth/logout`, `GET /auth/me` |
| cases | `GET /cases`, `POST /cases` (ingestor), `GET /cases/{cid}/latest` (307, no-store) |
| sources | `POST /cases/{cid}/sources` (ingestor; ASGI-capped streaming), `GET /cases/{cid}/sources/{sid}/original` (hardened headers) |
| builds | `POST /cases/{cid}/build` (202; 409 build-in-progress + Retry-After), `GET /cases/{cid}/builds/{bid}` |
| versions | `GET /cases/{cid}/versions/{v}/{state\|story\|timeline\|claims\|comparisons\|conflicts\|review\|manifest\|integrity}`; `GET …/versions/{v}/claims/{id}`; `GET …/versions/{v}/claims/{id}/evidence[/page.png\|/crop.png]` (cached only, 404 render-missing); `GET …/versions/{v}/entities/{eid}/envelope`; `POST …/versions/{v}/replay` (evaluator, DB single-flight) |
| claims | `POST /cases/{cid}/claims/{id}/recheck` (no-store, coalesced, 30/min) |
| review | `POST /cases/{cid}/review/{rid}/decision` (reviewer; senior for supersede; also covers `conflict_explain` and escalate) |
| eval | `POST /eval/run` (evaluator, DB single-flight), `GET /eval/report` |
| P1 events | `GET /cases/{cid}/events` (SSE, notice only) |

Problem types: v1's list plus `render-missing`, `replay-cache-miss`, `pdf-page-cap` and `rate-limited`.

### C.5 Frontend
- **Islands:** `LoginForm`, `CaseList`, `CaseWorkspace`, `ExpertView`, `ReviewQueue`, `EvalDashboard` (simple).
- **Components:** v1's set, plus multi-rect `RegionViewer`, a text-only `TextSpanView` for txt/md, an `UnknownTime` chip on the timeline, an `Escalated` badge, an `Explained` badge, and the `ExplainChoice` and `EscalateChoice` forms in `DecisionPanel`.
- **lib:**
  - `client.ts` (CSRF on writes);
  - `query/keys.ts` (version in every key);
  - `geom/bbox.ts`;
  - `textSlice.ts` (text nodes only);
  - `charts/safeFormatter.ts` (`encodeHTML` wrapper, the only allowed formatter).

---

## D. MVP milestones, tasks, hour ledger

### D.1 Ledger (4 × 30.5 = 122 h; **buffer 5.25 h**)
| A — Ingest + platform security | h | B — Engine + correctness floor | h | C — Frontend + e2e | h | D — Data, store, API, eval | h |
|---|---|---|---|---|---|---|---|
| A-01 Scaffold, pre-commit (ruff, mypy, import-linter incl. forbidden modules, gitleaks, nomean, contracts, lockfile sync), gitattributes, dockerignore, `.env.example`, hardened Docker skeleton, smoke (image + native), log scrubbing, no-egress default test | 2.5 | B-01 Models, validators, UnknownTime, canonical, IDs (§C.1a), port signatures (draft h3) | 3.0 | C-01 Astro/Tailwind, same-origin, typed client, **CSP spike h1** | 1.5 | D-01 h0 reality check + quiet-day counts | 1.5 |
| A-01b Ports, fakes, port contract tests | 1.25 | B-02 TelemetryReader adapter use, day windows, duplicates (T-14) | 2.5 | C-02 CaseWorkspace + story (precomputed view) + poller | 3.5 | D-02 Seed generators run once in image, bytes + SHA256SUMS committed (no temperature variant) | 3.5 |
| A-02 pypdfium2 PdfReader: char loop, surrogates, offsets, per-line rects, loose/tight boxes, font size, capability probe, render with annots (pixel cap, numpy gray, compress 1), cited-page prerender, PageText cached | 5.0 | B-03 Envelopes: per-scope, series_id, pool members, t_d, coverage d±3, pooling, drift, **oracle tests** (T-01/02/04, N-3) | 5.0 | C-03 ConflictCard, GateTable, OutcomeBadge | 3.0 | D-03 SQLite schema, triggers, version_claims, review_events (seq), derived-status views, partial-unique indexes, ConfigBundle + config_hash | 3.25 |
| A-03 Text rules + normalised view with offset map; txt/md reader | 3.5 | B-04 Gaps, flatline (abs ε), quantifier coverage + **gap-monotonicity property** (T-03/13) | 2.0 | C-04 RegionViewer (multi-rect), TextSpanView, TableWindow, RecheckBadge | 4.0 | D-04 Record/manifest chain (tables listed), snapshot hash excl. clock, byte verification, anchors, replay | 2.5 |
| A-04 Hidden-text guard: per-char + object-removal diff + size/CropBox/mode/alpha (T-06, Q1-22) | 2.0 | B-05 Units, sensor_native (T-05) | 1.5 | C-05 SensorChart (window, band, p5–p95, S-88.1, safe formatter) | 3.0 | D-05 API routes, LRU, ETag, 409s (3 kinds), IDOR dependency, RFC 9457, compute-then-commit decisions, recheck re-derive + rate limit, DB single-flight | 4.5 |
| A-05 CSV cell pointers (byte offsets), coverage_period | 2.0 | B-06 Resolver, features, veto, mention keys (T-10) | 3.0 | C-06 Timeline (valid + observed + unknown) | 2.0 | D-06 Fault injector, 7 types, seeded, dev/holdout **machines** | 3.0 |
| A-06 OCR, re-read, plausibility, EXIF, pixel header cap (T-09/16/21) | 4.5 | B-07 Time: plant_tz, half-open, unknown, relative (T-11/12/38) | 2.5 | C-07 ReviewQueue, DecisionPanel (typed choices, explain, escalate), CandidateList, LoginForm | 3.25 | D-07 Baselines TF-IDF, averaging/LWW, no-gate (N-4) | 1.5 |
| A-07 Upload: ASGI cap + streaming multipart, magic/text checks, blob put no-op, original-download route (T-16..19) | 2.25 | B-08 Gate, attribute-group pairing, outcomes, grouping + **totality/symmetry/never-average properties** | 4.5 | C-08 ExpertView, EnvelopeView, Integrity/Replay, StageTimings | 3.0 | D-08 Metrics + **evaluation protocol** (leave-block-out, holdout machines, Wilson harness by h14), ECE/Brier bootstrap, per-bin | 3.0 |
| A-08 Build child: env allowlist, self-deadline, parent pipe, killpg, 30 s sweep, RLIMIT measured, cache semantics, build_key retry (S4, T-20/28) | 2.5 | B-09 score_pre + score, independence, uncalibrated (T-15/32) | 2.0 | C-09 CSP header wiring (hashes JSON), security headers middleware, eslint rules (S7/S8, T-22/29) | 1.25 | D-09 Holdout gate (clean tree, 3 hashes on remote) + report (T-31) | 1.5 |
| A-09 Auth: argon2 params, threadpool, sessions hashed, abs expiry, CSRF incl. login, Origin, TrustedHost, loopback/LAN rule (S1/S2) | 2.5 | B-10 Rerun path, escalation derivation, explain semantics | 2.0 | C-10 Minimal eval page | 0.5 | D-10 Goldens + determinism + randseed + NFR-1 re-resolve | 1.5 |
| A-10 Hostile corpus (13) + secrets sentinel test (T-39) | 1.0 | B-11 Remaining properties (unit round-trip, overlap, chain, canonical) | 1.0 | C-11 Integration, polish, a11y | 1.5 | D-11 Final image ×2, S11 test, audit, native replay-verify, rehearsal, anchors | 2.0 |
| A-12 Integration/bugfix | 1.0 | B-12 Integration | 1.0 | C-12 Playwright 5 specs (from A) | 1.5 | D-12 Label kit (U-2) 0.5 · D-13 Perf suite 0.5 | 1.0 |
| **Buffer** | 0.5 | **Buffer** | 0.5 | **Buffer (floats to A)** | 2.5 | **Buffer (floats to B)** | 1.75 |
| **Total** | **30.5** | | **30.5** | | **30.5** | | **30.5** |

#### D.1a Deltas from v1 (they sum to the buffer change)
| Person | Change in hours |
|---|---|
| A | A-01 +0.5, A-01b +1.25 (new), A-02 +0.5, A-04 +0.5, A-05 −0.5, A-07 +0.75, A-11 −1.5 (moved to C-12), A-12 −0.5 → work +1.0, buffer 1.5→0.5 |
| B | B-01 +1.0, B-03 +0.5, B-04 +0.5, B-08 +0.5, B-10 +0.5, B-11 −1.5, B-12 −0.5 → work +1.0, buffer 1.5→0.5 |
| C | C-02 −0.5, C-06 −0.5, C-07 +0.25, C-08 −0.5, C-09 +0.25, C-10 −0.5, C-11 −1.0, C-12 +1.5 → work −1.0, buffer 1.5→2.5 |
| D | D-02 −1.0, D-03 +0.75, D-05 +1.0, D-07 −0.5, D-08 +0.5, D-11 +0.5, D-12 +0.5, D-13 +0.5 → work +2.25, buffer 4.0→1.75 |

**Total buffer: 8.5 → 5.25 h.**

**Floors:**
- **Correctness floor:** B-02..B-11 (25.0 h) + the D-08 protocol/harness (≈ 2.5 h) = **≈ 27.5 h**.
- **Security floor:** A-01 secrets/egress (≈ 0.75), A-04 2.0, A-07 2.25, A-08 2.5, A-09 2.5, A-10 1.0, C-09 1.25, D-05 authz/409/rate limit (≈ 1.5) = **≈ 13.75 h**.

#### D.1b Calendar (wall clock)
**Sleep and meals** (5.5 h each; at least two people are always awake on the critical path):
- C h12–16.5
- D h14.5–19
- A h17–21.5
- B h25–29.5

| Window | A | B | C | D |
|---|---|---|---|---|
| h0–h2.5 | A-01 | B-01 models | C-01 (CSP spike) | D-01 h0 |
| h2.5–h8 | A-02 (h6 checkpoint) → A-01b h7–8.25 | B-01 (draft h3, freeze h8) | C-02 against stub fixtures | D-03, D-05 stubs, D-02 start |
| h8–h10 | A-03 minimal → skeleton | B-02 + B-03 min + B-08 min | C-03 min | D-04 min, D-05 story/conflicts |
| h10–h17 | A-03, A-04, A-05, A-07 | B-03, B-04, B-05 | C-03, C-04 (sleep h12–16.5) | D-08 harness (by h14), D-02 (sleep h14.5–19) |
| h17–h24 | A sleeps until h21.5; then A-06, A-08 | B-06, B-07, B-08, B-09 | C-05, C-06, C-07 | D-06, D-07, D-10 goldens (by h24) |
| h24–h30 | A-09, A-10, A-12 | B-10, B-11, B-12 (by h25); sleeps h25–29.5 | C-08, C-09, C-12, C-10 | D-05 decision, D-08, D-13, D-12 |
| h30–h36 | Fixes | Fixes; holdout watch h31 | C-11 fixes | D-09 holdout **h31**, report, D-11, anchors h35 |

### D.2 pypdfium2 plan (A-02/A-04)
| Need | Mechanism | Gap and fallback |
|---|---|---|
| **Text and offsets** | Our own loop over `FPDFText_CountChars`/`FPDFText_GetUnicode`. Surrogate pairs are joined (two indices → one offset). Generated chars are kept and flagged (`FPDFText_IsGenerated`). No NFC. `page_text` is UTF-8 bytes written in binary mode, and its sha is `page_text_sha256`. A NFC/whitespace-collapsed view with an offset map serves the rules. `text_canon_version="1"` | `get_text_range()` is used only as a smoke cross-check after the same normalisation. Tests: `test_surrogate_pair_offsets`, `test_quote_spans_generated_linebreak`, `test_quote_equals_page_text_slice` |
| **Boxes** | `get_charbox(i, loose=False)` for geometry, `loose=True` for the size rule. Generated and zero-area boxes are skipped. Each line becomes a rect (baseline clustering) | `bbox_pt` becomes `line_rects_pt` |
| **Font size** | `FPDFText_GetFontSize`, plus loose-box height < 4 pt | The nominal size ignores the CTM, so the loose box is the backstop |
| **Render mode and alpha** | `FPDFText_GetTextObject` → `FPDFTextObj_GetTextRenderMode`; `FPDFText_GetFillColor` | Capability-probed and recorded in `PageText.capabilities` |
| **Visibility (primary)** | For each text object holding a non-whitespace char of a candidate span: open a fresh document instance, remove the object (`FPDFPage_RemoveObject` + `FPDFPage_GenerateContent`), render, and diff the grey levels inside each char's box. A max diff < 8 means invisible. Any invisible char holds the whole span (`hidden_text`) | If `GetTextObject` is missing, use per-char crop std-dev < 8 and label it `visibility=lower_assurance`. Cost is one extra render per affected object, only on pages with candidates. Fixtures: white-text, `hidden_negation.pdf` (hidden "no "), `white_over_rule.pdf`, `covered_by_rect.pdf`, render-mode-3. Tests: `test_white_text_pdf_zero_claims_one_review`, `test_partial_hidden_span_held`, `test_covered_text_held` |
| **CropBox and rotation** | `get_cropbox()`, `get_rotation()`. Outside the CropBox ⇒ held. `/Rotate ≠ 0` ⇒ `unsupported_page` | P1-10 uses `FPDF_PageToDevice` |
| **Render** | `page.render(scale=150/72, draw_annots=True)`, pixel cap checked from the CropBox before rendering (> 40 M px ⇒ refused). Grey from `to_numpy()`, PNG at `compress_level=1`. Only cited or candidate pages, and only in the child | `test_pdf_huge_mediabox_render_refused`, `test_bbox_roundtrip_reportlab_fixture` |
| **Scanned PDFs** | `count_chars()==0` ⇒ `no_text_layer` review item | P1-10: render → OCR |
| **Caps** | Page count is enforced in the child: > 50 ⇒ held source `pdf-page-cap` | `test_hostile_corpus[pdf_51_pages]` |
| **Determinism** | `PageText` is stored in the extraction cache with `binary_version = pypdfium2 + PDFium build` | Native replay matches the image (D-11) |

### D.3 Milestones (named tests are binding for the Tester)

#### M0 — Setup and h0 reality check (h0–h2.5)
- **A-01:**
  - `test_lockfiles_in_sync` (T-37);
  - `test_dockerignore_excludes_secrets` (T-39);
  - `test_groq_disabled_by_default_no_egress` (T-40, P0 default);
  - `test_smoke_rejects_network_fs_for_db`;
  - `test_worker_does_not_import_api`;
  - `test_compose_ports_loopback_only`.
- **C-01:** an island hydrates under the enforcing CSP header.
- **D-01:** `h0_report.json` and the decision (real day / another real day / planted) pinned in `case.yaml`.
- **Exit:** `make smoke` green in the image and `smoke-native` green on 4 laptops. Peak VM measured, so RLIMIT is set.

#### M1 — Contracts frozen (h2.5–h8; fakes by h8.5)
- **B-01:**
  - every model and ID rule;
  - `test_review_id_stable_across_extractor_version`;
  - `test_unknown_time_has_no_bounds`;
  - canonical property tests;
  - tag `contracts-v1`.
- **A-01b:** the port contract tests, parametrised over fakes.
- **D-03:**
  - `test_trigger_aborts_update`;
  - `test_no_update_paths_status_derived` (N-1);
  - `test_failed_build_same_key_can_retry`.
- **A-02:** green at the h6 checkpoint.
- **Exit:** `contracts-check` green; `schema.d.ts` committed.

#### M2 — Walking skeleton (h8–h10)
- C-17 and S-88 are on screen, red "They disagree", with the version badge and computed numbers.

#### M3 — Full ingest and engine (h10–h24; sign-off by A+B, goldens by D at h24)
| Task | Named tests |
|---|---|
| A-02/A-03 | `test_quote_equals_page_text_slice`, `test_surrogate_pair_offsets`, `test_quote_spans_generated_linebreak`, `test_plaintext_reader_offsets_crlf_preserved`, `test_render_stage_ms_recorded`, `test_page_png_cache_miss_404_not_render` |
| A-04 | `test_white_text_pdf_zero_claims_one_review`, `test_partial_hidden_span_held`, `test_covered_text_held` |
| A-05 | `test_cell_pointer_row_sha_and_offset`, `test_envelope_refuses_without_log_coverage` (with B-03) |
| A-06 | `test_decimal_drop_69_goes_to_review`, `test_exif6_bbox_alignment_and_no_gps`, `test_hostile_corpus[png_60mpx_rejected]` |
| A-07 | `test_300mb_rejected_streaming` (bytes read ≤ cap + 64 KiB), `test_chunked_upload_without_length_capped`, `test_api_never_imports_pdfium`, `test_hostile_corpus[html_as_pdf, svg, traversal_name, bomb_png, pdf_renamed_csv, html_renamed_txt]`, `test_upload_refused_when_disk_below_1gb`, `test_blob_put_existing_hash_is_noop_windows` |
| A-08 | `test_kill_mid_build_marks_stale_then_rebuilds`, `test_parent_restart_kills_orphan_child`, `test_timeout_kills_tesseract_grandchild`, `test_child_oom_marks_failed_not_running`, `test_build_child_under_rlimit_builds_demo0`, `test_parse_child_env_has_no_groq_key`, `test_build_key_idempotent`, `test_replay_cache_miss_is_error` |
| B-02 | `test_duplicate_ts_not_averaged`, `test_split_preserves_duplicate_rows` |
| B-03 | `test_conformal_oracle`, `test_quiet_day_false_alarm_rate_dev`, `test_check4_rejects_statistic_or_granularity_mismatch`, `test_planted_hot_days_bounded_shift`, `test_case_window_excluded`, `test_thin_history_uses_model_pool`, `test_envelope_drift_opens_review`, `test_quiet_day_requires_coverage_d_pm3`, `test_envelope_per_phrase_scope` |
| B-04 | `test_spike_in_gap_never_agree`, `prop_deleting_readings_never_toward_agree`, `test_frozen_sensor_flatline`, `test_stop_event_not_gap`, `test_flatline_degenerate_scale_abs_eps` |
| B-05 | `test_gauge_vs_telemetry_cannot_compare`, `test_no_mm_s_in_api_or_ui`, `test_unknown_unit_never_converts` |
| B-06 | `test_transposed_digits_never_autolink`, `test_serial_conflict_vetoes`, `test_decision_keyed_by_mention_key` |
| B-07 | `test_local_day_boundary_2330`, `test_undated_note_time_unknown`, `test_relative_time_yesterday_shift2`, `test_client_timestamp_ignored` |
| B-08 | `test_held_claims_never_pair`, `test_conflict_grouping_c17`, `test_forall_normal_vs_error_row_disagrees`, `test_forall_agree_requires_log_coverage_of_window`, `prop_gate_totality`, `prop_gate_symmetry`, `prop_never_average` |
| B-09 | `test_undeclared_provenance_no_corroboration`, `test_c17_confidence_computed`, `test_low_confidence_claim_never_pairs` |
| D-04 | `test_chain_verify_detects_edit`, `test_snapshot_hash_mismatch`, `test_manifest_covers_review_events`, `test_replay_identical_with_different_clock`, `test_integrity_verifies_stored_bytes` |
| D-05 | `test_cross_case_claim_404`, `test_viewer_decision_403`, `test_spoofed_reviewer_field_422`, `test_versioned_cache_headers_private_immutable`, `test_latest_no_store`, `test_problem_json_types`, `test_build_conflict_409_retry_after`, `test_recheck_re_derives_value`, `test_recheck_rate_limited` |
| D-06 | `test_injector_seeded_reproducible`, `test_dev_holdout_machines_disjoint` |
| D-08 (part 1) | `test_false_alarm_eval_day_not_in_calibration_set`, `test_wilson_ci_known_values` |
| D-10 | Goldens for Demos 0, 1a, 1b, 3, 4, 5, 5b, 2 (held), 6 (held); `test_no_magic_literals_in_engine`; `test_all_pointers_re_resolve`; golden-randseed |
| D-13 | `tests/perf` on image + native |

- **Exit:**
  - all of the above green;
  - build < 60 s (perf report);
  - goldens in pre-commit (blessed incrementally from h16).
- **The h26 stretch gate** is decided by A, C and D. B is asleep h25–29.5, so B's stretch items (S-04, S-05) are effectively deferred to P1.

#### M4 — UI complete (h18–h28)
- **C-03..C-08**, with all four proof kinds, multi-rect overlay, envelope view, integrity badge and replay.
- **B-10:** `test_decision_rerun_p95_under_1500ms`, `test_auto_escalate_after_one_working_day`, `test_explain_never_changes_outcome`.
- **D-05:**
  - `test_20_parallel_decisions_one_wins`;
  - `test_stale_base_version_untouched_item_accepted`;
  - `test_supersede_requires_senior`;
  - `test_decisions_on_two_cases_parallel_no_locked_error`;
  - `test_decision_during_build_other_case_p95_under_2s`;
  - `test_proof_p95_under_1s_during_decision`;
  - `test_choice_validated_against_item`.
- **A-09:**
  - `test_login_lockout_5_in_5min`;
  - `test_session_rotated_on_login`;
  - `test_session_token_stored_hashed`;
  - `test_session_absolute_expiry`;
  - `test_login_requires_csrf_header`;
  - `test_cross_origin_form_post_403`;
  - `test_write_requires_json_and_csrf`;
  - `test_foreign_host_header_400`;
  - `test_login_unknown_user_constant_work`;
  - `test_login_concurrency_bounded`;
  - `test_lan_without_tls_refuses_start`.
- **C-09:** `test_html_responses_have_csp_header_with_frame_ancestors`, `test_original_download_headers`.
- **C-12 Playwright** (median of 5 runs, enforcing CSP header):
  - `e2e_proof_under_1s`;
  - `e2e_decision_card_under_2s`;
  - `e2e_byte_flip_evidence_changed`;
  - `e2e_xss_fixture_no_dialog_under_csp` (including an `<img src=x>` channel name in a tooltip);
  - `e2e_all_panels_same_version`.
- **Exit:** e2e green on the image; NFR-10 (≤ 2 clicks) and NFR-11 (text labels) checked.

#### M5 — Eval and hardening (h16–h30; feature freeze h30)
- **D-06/D-07/D-08:** dev runs, baselines (`test_baseline_output_generated`), and metrics with CIs.
- **A-10:** the full hostile corpus (13 files: the original 7 + png_60mpx, pdf_51_pages, pdf_renamed_csv, html_renamed_txt, hidden_negation, huge_mediabox), plus `test_no_secret_in_logs_or_responses` (with sentinel key, seeded passwords and a malformed login) and `test_logs_contain_no_document_text` (S10).
- **B-11:** the remaining properties.
- **Cross-team:**
  - `test_parallel_eval_runs_one_proceeds` (owner D, DB single-flight);
  - `test_network_off_build_succeeds` (owner D, `--network none`).
- **D-11:** `make audit` one-shot, with results recorded in the freeze notes.
- **Exit:** `make check` and `make e2e` green on `main`; tag `mvp-freeze` at h30, with the config, engine and lock hashes **pushed**.

#### M6 — Holdout, freeze, rehearsal (h30–h36)
- **h31, D-09:** `make eval-holdout`, run once. Checks `test_eval_report_has_pushed_config_commit` (config, engine and lock hashes). `test_quiet_day_false_alarm_rate_holdout` runs here only: ≥ 200 holdout-machine quiet days, leave-block-out, Wilson CI. The report records P/R/F1 per fault, entity acc@1/@3, per-bin accuracy, ECE and Brier (bootstrap CI, bin counts), baseline outputs, and the share of external faults or the U-2 disclosure.
- **D-11:**
  - image built on two laptops (same digest);
  - `test_image_nonroot_readonly`;
  - the image secret grep (`grep -r gsk_`, no `credentials.local.txt`);
  - native `replay-verify` equals the image manifests;
  - perf report on both;
  - backup video.
- **h32:** slides updated from engine numbers.
- **h33:** rehearsal against the HARDENING §6 checklist.
- **h35:** `make anchor` pushed, with the roots visible in the UI.

### D.4 Stretch (h26 gate, buffer only, flags off by default)
1. S-01 SSE (1 h, C/D).
2. S-02 Ed25519 with off-box key (1 h, A).
3. S-03 Groq VLM record (3 h, A, only if a key and team consent exist; the demo runs in replay).
4. S-04 recalibration (P1, B asleep).
5. S-05 load bins (P1).
6. S-06 LLM + verifier (P1).
7. S-07 XLSX (P1).

---

## E. Product phases (single-plant pilot)

**Team:** the same 4 engineers; plant IT/OT (about 0.2 FTE); 2 maintenance engineers as reviewers and labellers (about 2 h/week each); a sponsor; and the plant DPO for the retention decision. **Calendar:** about 25 weeks.

### P1 — Hardening and stretch (weeks 1–4)
| ID | Task | Closes |
|---|---|---|
| P1-01 | SSE notices from `version_events` (outbox-ready); polling fallback | FR-UI-7 |
| P1-02 | Ed25519 manifests, off-box key, `key_id` | ADR-04 P1 |
| P1-03 | **GroqLlmProposer** (see detail below) | FR-ING-5, T-07, T-08, T-33, T-40 |
| P1-04 | **GroqVlmReader**: crop only; OCR vs. VLM disagreement beyond the gauge resolution ⇒ held; same propose-child, cache and allowlist rules | FR-ING-4 P1, FR-TRUST-3, T-09 |
| P1-05 | Isotonic/Platt calibration on U-2 labels plus injected truth; `calibration_fit_id`; ECE ≤ 0.05 on the holdout | FR-TRUST-5, NFR-12, D6 |
| P1-06 | Load bins (rotate terciles) with per-bin n fallback | FR-NORM-4 P1 |
| P1-07 | XLSX: openpyxl read-only + defusedxml; zip caps (≤ 1,000 entries, ≤ 100 MB uncompressed, ratio ≤ 100) | FR-ING-2 P1, T-16 |
| P1-08 | Full eval dashboard; threshold tuning on dev only | FR-UI-6, FR-LOOP-2 |
| P1-09 | Schemathesis, full authz matrix, `fuzz_mutated_pdf_smoke`, pip-audit + CycloneDX SBOM in CI, `/eval/run` rate limit, **per-IP login throttle**, cross-machine determinism job | T-20, T-34, T-37 |
| P1-10 | Rotated pages (`FPDF_PageToDevice`), scanned PDFs (render → OCR in the child), near-duplicate derivation labels | FR-ING-1, FR-TRUST-2 |
| P1-11 | CI: `make check`/e2e/perf/audit, gitleaks in CI with push protection, image signing (cosign) | T-37, T-39 |
| P1-12 | Windows Job Object (kill-on-close, memory cap) for the native path | S4 (native) |
| P1-13 | Synthetic temperature channel variant of Demo 0 (badged) | PRD §11 variant |

**P1-03 detail (GroqLlmProposer).** Every item here is a requirement.
- **Client:** OpenAI-compatible. The base URL is on an **https allowlist** (`api.groq.com`). The model id is in the config and in `params_hash`, and is checked against `/models` at startup (fail closed).
- **Call settings:** temperature 0, JSON-schema output, no tools, `max_tokens` cap, 64 KB response cap, `extra="forbid"` on proposals.
- **Isolation:** it runs in a separate **propose child** that does no hostile parsing. The key is passed only in `record` mode.
- **Deadline and failure handling:** a 60 s AI deadline per build, concurrency 2, `Retry-After` honoured, a circuit breaker after 3 failures → `ai_status=degraded` and rules-only.
- **Budget:** reserved in the DB under `BEGIN IMMEDIATE`.
- **Modes:**
  - `off` (default; module never imported);
  - `replay` (a miss is an error);
  - `replay_or_skip` (misses recorded in the manifest);
  - `record` (write-once).
- **Egress consent:** `TRACE_LLM_EGRESS_ACK`, a per-case `allow_external_ai` flag, and a UI egress banner.
- **Redactor:** reversible, and never redacts numbers or units.
- **Verifier:** the 5 checks, run against the de-redacted original.
- **Secrets:** a `GROQ_API_KEY_FILE` secret, and the `openai`/`httpx` loggers set to WARNING.
- **Tests:**
  - `test_groq_disabled_by_default_no_egress`;
  - `test_groq_base_url_must_be_allowlisted_https`;
  - `test_llm_response_over_64kb_rejected`;
  - `test_proposal_extra_fields_rejected`;
  - `test_cache_key_changes_with_prompt_or_redactor`;
  - `test_unknown_model_fails_closed`;
  - `test_llm_replay_miss_is_error`;
  - `test_record_does_not_overwrite_cached_response`;
  - `test_groq_outage_build_completes_rules_only_under_60s`;
  - `test_groq_429_honours_retry_after`;
  - `test_budget_reservation_atomic_two_builds`;
  - `test_llm_mutations_zero_accepted` and `test_injection_fixture_no_outcome_change`, both run in replay (the CI gate) and in record.

**Exit:**
- all P1 tests green;
- with all AI modes off, the suite passes under `--network none`;
- the holdout is re-run, with ECE before and after calibration.

**Risks:**
- Groq model deprecation. **Mitigation:** model ids in the config, cache pinned to the id, config version bump on change.
- Rate limits. **Mitigation:** budget, backoff, circuit breaker.
- VLM weakness on gauge crops. **Mitigation:** it can only hold claims, never accept them.

### P2 — Platform migration (weeks 5–9)
| ID | Task |
|---|---|
| P2-01 | **Postgres 16** `PgClaimStore` (psycopg 3). The evidence tables store `body_jcs BYTEA` (authoritative) and a derived `body JSONB`. Fixed-width `valid_start/end` text is authoritative, with a generated `tstzrange` and GiST index. Append-only `BEFORE UPDATE OR DELETE` and `BEFORE TRUNCATE` triggers (plpgsql). `trace_owner` (migrations) vs. `trace_app`, with `REVOKE UPDATE, DELETE, TRUNCATE`, and the app role cannot alter or disable triggers. RLS prepared, off (single tenant). `pg_advisory_xact_lock(hashtext(case_id))` around decision, rerun, snapshot and build commit. T-24 and a two-worker build race run on PG in CI. Tests: `test_app_role_cannot_disable_trigger_or_truncate` |
| P2-02 | Migration: additive SQL files plus a runner (runs as `trace_owner` after a backup). `sqlite_to_pg` copies `body_jcs` bytes and `seq` and checks `sha256(body_jcs)==record_hash` per row. It also migrates the extraction cache, artifacts and snapshots with sha checks. `canon_version` is frozen. Tests: `test_migrated_chain_verifies`, `test_upgrade_n_minus_1_chain_verifies`. Exit includes `replay-verify` on the migrated chain |
| P2-03 | **MinIO with Object Lock** plus versioning. The **retention decision is written down first** (sponsor + DPO): GOVERNANCE with a two-person bypass, unless the plant requires COMPLIANCE. PII minimisation (roster outside WORM; identity snapshots only). `S3BlobStore` uses a conditional put; the API proxies originals. Tests: `test_locked_object_delete_denied`, `test_bucket_lock_mode_matches_policy` |
| P2-04 | **OIDC** (Authlib, auth-code + PKCE, BFF pattern). `principal=(iss, sub)` with snapshots. An append-only `identity_links` table maps local → OIDC identities (historic decisions are never rewritten). Groups map to roles. The IdP session is re-checked every 15 min, with a 12 h absolute limit. A break-glass admin raises an alert when used. Tests: `test_migrated_decisions_attribution_preserved`, `test_oidc_principal_is_iss_sub_pair`, `test_deprovisioned_user_session_revoked_15min` |
| P2-05 | **ADR-16: no Temporal for the pilot.** A Postgres job table (`FOR UPDATE SKIP LOCKED`) is drained by 1–2 worker containers, each running the same killable child. Eval and replay single-flight use DB rows. **Trigger to adopt Temporal:** more than one worker host with multi-step paid AI retries, or build p95 > 10 min, or > 500 builds a day |
| P2-06 | Outbox `version_events` in the same transaction; `LISTEN/NOTIFY` → snapshot builder and SSE fan-out |
| P2-07 | **Backups:** pgBackRest full weekly, differential daily, WAL archive, `repo-cipher-type=aes-256-cbc` with the key off the VM, to a **named second site** (plant DR room or NAS). MinIO replication to the same site. Anchors pushed daily. RPO 15 min, RTO 4 h. The monthly restore drill includes `trace verify --all` and `trace verify --blobs` (every `source.sha256` present, 5% re-hashed). Test: `test_restore_drill_db_blob_consistent` |
| P2-08 | **Monitoring:** OTel spans per stage; `/metrics` (internal); Grafana. Nightly `trace verify --all` → `trace_integrity_ok`. **Alerts:** integrity red (page), build failures > 3/h, stale build, review item older than 1 working day, backup age > 26 h, disk > 80%, cert expiry < 14 d, Groq budget 80%, IdP errors. Test: `test_integrity_job_alerts_on_tamper` (game day) |
| P2-09 | **Deployment:** compose on an on-prem Ubuntu 24.04 VM (8 vCPU / 32 GB / 500 GB). Images by digest, with `cosign verify --key` offline before `up`. The hardened run flags from S11. Caddy TLS from the plant CA. **Egress via a Squid forward proxy** with an SNI allowlist (Groq only when AI is on, the IdP, the git remote, the mail relay, the backup target); the app network is `internal: true`. Test: `test_egress_denied_except_allowlist` |
| P2-10 | **Performance:** k6 with 50 users. p95 versioned read < 300 ms, proof < 1 s, 40 machines × 30-day build < 2 min. Precompressed snapshots with a per-encoding ETag (`test_versioned_read_serves_precompressed_etag_per_encoding`). LRU sized from hit rates |

**Exit:**
- suite green on PG + MinIO;
- migrated chain verifies and replays;
- restore drill within the RTO, with DB and blobs consistent;
- SSO working on the plant IdP test tenant;
- the alert game day passes;
- the egress test passes;
- an ASVS L2-subset pen test has no highs.

**Risks:**
- IdP paperwork. **Mitigation:** start in week 1, with local accounts as interim.
- WORM misconfiguration. **Mitigation:** GOVERNANCE in staging first, and the policy test.

### P3 — Pilot onboarding (weeks 9–13)
| ID | Task |
|---|---|
| P3-01 | Asset register (CMMS CSV) → registry with serials, models, components and aliases; data-quality report |
| P3-02 | Historian export with `tags.yaml` (tag → machine/channel/unit/datasheet). The T-14 duplicate check runs **before** resampling, and the statistic is declared in the pointer. Expected points are computed from the **local day length** (DST) |
| P3-03 | Real logs with `coverage_period` (A8) |
| P3-04 | Tolerances from datasheets (A5) |
| P3-05 | `trace onboard check` readiness report (A1–A8) |
| P3-06 | **Labeller programme:** 2 non-builder engineers, 300 items, 50 double-labelled (κ ≥ 0.7), ≥ 30% of holdout faults authored by them, dev/holdout split by machine |
| P3-07 | Phrase ontology from real reports, each phrase with a quantifier and attribute group |
| P3-08 | Re-tune on dev; explicit `training_policy` per case type (`before_only` for live monitoring, `all_except_case_window` for retrospective); egress approval by plant IT (or AI stays off) |
| P3-09 | Training and runbooks: integrity red, build stuck, review backlog, restore, disk full, cert expiry, IdP outage/break-glass, **Groq key leaked** (revoke, rotate, purge, `gitleaks detect --log-opts=--all`), **erasure request** (states honestly what WORM retention cannot erase) |
| P3-10 | **ADR-17 sensor known-unit comparison:** statistic and granularity pairing (e.g. hourly mean vs. instant reading is not comparable), datasheet tolerance, goldens. Until accepted, check 4 fails for sensor vs. authored even with known units |

**Exit:**
- 40 machines registered;
- readiness report green, or each item accepted in writing;
- envelopes with n ≥ 19 or labelled as pooled;
- plant-holdout quiet-day false alarms passing (Wilson lower bound ≤ 5%; point estimate reported);
- labelled precision ≥ 0.90 and recall ≥ 0.85.

### P4 — Operations and go/no-go (weeks 13–25)
- **Weekly:** SLOs, held items, queue age, incidents, Groq spend.
- **Monthly:** restore drill, calibration check, drift review, CVE updates (additive migrations only).
- **SLOs:** 99% availability in working hours; p95 read < 300 ms; build < 2 min; review median < 1 working day; `trace_integrity_ok` = 1 nightly.
- **Mid-point at week 6. GO at week 12 only if all of these hold:**
  1. Engineer-confirmed conflict precision ≥ 0.85 on **N ≥ 100** adjudicated conflicts. The Wilson CI is reported, and its lower bound must be ≥ 0.75.
  2. "Gaps read as normal" = 0, from an automated invariant scan over every version (no ∀-agree with coverage < 100%; no agree where check 5 fails).
  3. Quiet-day false alarms: Wilson lower bound ≤ 5% **and** point estimate ≤ 5%, on ≥ 400 machine-days.
  4. ECE ≤ 0.05 after calibration, with CI.
  5. Median reviewer time ≤ 2 h/week, measured from `review_events` (time from opened to decided, attributed per principal).
  6. No Sev-1 integrity incident.
  7. Sponsor sign-off on value: at least 3 documented cases where TRACE surfaced a disagreement.

### P5 — Optional multi-tenant SaaS (outline only)
- Tenant in the path, enforced RLS, per-tenant KMS keys with crypto-shredding (T-35; T-36 extended from the P2/P3 design).
- An edge-authorised CDN keyed by (tenant, case, version); Redis; read replicas.
- Temporal plus a GPU OCR/VLM pool; an AI gateway (cache, caps, failover: Groq primary plus a second OpenAI-compatible provider).
- Kafka, Citus and TimescaleDB "planned only if".
- SOC 2, canary releases, a second region, admission-time cosign.

---

## F. Build risk register (top 12)

| # | Risk | P | I | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | The real M-21 on 14 Mar does not fit the story | M | H | h0 check; real alternative day, or planted and badged | D |
| R2 | pypdfium2 gaps (generated chars, CTM font size, missing object/render-mode API) | M | M | Own char loop; object-removal diff with capability probe; std-dev fallback labelled; h6 checkpoint pulls C's reserve | A |
| R3 | **Ledger is tight (5.25 h buffer)** | H | H | Floating reserves (C → A, D → B); the stretch gate does not open by default; the moved-to-P1 list is fixed; a task 50% over its estimate is escalated at the next standup | Lead |
| R4 | OCR or PDF float differences between OSes | H | M | Every reader output cached (PageText included); native replay-verify in D-11 | A |
| R5 | Quiet-day n < 19 | M | M | Model pooling labelled; h0 measures it | B/D |
| R6 | Contract churn after h8 | M | H | Freeze tag, CCR, contracts-check | B |
| R7 | CSP header blocks hydration | M | H | Spike at h1; hashes JSON always generated; e2e under the header | C |
| R8 | CRLF or seed regeneration changes hashes | M | H | `.gitattributes`; committed seed bytes plus SHA256SUMS | A/D |
| R9 | SQLite lock contention (decision vs. build) | M | M | Compute-then-commit, `isolation_level=None`, single final child transaction, perf tests | D |
| R10 | RLIMIT breaks imports in the image | M | M | Allocator env, measured limit, cgroup backstop, `test_build_child_under_rlimit_builds_demo0` | A |
| R11 | No U-2 labeller | M | M | Injected-truth metrics, disclosed; D's label kit ready; P3-06 | D |
| R12 | Docker Desktop failure on a demo laptop | M | H | Native fallback rehearsed (replay mode); two laptops; video | D |

---

## G. Definition of Done

**Task level:**
1. A PR reviewed by a non-author (floor PRs → D, security PRs → B).
2. `make check` green: lint, mypy/tsc strict, import-linter, nomean, contracts-check, lockfile sync, tests, golden-randseed.
3. Every named test for the task (§D.3) exists under the exact name and passes. Invariants have properties.
4. No demo literals; no document text or secrets in logs or responses; no network calls (pytest-socket).
5. Hot paths have a `tests/perf` entry, run at the next milestone.
6. No contract change without a CCR. Goldens green, or re-blessed with the oracle green and the diff explained.
7. UI: text labels on badges; uncalibrated and synthetic badges where needed.
8. A `holdout`-marked test must never run outside `eval-holdout`.

**Milestone level:** all tasks done, exit criteria met, image builds, `make demo` passes, perf report updated (M3, M4, M6), tag `m<N>`, buffer use recorded.

**Phase level (pilot):** exit criteria met; CI green (check, e2e, perf, audit, image-scan); runbooks updated; an ADR for every decision (ADR-16 Temporal, ADR-17 known units); rollback tested in staging; sponsor sign-off.

---

## H. Traceability

### H.1 Functional requirements
| Req | MVP tasks | Product |
|---|---|---|
| FR-ING-1 | A-02, A-03, A-04, D-02, C-04 | P1-10 |
| FR-ING-2 | A-05, D-02 | P1-07, P3-03 |
| FR-ING-3 | B-02, B-03, B-04, A-01b (TelemetryReader), C-05 | P3-02 |
| FR-ING-4 | A-06, D-02, C-04 | P1-04 |
| FR-ING-5 | B-01 / A-01b (port, FakeLlm) | P1-03 |
| FR-ING-6 | A-07, D-03, B-09 | P2-03 |
| FR-NORM-1 | B-05 | P3-02, P3-04, P3-10 |
| FR-NORM-2 | B-06, C-07 | P3-01 |
| FR-NORM-3 | B-07, B-01 (UnknownTime), C-06 | P3-02 (DST), P3-05 |
| FR-NORM-4 | B-03, C-08, D-01, D-08 | P1-06, P3-08 |
| FR-NORM-5 | B-04, B-08 | P3-02 |
| FR-GATE-1 | B-08 (attribute groups), C-03 | — |
| FR-GATE-2 | B-08 (totality property) | — |
| FR-GATE-3 | B-08, C-03 | — |
| FR-GATE-4 | B-02, B-08, A-01 (nomean AST + lint) | — |
| FR-GATE-5 | B-01, D-03 (config_hash), D-04, D-10 | P1-09 |
| FR-TRUST-1 | B-09 | P3-06 |
| FR-TRUST-2 | B-09, A-07 | P1-10 |
| FR-TRUST-3 | A-04, A-06, B-03, B-06, B-09 (score_pre), D-03, B-10 | P1-04 |
| FR-TRUST-4 | B-09, C-08 | — |
| FR-TRUST-5 | B-09 (label), D-08 | P1-05 |
| FR-EVID-1 | B-01, D-03 | — |
| FR-EVID-2 | B-01, D-10 | — |
| FR-EVID-3 | D-03, D-04 | P2-01, P2-02 |
| FR-EVID-4 | D-03, A-07, B-02 | P2-01, P2-03 |
| FR-UI-1 | C-02, D-04 (views), D-05 | — |
| FR-UI-2 | C-04, C-05, D-05 (recheck re-derive), A-02 (prerender) | — |
| FR-UI-3 | C-06 | — |
| FR-UI-4 | C-07, D-05, B-10 (explain, escalate), A-09 | P2-04 |
| FR-UI-5 | C-08 | — |
| FR-UI-6 | C-10 | P1-08 |
| FR-UI-7 | C-02 (poll), S-01 | P1-01, P2-06 |
| FR-UI-8 | D-04, C-08 | P1-02, P2-08 |
| FR-LOOP-1 | B-10, C-07, D-05 | P3-09 |
| FR-LOOP-2 | D-06, D-07, D-08, D-09, D-12 | P1-05, P1-08, P3-06, P3-08 |

### H.2 Non-functional requirements
| NFR | Tasks |
|---|---|
| NFR-1 | B-01, D-10 (`test_all_pointers_re_resolve`) |
| NFR-2 | A-07, D-05 (recheck), C-12 (byte flip); P2-08 (nightly verify) |
| NFR-3 | D-03, D-04; P2-01, P2-02, P2-03 |
| NFR-4 | B-01, A-02/A-08 (cache), D-04, D-10, D-11; P1-09, P2-02 |
| NFR-5 | B-08, B-09, C-03, C-08 |
| NFR-6 | B-02, B-08, B-11, A-01 |
| NFR-7 | A-02, A-08, D-05, B-10, D-13, C-12 |
| NFR-8 | P2-10; P5 |
| NFR-9 | A-06, A-09, A-01 (scrubbing); P1-03 (redaction/egress), P2-03 (retention/PII), P2-04, P2-09; P5 |
| NFR-10 | C-02, C-11 |
| NFR-11 | C-03, C-11 |
| NFR-12 | B-09, C-08, D-08; P1-05 |

### H.3 Deliverables
| Deliverable | Tasks |
|---|---|
| D1 | A-02, A-03, A-05, A-06, B-02 |
| D2 | B-01, D-04 (`state` view), D-05 |
| D3 | B-01, D-10 |
| D4 | A-02, A-05, A-06, B-02, C-04, C-05 |
| D5 | B-06, B-07, B-08 |
| D6 | B-09, D-08, D-09, D-12 (P1-05) |
| D7 | C-02 … C-08 |
| D8 | D-02, D-10, C-12, D-11 |

### H.4 Threat index (T-01..T-40, N-1..N-4)
| Threat | Task | Named test(s) |
|---|---|---|
| T-01 | B-03, D-08, D-09 | `…false_alarm_rate_dev`, `…_holdout` (h31 only), `test_false_alarm_eval_day_not_in_calibration_set` |
| T-02 | B-03 | `test_check4_rejects_statistic_or_granularity_mismatch` |
| T-03 | B-04 | `test_spike_in_gap_never_agree`, `prop_deleting_readings_never_toward_agree` |
| T-04 | B-03 | `test_envelope_refuses_without_log_coverage`, `test_planted_hot_days_bounded_shift`, `test_case_window_excluded`, `test_quiet_day_requires_coverage_d_pm3` |
| T-05 | B-05 | `test_gauge_vs_telemetry_cannot_compare`, `test_no_mm_s_in_api_or_ui` |
| T-06 | A-04 | `test_white_text_pdf_zero_claims_one_review`, `test_partial_hidden_span_held`, `test_covered_text_held` |
| T-07, T-08 | P1-03 | `test_llm_mutations_zero_accepted`, `test_injection_fixture_no_outcome_change` |
| T-09 | A-06; P1-04 | `test_decimal_drop_69_goes_to_review` |
| T-10 | B-06 | `test_transposed_digits_never_autolink` |
| T-11 | B-07 | `test_local_day_boundary_2330` |
| T-12 | B-07, B-01 | `test_undated_note_time_unknown`, `test_unknown_time_has_no_bounds` |
| T-13 | B-04 | `test_frozen_sensor_flatline`, `test_stop_event_not_gap` |
| T-14 | B-02 | `test_duplicate_ts_not_averaged`, `test_split_preserves_duplicate_rows` |
| T-15 | B-09 | `test_undeclared_provenance_no_corroboration` |
| T-16 | A-06, A-02, A-07, A-10 | `hostile[bomb_png, png_60mpx_rejected]`, `test_pdf_huge_mediabox_render_refused` |
| T-17 | A-07 | `test_300mb_rejected_streaming`, `test_chunked_upload_without_length_capped` |
| T-18 | A-07, C-09 | `hostile[html_as_pdf, svg, pdf_renamed_csv, html_renamed_txt]`, `test_original_download_headers` |
| T-19 | A-07 | `hostile[traversal_name]` |
| T-20 | A-08, A-07 (no PDFium in the API); P1-09 | `test_api_never_imports_pdfium`, `hostile[pdf_51_pages]`, `fuzz_mutated_pdf_smoke` (P1) |
| T-21 | A-06 | `test_exif6_bbox_alignment_and_no_gps` |
| T-22 | C-09, C-12 | `e2e_xss_fixture_no_dialog_under_csp` (+ tooltip) |
| T-23 | D-05 | `test_spoofed_reviewer_field_422`, `test_viewer_decision_403` |
| T-24 | D-05; P2-01 | `test_20_parallel_decisions_one_wins` (SQLite; Postgres in P2) |
| T-25 | D-05 | `test_cross_case_claim_404` |
| T-26 | A-09 | `test_cross_origin_form_post_403`, `test_login_requires_csrf_header` |
| T-27 | D-03, D-04, C-12 | `test_trigger_aborts_update`, `test_chain_verify_detects_edit`, `test_snapshot_hash_mismatch`, `e2e_byte_flip_evidence_changed` |
| T-28 | A-08 | `test_kill_mid_build_marks_stale_then_rebuilds`, `test_parent_restart_kills_orphan_child`, `test_child_oom_marks_failed_not_running` |
| T-29 | C-09, C-12 | `e2e_all_panels_same_version` |
| T-30 | D-10 | `test_no_magic_literals_in_engine` |
| T-31 | D-09 | `test_eval_report_has_pushed_config_commit` (config + engine + lock) |
| T-32 | B-09, C-08 | `test_ui_uncalibrated_label` |
| T-33 | D (owner), P1-03 | `test_network_off_build_succeeds`; `test_groq_outage_build_completes_rules_only_under_60s` (P1) |
| T-34 | D-05; P1-09 | `test_parallel_eval_runs_one_proceeds` |
| T-35 | P5 | — (accepted risk) |
| T-36 | P2-03, P3-09 (design + runbook); P5 | `test_bucket_lock_mode_matches_policy` |
| T-37 | A-01, D-11; P1-09, P1-11, P2-09 | `test_lockfiles_in_sync`, `make audit`, image scan |
| T-38 | B-07 | `test_client_timestamp_ignored` |
| **T-39** Groq key leak | A-01, A-08, A-10, D-11; P1-03, P1-11 | `test_no_secret_in_logs_or_responses`, `test_dockerignore_excludes_secrets`, `test_parse_child_env_has_no_groq_key`, image grep, gitleaks pre-commit (CI from P1-11) |
| **T-40** Egress without consent | A-01 (P0 default); P1-03, P1-04, P2-09 | `test_groq_disabled_by_default_no_egress`, `test_groq_base_url_must_be_allowlisted_https`, `test_egress_denied_except_allowlist` |
| N-1 | D-03 | `test_no_update_paths_status_derived` |
| N-2 | D-11 | Pre-demo checklist (anchor pushed) |
| N-3 | B-03 | `test_thin_history_uses_model_pool`, `test_conformal_oracle` |
| N-4 | D-07 | `test_baseline_output_generated` |

### H.5 Security floor controls (ADR-15) → tasks and tests
| Control | Task | Test |
|---|---|---|
| S1 | A-09, A-01 | `test_spoofed_reviewer_field_422`, `test_compose_ports_loopback_only`, `test_lan_without_tls_refuses_start`, `test_login_unknown_user_constant_work` |
| S2 | A-09 | `test_write_requires_json_and_csrf`, `test_foreign_host_header_400` |
| S3 | D-05 | `test_20_parallel_decisions_one_wins`, `test_supersede_requires_senior` |
| S4 | A-08 | `test_timeout_kills_tesseract_grandchild`, `test_parent_restart_kills_orphan_child` |
| S5 | D-03, D-04, D-11 | `test_trigger_aborts_update`, `test_integrity_verifies_stored_bytes`, anchor checklist |
| S6 | A-07, A-02, A-06 | `test_300mb_rejected_streaming`, `hostile[pdf_51_pages]`, `test_upload_refused_when_disk_below_1gb` |
| S7 | C-09, A-07 | `test_original_download_headers` |
| S8 | C-09 | `test_html_responses_have_csp_header_with_frame_ancestors`, eslint rules |
| S9 | D-05 | `test_cross_case_claim_404` |
| S10 | A-01, A-10 | `test_logs_contain_no_document_text`, `test_groq_disabled_by_default_no_egress` |
| S11 | A-01, D-11 | `test_image_nonroot_readonly` |
