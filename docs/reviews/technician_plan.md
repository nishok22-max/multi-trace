# TRACE — Technician's Implementation Plan

| Field | Value |
|---|---|
| Author | The Technician (tech lead) |
| Inputs | `TRACE_PRD.md` v1.2, `system-design/SYSTEM_DESIGN.md`, `DECISIONS.md` (ADR-01..15), `HARDENING.md` (T-01..T-38, N-1..N-4), `debate/r3_judge.md` (binding; hour ledger Part 3) |
| Scope | **Part I:** MVP = 36-hour hackathon P0, 4 people. **Part II:** turning the MVP into a **single-plant pilot** (one plant, ~40 machines, single tenant, VM/on-prem). **Part III:** optional multi-tenant SaaS outline. |
| Date | 2026-11-20 |
| Status | Ready for QA review. The Tester derives the test plan from the task IDs and named tests in §D and §H. |

## 0. Binding user decisions that override the design docs

| # | Decision | Where the docs change |
|---|---|---|
| U-A | After the MVP the product is a **plant pilot**: one plant, ~40 machines, single tenant, VM/on-prem. It uses Postgres (same append-only triggers plus REVOKE), S3-compatible storage with object lock (MinIO), SSO/OIDC, LLM/VLM enabled, backups and monitoring. Multi-tenant SaaS (PRD §15 Part C) is only a designed path (§P5). | PRD §15 and ADR-13 become P5. The pilot is §E. |
| U-B | **pypdfium2** (Apache-2.0 / BSD-3) replaces PyMuPDF **from h0**. This closes U-1 and removes the AGPL disclosure. | ADR-06, SYSTEM_DESIGN §15, PRD §14.1. It costs about +2.5 h in A's column (§D). |
| U-C | Dev environment: **Docker Desktop (WSL2)** builds the demo image. The fast dev loop uses native `uv` + `npm` on Windows. | SYSTEM_DESIGN §18 |
| U-D | AI provider for P1 and the pilot is **Groq** (OpenAI-compatible) behind `LlmProposer`, plus a Groq vision model as the second photo reader (`VlmReader`). The MVP makes **zero** network calls. Groq is opt-in through config. Responses are recorded into the extraction cache, the key comes only from `.env` (`GROQ_API_KEY`), and a data-egress notice plus a redaction hook run before any document text leaves the box. | ADR-06 P1, T-07/T-08/T-33 |
| U-E | The stack is fixed: Python 3.11 + FastAPI + Pydantic v2; Astro (static) + Tailwind + React islands. | — |

All other judge verdicts stand unchanged. These include the conformal envelope, `sensor_native` telemetry, the killable child process, SQLite in P0, status derived from events, the pushed anchor, 409 only on already-decided or evidence-changed, and per-user argon2id login.

---

# PART I — MVP (36 h, P0)

## A. Coding strategy

### A.1 Fast delivery
1. **Contracts first, frozen at h8.** B owns `trace_core/models/`. At h8 the models are tagged `contracts-v1`, and the following are exported and committed:
   - `schemas/*.json` (Pydantic JSON Schema);
   - `openapi.json`;
   - `frontend/src/lib/api/schema.d.ts` (`openapi-typescript`).

   After h8, any change needs a **Contract Change Request**: a one-line post in the team channel that B approves, then `make contracts`. `make contracts-check` regenerates and runs `git diff --exit-code` in pre-commit, so silent drift is impossible.
2. **Walking skeleton at h10.** One text claim (C-17) and one sensor claim (S-88 against a real envelope) go through gate → snapshot → API → a conflict card in the browser. Everything after that thickens a path that already works end to end.
3. **Fakes before adapters.** Every port ships with an in-memory fake at h8:
   - `FakePdfReader` returns a fixture `PageText`;
   - `FakeOcr`, `FixedClock`, `MemClaimStore`, `MemBlobStore`, `FakeLlm` and `DictExtractionCache`.

   B and C never wait for A's real readers. A's adapters must pass the **same port contract tests** as the fakes (`tests/unit/ports/test_<port>_contract.py`, parametrised over fake and real).
4. **Goldens drafted before code.** The expected outcome table for Demos 0–6 is written at h8 with the numeric cells left `⟨computed⟩`. After the h0 reality check and the first green build, `make golden-bless` pins the computed values and `manifest_hash`.
5. **Trunk-based development.** Branches live under 4 h. PRs stay under about 300 lines and get one reviewer, who is never the author's own pair on the correctness floor (B's PRs are reviewed by D). Standups are 10 minutes at h2, h6, h10, h14, h20, h24, h28 and h32. A task that overruns its estimate by 50% is escalated at the next standup, and the buffer owner decides.
6. **Seed data comes from scripts, not a word processor.** PDFs are generated with `reportlab` (dev-only, BSD) and gauge photos with Pillow, plus 1–2 real phone photos. Seeds are therefore reproducible and hash-stable.
7. **Stretch is flag-gated.** `TRACE_FEATURE_SSE`, `TRACE_LLM_MODE`, `TRACE_VLM_MODE` and `TRACE_LOAD_BINS` all default to off. Stretch work starts only at the h26 gate, and only from buffer hours.

### A.2 Low latency (NFR-7: build < 60 s, proof < 1 s, decision → card < 2 s)
- **Serialisation:** `orjson` through `default_response_class=ORJSONResponse`. Snapshots are stored and served as **pre-serialised bytes**.
- **Snapshot cache:** `SnapshotLRU` is an `OrderedDict` keyed `(case_id, version, view)` and capped at 256 entries or 64 MB. Fill happens once, after the snapshot sha256 is verified. Versioned reads are dictionary lookups.
- **HTTP caching:** `ETag = "<manifest_hash>"`. `If-None-Match` returns 304 before the snapshot is touched. Versioned JSON is `private, max-age=31536000, immutable` with `Vary: Cookie`. `latest`, `recheck` and all writes are `no-store`.
- **Precomputed projections:** the story, timeline and review views are computed once inside `snapshot()` and stored as separate views, so no request ever computes them.
- **Proof path:**
  - page PNGs are cached by `(source_sha, page, dpi)`;
  - recheck re-hashes only the cited artifact (page text, crop, CSV line or Arrow slice) plus one streaming sha256 of the source;
  - tables return a ±25-row window;
  - the sensor chart uses ECharts with LTTB sampling.
- **Telemetry:** one Parquet file per machine. Reads use `pyarrow.dataset` with a timestamp predicate, so only the case window ±3 days and the quiet-day columns are loaded.
- **Decision re-run:** link → gate → trust → snapshot over cached extracted claims inside one `BEGIN IMMEDIATE`. There is no parsing and no OCR. Pairs come from a per-(entity, attribute) interval sweep, never all-pairs.
- **SQLite:** `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; mmap_size=268435456; foreign_keys=ON`.
- **Budgets are measured.** Per-stage ms is written to the `builds` row. Playwright asserts the 1 s and 2 s budgets, and `tests/api/test_perf_budget.py` asserts the build is under 60 s inside the image.

### A.3 Reliability
- Builds run in a killable spawn child: 180 s wall time, `RLIMIT_AS` 2 GiB on Linux, a heartbeat every 5 s, and a startup sweep that marks stale builds. The partial unique index allows one build per case, and `build_key` makes builds idempotent.
- **Fail closed.** Anything unknown becomes "can't be compared" or "we can't tell". Every `match` on `Outcome`, `PointerKind`, `LinkStatus` and `UnitStatus` ends in `assert_never`, so `mypy --strict` proves the match is exhaustive.
- **Determinism:**
  - content-addressed IDs;
  - JCS hashing with fixed 6-dp float strings;
  - `PYTHONHASHSEED=0`;
  - explicit sort keys and `quantile(method="linear")`;
  - `RELATIVE_BASE` for dateparser;
  - replay reads only the extraction cache, and a miss is an error.
- **Goldens run in pre-commit from h16.** Hypothesis properties run in `make check`.
- `GET /healthz` (process) and `GET /readyz` (DB writable, blob dir writable, Tesseract present, free disk > 1 GB) back the Docker `HEALTHCHECK`.

### A.4 Modularity
- **Hexagonal layout.** `trace_core` is pure. Its only I/O goes through `Protocol` ports passed in an `EnginePorts` bundle.
- **`.importlinter` contracts:**
  1. `trace_core` is independent of `trace_adapters`, `trace_api`, `trace_worker` and `trace_eval`.
  2. Layers run `trace_api` → `trace_worker` → `trace_adapters` → `trace_core`.
  3. `trace_eval` may import `trace_core` and `trace_adapters`, never `trace_api`.
  4. `trace_core.compare` must not import `trace_core.read`. The gate sees claims, never parsers.
- **Config is one bundle.** `config/*.yaml` is validated by `ConfigBundle` (Pydantic, `extra="forbid"`), and `config_hash = sha256(JCS(bundle))`.
- Each resource has its own router, and each pipeline stage is a top-level function. Stage names equal the future OTel span names and Temporal activity names.

### A.5 Security
- The security floor S1–S11 from ADR-15 is implemented in full (task map in §D).
- **Lint rules as guard rails** (ruff):
  - `S` (bandit) is on;
  - `DTZ` bans naive datetimes (T-38);
  - `TID251` banned-api blocks `datetime.datetime.now`, `time.time`, `os.environ`, `open` and `requests` inside `trace_core`;
  - `numpy.mean`, `numpy.average` and `statistics.mean` are banned everywhere **except** `trace_core/read/sensor.py`, where daily means of a single series are allowed. This backs NFR-6 with a lint rule as well as a test.
- **Secrets:**
  - `pydantic-settings` with `SecretStr`;
  - `.env` is git-ignored and Docker-ignored and is passed at runtime with `--env-file`, never baked into the image;
  - a `gitleaks` pre-commit hook carries a custom rule for `gsk_[A-Za-z0-9]{20,}` (Groq);
  - a structlog processor drops the keys `quote`, `text`, `page_text`, `ocr_text`, `prompt`, `completion` and `authorization`, and regex-scrubs key patterns.
- **Frontend:** eslint `react/no-danger` is an error. The CSP uses build-time hashes. There is no pdf.js and no CSV export.
- **Supply chain (P0):** `uv.lock` and `package-lock.json` are committed, the base images are digest-pinned, and the apt Tesseract version is pinned.

### A.6 Typing strictness
- `mypy --strict` with the `pydantic.mypy` plugin runs on `trace_core`, `trace_api` and `trace_worker`. Adapters and eval run `--strict` minus `disallow-any-generics` for pandas.
- Pydantic: `BaseModel` subclasses use `ConfigDict(frozen=True, extra="forbid")`. Core-internal models add `strict=True`. API input models are lax only where JSON forces it, such as datetime strings.
- IDs are `NewType` or `Annotated[str, StringConstraints(pattern=...)]`: `ClaimId` `^clm_[0-9a-f]{24}$`, `Sha256` `^[0-9a-f]{64}$`, `CaseId` `^[a-z0-9-]{3,64}$`. The path-ID regex also closes T-19.
- TypeScript runs with `"strict": true, "noUncheckedIndexedAccess": true, "exactOptionalPropertyTypes": true`. `tsc --noEmit` on the generated `schema.d.ts` is the contract test.

### A.7 Windows and Docker practicalities (decision U-C)
- **`.gitattributes`:**
  - `* text=auto eol=lf`;
  - `seed/** -text`, so CSV and PDF bytes are never CRLF-converted. Converting them would change `row_sha256` and the source hashes and break every golden.
- **`tzdata`** is a runtime dependency, because Python's `zoneinfo` on Windows has no system time-zone database (needed for `Asia/Kolkata`).
- **Tesseract on Windows:** `winget install UB-Mannheim.TesseractOCR`, with the path in `TRACE_TESSERACT_CMD`. The Windows build's output can differ from the pinned Linux version, so native dev runs OCR in `replay` mode against `seed/cache/`. `make record-cache` runs **inside the image** and is the only way new OCR artifacts are recorded.
- **pypdfium2** ships PDFium binaries in its Windows and manylinux wheels, so there is no system dependency.
- **Spawn and memory caps:** `multiprocessing` spawn is native on Windows. `RLIMIT_AS` is skipped on Windows, and the log states "no memory cap" once at startup.
- **Docker Desktop:** clone the repo inside the WSL2 filesystem (`\\wsl$`), not `/mnt/c`, for bind-mount speed. Use a named volume `trace-data` for `data/`. `make` runs from Git Bash or WSL. Every Makefile target is a one-liner around `uv run python -m tools.<task>` or `npm run <script>`, so PowerShell users can run the same command directly.

---

## B. Repository scaffold, Makefile, dependencies

### B.1 Directory tree
```
trace/
├── .gitattributes  .gitignore  .dockerignore  .editorconfig
├── .env.example                 # GROQ_API_KEY=, TRACE_LLM_MODE=off, TRACE_VLM_MODE=off, TRACE_LLM_EGRESS_ACK=false,
│                                # TRACE_GROQ_BASE_URL=https://api.groq.com/openai/v1, TRACE_GROQ_TEXT_MODEL=,
│                                # TRACE_GROQ_VISION_MODEL=, TRACE_TESSERACT_CMD=, TRACE_LAN=0, TRACE_DATA_DIR=./data
├── .pre-commit-config.yaml  .importlinter
├── Makefile  Dockerfile  compose.demo.yml
├── LICENSE (Apache-2.0)  THIRD_PARTY_NOTICES.md (PDFium BSD-3, Tesseract Apache-2.0, MS dataset terms)
├── backend/
│   ├── pyproject.toml  uv.lock
│   ├── trace_core/                       # PURE
│   │   ├── models/  base.py time.py evidence.py claims.py records.py case.py config.py api_io.py eval.py
│   │   ├── ports.py  canonical.py (JCS, 6dp)  ids.py  errors.py  build.py  rerun.py
│   │   ├── read/        text_rules.py numunit.py dates.py mentions.py text.py hidden_text.py
│   │   │                table.py sensor.py image.py llm_verify.py (P1 slot)
│   │   ├── normalise/   units.py entities.py time.py envelopes.py gaps.py sensor_state.py
│   │   ├── review/      holds.py status.py (derived from review_events)
│   │   ├── compare/     pairs.py gate.py quantifiers.py tolerance.py conflicts.py
│   │   ├── score/       confidence.py independence.py calibration.py (P1 slot)
│   │   └── snapshot/    records.py manifest.py projections.py (story, timeline, review views)
│   ├── trace_adapters/
│   │   ├── sqlite/      store.py migrate.py   blob_fs.py   pdfium_reader.py   tesseract_ocr.py
│   │   ├── extraction_cache.py  clock.py  telemetry_split.py  llm_fake.py  redactor.py
│   │   └── groq/        llm_groq.py vlm_groq.py   (P1; never imported when mode=off)
│   ├── trace_api/
│   │   ├── main.py settings.py deps.py problems.py logging.py
│   │   ├── security/    sessions.py passwords.py csrf.py csp.py upload_limits.py magic.py headers.py
│   │   ├── routers/     auth cases sources builds versions claims review entities eval health
│   │   └── services/    build_service.py decision_service.py snapshot_lru.py evidence_render.py recheck.py
│   ├── trace_worker/    build_runner.py sweep.py
│   ├── trace_eval/      injector.py faults/ baselines/{tfidf,fusion,nogate}.py metrics.py holdout.py report.py
│   ├── tools/           smoke.py h0_reality.py gen_seed_pdfs.py gen_gauges.py fetch_dataset.py seed_users.py
│   │                    seed_build.py export_contracts.py anchor.py record_cache.py
│   ├── config/          case.yaml ontology.yaml phrases.yaml aliases.yaml tolerances.yaml gauges.yaml
│   │                    shifts.yaml envelope.yaml gate.yaml llm.yaml
│   ├── migrations/sqlite/ 001_schema.sql 002_append_only_triggers.sql 003_indexes.sql
│   └── tests/  unit/ ports/ golden/ properties/ hostile_corpus/ authz/ api/ eval/ fixtures/
├── frontend/
│   ├── package.json package-lock.json astro.config.mjs tsconfig.json eslint.config.js
│   ├── scripts/csp-hash.mjs             # fallback CSP hasher if Astro's built-in CSP is unavailable
│   └── src/ pages/ islands/ components/ lib/{api/,query/,geom/} styles/
├── e2e/            playwright.config.ts  specs/{proof,decision,tamper,xss,versions}.spec.ts
├── seed/           dataset/ (fetched, not committed if licence forbids)  authored/{reports,photos,logs}
│                   labels.yaml  cache/ (recorded OCR artifacts)  faults/{dev,holdout}/  credentials.local.txt (ignored)
├── schemas/        exported JSON Schema (generated, committed)
├── data/           runtime volume (gitignored)
└── anchors/demo_roots.txt
```

### B.2 Makefile targets
| Target | Does |
|---|---|
| `setup` | `uv sync`, `npm ci`, `pre-commit install` |
| `smoke` | Checks Tesseract version, pypdfium2 render + char-box round-trip on a seed PDF, `zoneinfo('Asia/Kolkata')`, SQLite trigger abort, write access |
| `h0` | `tools.h0_reality`: M-21 on 14 Mar T_D vs T\*, error rows, quiet-day counts histogram per machine, written to `data/h0_report.json` |
| `contracts` / `contracts-check` | Export JSON Schema + OpenAPI → `openapi-typescript`; the check variant fails on diff |
| `lint` / `type` / `imports` | ruff + eslint / mypy + `tsc --noEmit` / `lint-imports` |
| `test-fast` / `test` | Unit + ports + golden / everything except e2e |
| `golden` / `golden-bless` | Run / re-pin goldens (bless requires `CONFIRM=1` and prints the diff) |
| `props`, `hostile`, `authz` | Test subsets |
| `e2e` | Playwright against the built image under the enforcing CSP |
| `check` | lint + type + imports + contracts-check + test |
| `seed` | Fetch the dataset, generate authored seed, seed users (credentials written to the ignored file) |
| `record-cache` | Inside the image only: fresh OCR → `seed/cache/` |
| `demo` | seed → build Demos 0–6 → print the manifest hashes |
| `replay-verify` | Rebuild every demo version from the cache and compare `manifest_hash` |
| `eval-dev` / `eval-holdout` | Holdout refuses unless `config_hash` is in a commit that exists on the remote (`git branch -r --contains`) |
| `anchor` | Append roots to `anchors/demo_roots.txt`, commit, **push** |
| `image` / `run-docker` / `run-native` | `docker build -t trace:$(git sha)` / run with the volume, `127.0.0.1` / `uv run trace-api` |

### B.3 Backend dependencies (`backend/pyproject.toml`; ranges shown, **exact pins at h0 via `uv lock`**)
| Group | Package | Range | Why |
|---|---|---|---|
| runtime | fastapi | `>=0.115,<1.0` | API |
| | uvicorn[standard] | `>=0.32,<1.0` | Server |
| | pydantic / pydantic-settings | `>=2.9,<3` / `>=2.6,<3` | Models, settings, SecretStr |
| | orjson | `>=3.10,<4` | Fast JSON |
| | structlog | `>=24.4` | JSON logs |
| | pandas / pyarrow / numpy | `>=2.2,<3` / `>=17,<22` / `>=1.26,<3` | Tables, Parquet |
| | pint | `>=0.24,<1` | Units (authored only) |
| | rapidfuzz | `>=3.10,<4` | Entity matching |
| | dateparser / python-dateutil / tzdata | `>=1.2,<2` / `>=2.9` / `>=2024.2` | Time (tzdata for Windows) |
| | rfc8785 | `>=0.1.4` | JCS |
| | **pypdfium2** | `>=4.30,<5` (verify v5 API at h0) | PDF text, char boxes, render |
| | pytesseract / Pillow | `>=0.3.13` / `>=11.0,<12` | OCR, EXIF, crops |
| | argon2-cffi | `>=23.1` | Passwords |
| | python-multipart | `>=0.0.18` | Uploads (post-CVE) |
| | PyYAML | `>=6.0.2` | Config |
| eval | scikit-learn | `>=1.5,<2` | Isotonic/Platt, TF-IDF baseline |
| dev | pytest, pytest-xdist, pytest-cov, hypothesis, httpx | `>=8.3`, `>=3.6`, `>=5`, `>=6.112`, `>=0.27` | Tests |
| | mypy, ruff, import-linter, pre-commit | `>=1.13`, `>=0.7`, `>=2.1`, `>=4.0` | Static checks |
| | reportlab | `>=4.2` | Seed PDF generation only |
| llm (P1, optional extra) | openai | `>=1.50,<2` | OpenAI-compatible client pointed at Groq |
| pilot (P2, optional extra) | psycopg[binary,pool], boto3, authlib, opentelemetry-sdk, opentelemetry-instrumentation-fastapi, prometheus-client | `>=3.2`, `>=1.35`, `>=1.3`, `>=1.27`, `>=0.48b0`, `>=0.21` | Pilot platform |
| P1 tools | schemathesis, pip-audit, cyclonedx-bom, openpyxl, defusedxml | `>=3.36`, `>=2.7`, `>=5`, `>=3.1.5`, `>=0.7.1` | Hardening, XLSX |

System dependencies are pinned in the Dockerfile:
- `python:3.11-slim-bookworm@sha256:<digest>`;
- `tesseract-ocr=5.3.0-*` and `tesseract-ocr-eng` (the exact version string is recorded into every manifest);
- `node:20-bookworm-slim@sha256:<digest>` for the frontend stage.

### B.4 Frontend dependencies (`frontend/package.json`; **`package-lock.json` committed at h0**)
| Package | Range | Note |
|---|---|---|
| astro | `^5.9` | `output:'static'`; the experimental CSP hashing is used if present, otherwise `scripts/csp-hash.mjs` |
| @astrojs/react | `^4.2` | Islands, `client:only="react"` |
| react, react-dom | `^18.3.1` | 18 for `echarts-for-react` peer compatibility |
| tailwindcss, @tailwindcss/vite | `^4.0` | Tailwind 4 through the Vite plugin |
| @tanstack/react-query | `^5.59` | Version-keyed queries |
| echarts, echarts-for-react | `^5.5`, `^3.0.2` | Sensor chart, timeline, reliability diagram |
| openapi-fetch, openapi-typescript | `^0.13`, `^7.4` | Typed client |
| typescript | `^5.6` | Strict |
| eslint, typescript-eslint, eslint-plugin-react, eslint-plugin-react-hooks | `^9`, `^8`, `^7.37`, `^5` | `react/no-danger: error` |
| vitest, @testing-library/react | `^2.1`, `^16` | Unit tests of `geom/` (bbox transforms) and `textSlice` |
| @playwright/test | `^1.48` | e2e under the enforcing CSP |

---

## C. Interfaces

### C.1 Pydantic core models (`trace_core/models/`)
All models are `frozen=True, extra="forbid"`. Times are `UtcStr` (fixed-width `YYYY-MM-DDTHH:MM:SSZ`).

| Model | Key fields |
|---|---|
| `Interval` | `start: UtcStr`, `end: UtcStr` (half-open; validator `start < end`), `granularity: Literal[hour, shift, day, unknown]`, `resolved_from` |
| `ObservedTime` | `at: UtcStr \| None`, `basis: Literal[document_date, sensor_timestamp, ingest_time]` (**`file_timestamp` is not a legal value for valid time**) |
| `Temporal` | `valid_time: Interval`, `observed_time: ObservedTime`, `timezone_original: str` |
| `Candidate` | `entity_id`, `score`, `features: dict[str, float]`, `reasons: list[str]`, `vetoed: bool` |
| `Subject` | `mention`, `entity_id \| None`, `link_status: resolved\|ambiguous\|unresolved`, `candidates: list[Candidate]`, `mention_key: MentionKey(source_sha256, locator)` |
| `EvidencePointer` | A discriminated union on `kind`, made of the five types below |
| `TextSpanPointer` | `source_id, sha256, page, line?, page_text_sha256, char_start, char_end, quote, quote_sha256, bbox_pt?, bbox_px?` |
| `ImageRegionPointer` | `source_id, sha256 (derived image), bbox[x,y,w,h], coord_space="oriented_px", reader: ocr\|vlm, read_text, reread_text?, crop_sha256` |
| `TableCellPointer` | `source_id, sha256, row (1-based line), column, raw_value, row_sha256, sheet?` |
| `SensorWindowPointer` | `source_id, series_id, channels, start, end, n_points, expected_points, statistic, granularity, window_sha256, envelope_id?` |
| `HumanDecisionPointer` | `decision_id, user_id, display_name, role, reason, base_version, shown_evidence_hash, timestamp` |
| `Method` | `extractor, extractor_version, rule_id, llm_used: bool, model_id?` |
| `Confidence` | `value, calibrated: bool, components: {extractor, entity_link, time, unit, reliability_adj, corroboration}, calibration_fit_id?` |
| `ClaimRecord` | `claim_id, label?, case_id, claim_type: extracted\|inferred, statement, subject, attribute, value, value_type, unit, unit_status: known\|unknown\|sensor_native\|not_applicable, normalized_value, normalized_unit, temporal, modality, evidence?, derived_from, method, confidence, supersedes?, record_hash`. Validators: inferred ⇒ non-empty `derived_from` + `rule_id`; extracted ⇒ evidence required; `sensor_native` ⇒ `normalized_*` is None |
| `Source` | `source_id, case_id, modality, sha256, origin, ingested_at, derived_from_sources, coverage_period?: Interval, synthetic: bool, mime, size` |
| `Entity` / `Event` / `Measurement` / `Relation` | As in PRD §9.2. These are **views** built from claims in `projections.py` |
| `Envelope` | `envelope_id, machine, scope, statistic="robust_max_z", granularity="day", quiet_days: list[QuietDay(date, reasons)], n, med, mad, T_star, pooled: none\|t_star_model\|model_level, degenerate_channels, params, partition_hashes` |
| `GateCheck` | `n: 1..6, name, passed: bool, detail` |
| `ComparisonRecord` | `comparison_id, claim_a, claim_b (sorted), checks: list[GateCheck], outcome: disagree\|agree\|cannot_compare\|cannot_tell, reason, config_hash, record_hash` |
| `ConflictRecord` | `conflict_id, comparison_ids, sides, supporting_context, magnitude, averaged: Literal[False]` (no status field) |
| `ReviewItem` | `review_id, type: ambiguous_entity\|reader_disagreement\|implausible_value\|hidden_text\|envelope_drift\|low_confidence\|unknown_unit\|llm_only_interpretation, claim_ids, candidates?, evidence_hash, opened_at` |
| `ReviewEvent` | `event_id, review_id, kind: opened\|decided\|escalated\|stale\|explained, decision_id?, at` |
| `DecisionRequest` (API in) | `choice: str, reason: constr(min_length=15), base_version: int, shown_evidence_hash: Sha256, supersedes?: DecisionId`. `extra="forbid"`, so a `reviewer` field returns 422 |
| `ConfigBundle` | `case(plant_tz, shifts), ontology(phrases with quantifier ∀/∃ and scope), aliases, tolerances, gauges(range, resolution), envelope(α, ±3 d, policy), gate(τ_link, δ_link, τ_review, λ), llm(mode, model ids, budgets)` → `config_hash` |
| `CaseManifest` | `case_id, scope, window, sources: list[Source], parent_version?` |
| `CaseVersion` | `case_id, version, parent_manifest_hash, manifest_hash, config_hash, engine_sha, lockfile_hash, tesseract_version, claims, comparisons, conflicts, envelopes, review_items, review_events, views: {story, timeline, review}` |
| `BuildStatus` | `build_id, status, heartbeat_at, stage_ms: dict, counters: dict` |
| Read artifacts | `PageText(text, page_text_sha256, char_boxes: list[BoxPt], font_sizes: list[float\|None], generated: list[bool], cropbox, rotation)`, `OcrResult(words: list[OcrWord(text, conf, bbox)])`, `VlmReading`, `ProposalBatch` |
| API out | `Story(steps: 5×StoryStep)`, `TimelineEntry`, `EvidenceRender` (union per kind), `RecheckResult(match, source_sha_ok, value_ok)`, `IntegrityResult`, `EvalReport`, `Problem` (RFC 9457) |

### C.2 Ports (`trace_core/ports.py`, `typing.Protocol`)
```text
BlobStore:        put(stream: BinaryIO, *, max_bytes: int) -> BlobRef
                  open(sha256: Sha256) -> BinaryIO ;  exists(sha256) -> bool
PdfReader:        page_count(pdf: bytes) -> int
                  page_text(pdf: bytes, page: int) -> PageText
                  render_png(pdf: bytes, page: int, dpi: int = 150) -> bytes
                  pt_to_px(page_meta: PageMeta, box: BoxPt, dpi: int) -> BoxPx
OcrReader:        read_words(png: bytes, cfg: OcrConfig) -> OcrResult
                  reread_region(png: bytes, bbox: BBox, cfg: RereadConfig) -> OcrResult
VlmReader (P1):   read_region(crop_png: bytes, prompt_id: str, gauge: GaugeSpec) -> VlmReading
LlmProposer:      propose(doc: RedactedDocument, prompt_id: str) -> ProposalBatch
Redactor:         redact(text: str) -> RedactedDocument   # text + reversible span map; numbers/units never redacted
ExtractionCache:  get(key: CacheKey) -> bytes | None ; put(key: CacheKey, artifact: bytes) -> Sha256
                  mode: Literal["record", "replay"]        # CacheKey = (input_sha, extractor_id, version, params_hash)
Clock:            now_utc() -> datetime
ClaimStore:       append(case_id, records: Sequence[EvidenceRecord]) -> None      # no update/delete methods exist
                  put_version(v: CaseVersion, members: VersionMembers) -> None
                  get_version(case_id, v) -> VersionHeader ; latest(case_id) -> int | None
                  load_claims(case_id, v) -> list[ClaimRecord] ; review_events(case_id) -> list[ReviewEvent]
                  append_decision(case_id, decision: ClaimRecord, event: ReviewEvent) -> None
EnginePorts:      dataclass(blobs, pdf, ocr, cache, clock, llm, redactor, vlm | None)
```
Operational stores (`UserStore`, `SessionStore` and `BuildStore`) live in `trace_api` and `trace_adapters`, not in the core.

### C.3 Stage functions (pure; future Temporal activities)
```text
read_text(src, blob, cfg, ports)            -> ReadResult(claims, review_items, artifacts)
read_table(src, blob, cfg)                  -> ReadResult
read_image(src, blob, cfg, ports)           -> ReadResult
split_telemetry(src, blob)                  -> list[DerivedSource]   # adapter-side, Parquet per machine
read_sensor(partitions, case, cfg)          -> SensorWindows         # day windows per channel, duplicates → gap
normalise_units(claims, ontology, tol)      -> list[ClaimRecord]
resolve_entities(claims, registry, decisions, cfg) -> tuple[list[ClaimRecord], list[ReviewItem]]
resolve_time(claims, case_cfg)              -> list[ClaimRecord]
learn_envelopes(partitions, events, sources, case, cfg) -> list[Envelope]   # raises LogCoverageError
detect_gaps(windows, events, envelopes, cfg)-> list[ClaimRecord]
derive_sensor_state(windows, envelopes, cfg)-> list[ClaimRecord]   # S-88 (day) + S-88.1 (hour child)
apply_holds(claims, review_items, events, decisions) -> tuple[eligible, held]
candidate_pairs(eligible, ontology)         -> Iterator[tuple[ClaimRecord, ClaimRecord]]
gate(a, b, ctx: GateContext)                -> ComparisonRecord        # total: exactly one outcome
group_conflicts(comparisons, claims)        -> list[ConflictRecord]
score(claims, comparisons, provenance, cfg) -> list[ClaimRecord]
snapshot(case, parent, parts, hashes, clock)-> CaseVersion
build_case(manifest, config, decisions, ports) -> CaseVersion
rerun_after_decision(parent: CaseVersion, decisions, config, clock) -> CaseVersion  # link→gate→trust→snapshot
```

### C.4 API routers (`/api/v1`; all case-scoped through `resolve_case_and_authorize`)
| Router | Routes |
|---|---|
| `health` | `GET /healthz`, `GET /readyz` (outside `/api/v1`, no auth, no data) |
| `auth` | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| `cases` | `GET /cases`, `POST /cases` (ingestor), `GET /cases/{cid}/latest` (307, no-store) |
| `sources` | `POST /cases/{cid}/sources` (ingestor, multipart, streaming caps), `GET /cases/{cid}/sources/{sid}/original` (attachment, nosniff, `CSP: sandbox`) |
| `builds` | `POST /cases/{cid}/build` (202), `GET /cases/{cid}/builds/{bid}` |
| `versions` | `GET /cases/{cid}/versions/{v}/{state\|story\|timeline\|claims\|comparisons\|conflicts\|review\|manifest\|integrity}`, `POST …/replay` (evaluator) |
| `claims` | `GET /cases/{cid}/claims/{id}`, `GET …/evidence`, `GET …/evidence/page.png`, `GET …/evidence/crop.png`, `POST …/recheck` |
| `review` | `POST /cases/{cid}/review/{rid}/decision` (reviewer; senior for `supersedes`) |
| `entities` | `GET /cases/{cid}/entities/{eid}/envelope` |
| `eval` | `POST /eval/run` (evaluator, one in flight), `GET /eval/report` |
| P1 `events` | `GET /cases/{cid}/events` (SSE, notice-only) |

### C.5 Frontend
- **Pages and islands** (one `client:only="react"` island per page):
  - `/login` → `LoginForm`
  - `/` → `CaseList`
  - `/case?id=` → `CaseWorkspace`
  - `/case/expert?id=` → `ExpertView`
  - `/review` → `ReviewQueue`
  - `/eval` → `EvalDashboard`
- **Components:**
  - layout and status: `SignedInAs`, `VersionBadge`, `IntegrityBadge`, `RecheckBadge`, `SyntheticBadge`, `UncalibratedLabel`, `OutcomeBadge` (icon plus a text label, so colour is never the only signal), `BuildStatusPoller`;
  - story and conflicts: `StoryStep` ×5, `ConflictCard`, `GateTable`;
  - evidence: `EvidencePanel`, which dispatches to `RegionViewer`, `TextSpanView`, `TableWindow` or `SensorChart`;
  - timeline and review: `Timeline`, `DecisionPanel`, `CandidateList`;
  - expert view: `ClaimsTable`, `ComparisonsTable`, `EnvelopeView`, `ReplayButton`, `StageTimings`;
  - eval: `ReliabilityDiagram`, `FaultPRTable`.
- **Library:**
  - `lib/api/client.ts`: `openapi-fetch` plus the CSRF header on writes;
  - `lib/query/keys.ts`: every key is `[caseId, version, view, …]`;
  - `lib/geom/bbox.ts`: transforms from pt to px and from oriented px to display px;
  - `lib/textSlice.ts`: splits page text into three plain text nodes around `[char_start, char_end)`.

---

## D. MVP milestones, tasks and hour ledger

### D.1 Hour ledger (4 × 30.5 h = 122 h; buffer 8.5 h)
Changes from the judge's ledger:
- **+2.5 h** for pypdfium2 (A-02/A-03);
- **+0.5 h** for schema ownership (B-01);
- **−1 h** of Playwright moved into A's integration time;
- **−0.5 h** of Hypothesis properties, because the false-alarm harness moved to D-08;
- **−0.5 h** of seed authoring and **−0.5 h** of Docker, by scripting both;
- **−0.5 h** on the eval page, which is static ECharts from the report JSON.

| A — Ingest + platform security | h | B — Engine + correctness floor | h | C — Frontend | h | D — Data, store, API, eval | h |
|---|---|---|---|---|---|---|---|
| A-01 Scaffold, pre-commit, import-linter, Docker skeleton, `.env.example`, smoke | 2.0 | B-01 Models, ports, fakes, ConfigBundle, JSON Schema (owner) | 2.0 | C-01 Astro/Tailwind, same-origin proxy, typed client, **CSP spike** | 1.5 | D-01 h0 reality check + quiet-day counts | 1.5 |
| A-02 pypdfium2 `PdfReader` (char loop, offsets, boxes, font size, render, pt→px) | 4.5 | B-02 Telemetry split, day windows, duplicates (T-14) | 2.5 | C-02 CaseWorkspace + 5-step story + build poller | 4.0 | D-02 Seed generators (PDFs, gauges, repair log, temperature, labels.yaml) | 4.5 |
| A-03 Text rules: phrases, number+unit, dates, mentions, lines | 3.5 | B-03 Conformal envelopes, quiet days, log coverage, pooling, drift (T-01/02/04, N-3) | 4.5 | C-03 ConflictCard + GateTable + OutcomeBadge | 3.0 | D-03 SQLite schema, triggers, version_claims, review_events, derived status | 2.5 |
| A-04 Hidden-text guard (T-06) | 1.5 | B-04 Gaps, flatline, quantifier coverage (T-03/13) | 1.5 | C-04 RegionViewer, TextSpanView, TableWindow, RecheckBadge | 4.0 | D-04 Record hash, manifest chain, snapshot hash, anchors, replay | 2.5 |
| A-05 CSV cell pointers, `coverage_period` | 2.5 | B-05 Units, `sensor_native` (T-05) | 1.5 | C-05 SensorChart (window, band, p5–p95, S-88.1) | 3.0 | D-05 API routes, LRU, ETag, 409s, IDOR dependency, RFC 9457, projections wiring | 3.5 |
| A-06 OCR, re-read, plausibility, EXIF (T-09/21) | 4.5 | B-06 Entity resolver, features, veto (T-10) | 3.0 | C-06 Timeline (valid + observed) | 2.5 | D-06 Fault injector, 7 types, seeded, dev/holdout | 3.0 |
| A-07 Upload hardening + BlobStore (S6/S7, T-16..19) | 1.5 | B-07 Time: `plant_tz`, half-open, unknown (T-11/12) | 2.5 | C-07 ReviewQueue, DecisionPanel, CandidateList, LoginForm | 3.0 | D-07 Baselines: TF-IDF, averaging/LWW, no-gate (N-4) | 2.0 |
| A-08 Build child, heartbeat, sweep, extraction cache (S4, T-28) | 2.5 | B-08 Gate: 6 checks, outcomes, pairs, conflict grouping | 4.0 | C-08 ExpertView, EnvelopeView, Integrity/Replay, StageTimings | 3.5 | D-08 Metrics: P/R/F1, Wilson false-alarm harness, ECE/Brier bootstrap, per-bin | 2.5 |
| A-09 Auth: argon2id, sessions, CSRF, lockout, roles (S1/S2) | 2.5 | B-09 Trust formula, independence, uncalibrated (T-15/32) | 2.0 | C-09 CSP hashes final, eslint, version badges (S8, T-22/29) | 1.0 | D-09 Holdout protocol + report (T-31) | 1.5 |
| A-10 Hostile corpus ×7 | 1.0 | B-10 Decision re-run path (`rerun_after_decision`) | 1.5 | C-10 Minimal eval page | 1.0 | D-10 Goldens + determinism + replay tests | 1.5 |
| A-11 Playwright 5 scripts | 1.5 | B-11 Hypothesis properties | 2.5 | C-11 Integration, polish, a11y pass | 2.5 | D-11 Final image, two laptops, rehearsal, anchors | 1.5 |
| A-12 Integration/bugfix | 1.5 | B-12 Integration | 1.5 | — | — | — | — |
| **Buffer** | 1.5 | **Buffer** | 1.5 | **Buffer** | 1.5 | **Buffer (floating reserve for B)** | 4.0 |
| **Total** | **30.5** | | **30.5** | | **30.5** | | **30.5** |

**Floors:**
- **Correctness floor** (B-02..B-09, B-11, D-08 harness): about 14 h.
- **Security floor** (A-04, A-07, A-08, A-09, A-10, C-09, D-05 authz parts): about 9 h.

**Sleep and meal windows** (5.5 h each, staggered so two people are always on the critical path):
- C: h12–h16.5
- A: h17–h21.5
- D: h21–h25.5
- B: h25–h29.5

Each person also takes 1 h of meals, spread across the event.

### D.2 pypdfium2 plan (task A-02, decision U-B)
| Need | pypdfium2 mechanism | Notes and gaps |
|---|---|---|
| Page text with char offsets | `textpage = page.get_textpage()`; `n = textpage.count_chars()`; build `page_text` **ourselves**, char by char, through `pdfium.raw.FPDFText_GetUnicode(tp, i)` | `get_text_range()` returns UTF-16 text that can contain generated `\r\n` characters and surrogate pairs, so its string index ≠ char index. Our own loop keeps an exact `char_index → string offset` map. `FPDFText_IsGenerated(tp,i)` marks generated characters (kept in the text and flagged; quotes may span them). `page_text_sha256 = sha256(utf8(page_text))`. Cross-check: `get_text_range()` after NFC equals our text after the same normalisation (smoke test). |
| Char boxes | `textpage.get_charbox(i, loose=False)` → `(left, bottom, right, top)` in PDF points, origin bottom-left | Span bbox = union of the char boxes in `[char_start, char_end)`. Line number = cluster on the baseline y (tolerance 0.5 × median char height), plus generated line breaks. |
| Font size (hidden-text guard < 4 pt) | `pdfium.raw.FPDFText_GetFontSize(tp.raw, i)` | Long-standing API. **Gap:** it returns the nominal size before the CTM, so a scaled text matrix can hide tiny text. **Fallback:** also flag when the char-box height is < 3 pt. The pixel test is primary anyway. |
| Invisible render mode, fill alpha | `FPDFText_GetTextObject(tp,i)` → `FPDFTextObj_GetTextRenderMode`; `FPDFText_GetFillColor(tp,i,&r,&g,&b,&a)` | Availability depends on the bundled PDFium build. A-02 probes with `hasattr(pdfium.raw, …)` and records which signals were available in the PageText artifact. If a call is missing, the pixel test still catches the case (render mode 3 draws no pixels, so std-dev < 8). |
| CropBox and rotation | `page.get_cropbox()`, `page.get_rotation()` | Outside the CropBox ⇒ held. In P0, pages with `/Rotate ≠ 0` are held as "unsupported rotation" and seed PDFs are generated unrotated. P1-10 adds `FPDF_PageToDevice`. |
| Render to PNG at 150 dpi | `page.render(scale=150/72, rotation=0, draw_annots=False).to_pil()` → PNG, cached by `(sha, page, 150)` and hashed | The pt→px transform is `x_px=(x−crop.left)·s`, `y_px=(crop.top−y)·s`, with `s=150/72`. The goldens include a bbox round-trip test against a reportlab fixture with known coordinates. |
| Hidden-text pixel test | Crop the span bbox on the rendered PNG, convert to greyscale, and compute the std-dev; < 8 ⇒ held "text not visible" | Primary signal (judge item 6). |
| Scanned PDFs (no text layer) | `count_chars()==0` on every page | **Gap in P0:** no claims, with one review item "no text layer". P1-10 adds the render → OCR path. |
| Page cap and safety | `len(pdf) ≤ 50`; parsing happens only in the build child (RLIMIT, timeout) | `FPDF_LoadMemDocument` runs on bytes; nothing is written to disk. |

The licence row goes into `THIRD_PARTY_NOTICES.md` (pypdfium2 Apache-2.0/BSD-3, PDFium BSD-3). The PRD §21.2-7 and §22 caveat is removed.

### D.3 Milestones

#### M0 — Setup and h0 reality check (h0 → h2)
| Task | Owner | Details | Closes |
|---|---|---|---|
| A-01 | A | Repo tree (§B.1), `uv` + `npm ci`, pre-commit (ruff, mypy, lint-imports, gitleaks, contracts-check stub, eslint, tsc), `.gitattributes`, `.env.example`, Dockerfile skeleton building on Docker Desktop, `make smoke` on 4 laptops (native) plus the image | S10 baseline, S11, T-37 (lockfiles) |
| B-01 (start) | B | Model skeletons, ID types, `canonical.py` (JCS, 6 dp) | NFR-4 basis |
| C-01 | C | Astro static + Tailwind 4 + React island hello world, served by FastAPI `StaticFiles`; Vite proxy `/api` in dev; **CSP spike**: build once with the enforcing CSP and confirm the island hydrates | Early de-risk of ADR-08's residual risk |
| D-01 | D | `make h0` on the real CSVs: does M-21 on 14 Mar exceed T\*? Are there error rows at 10:00 and 14:00? Quiet-day counts per machine, the decision (real day / other real day / planted), written to `data/h0_report.json` and pinned in `config/case.yaml` | T-30, N-3 sizing, PRD §21.2-4/5 |

- **Entry:** dataset downloaded; laptops have Docker Desktop and the WSL2 clone.
- **Exit:**
  - `make smoke` is green natively on all 4 laptops and in the image;
  - the h0 decision is recorded;
  - Tesseract and pypdfium2 versions are recorded.

#### M1 — Contracts frozen (h2 → h8)
| Task | Owner | Details |
|---|---|---|
| B-01 | B | All §C.1 models and validators; §C.2 ports plus fakes; ConfigBundle plus `config_hash`; JSON Schema export; tag `contracts-v1` at h8 |
| D-03 | D | `001_schema.sql` with every evidence table, `002_append_only_triggers.sql`, `version_claims`, `review_events`, the derived-status SQL view, partial unique index on builds, and the `SqliteClaimStore` against the port contract tests |
| D-05 (part 1) | D | Router skeletons that return fixture data with the real response models, so `openapi.json` → `schema.d.ts` exists at h8 |
| A-02 | A | The pypdfium2 adapter (§D.2) against `PdfReader` contract tests |
| D-02 (part 1) | D | `gen_seed_pdfs.py` (report_0314.pdf with C-17 on line 4, the white-text fixture, the undated note, the 10 Mar note); `labels.yaml` |
| C-02 (start) | C | Workspace layout against fixtures served by the stub API |

- **Exit:**
  - `contracts-v1` tag;
  - `make contracts-check` is green;
  - every port has a fake and contract tests;
  - triggers abort an UPDATE (`test_trigger_aborts_update`).

#### M2 — Walking skeleton (h8 → h10)
| Task | Owner | Details |
|---|---|---|
| A-03 (min) | A | A phrase rule that extracts C-17 from report_0314.pdf with a verified quote and offsets |
| B-02, B-03 (min) | B | M-21 Parquet split, day windows, a first real envelope, S-88 |
| B-08 (min) | B | Gate checks 1–6 for this pair only |
| D-04 (min), D-05 | D | A snapshot with manifest_hash; `story` and `conflicts` routes from the snapshot |
| C-03 (min) | C | ConflictCard renders the two claims with VersionBadge |

- **Exit:** `make demo-skeleton` puts a red "They disagree" card in the browser, with computed numbers and the version. This shows the frozen contracts work end to end.

#### M3 — Full ingest and engine (h10 → h24)
| Task | Owner | Named tests that must pass (from HARDENING) |
|---|---|---|
| A-03 | A | `test_quote_equals_page_text_slice`, `test_undated_note_time_unknown` (with B-07) |
| A-04 | A | `test_white_text_pdf_zero_claims_one_review` (T-06) |
| A-05 | A | `test_cell_pointer_row_sha`, `test_envelope_refuses_without_log_coverage` (with B-03) |
| A-06 | A | `test_decimal_drop_69_goes_to_review` (T-09), `test_exif6_bbox_alignment_and_no_gps` (T-21) |
| A-07 | A | `test_300mb_rejected_streaming` (T-17), `test_hostile_corpus[html_as_pdf, svg, traversal_name, bomb_png]` (T-16/18/19) |
| A-08 | A | `test_kill_mid_build_marks_stale_then_rebuilds` (T-28), `test_build_key_idempotent`, `test_replay_cache_miss_is_error` |
| B-02 | B | `test_duplicate_ts_not_averaged` (T-14) |
| B-03 | B | `test_quiet_day_false_alarm_rate_holdout` (harness from D-08), `test_check4_rejects_statistic_or_granularity_mismatch` (T-02), `test_planted_hot_days_bounded_shift`, `test_case_window_excluded` (T-04), `test_thin_history_uses_model_pool` (N-3), `test_envelope_drift_opens_review` |
| B-04 | B | `test_spike_in_gap_never_agree` (T-03), `test_frozen_sensor_flatline`, `test_stop_event_not_gap` (T-13) |
| B-05 | B | `test_gauge_vs_telemetry_cannot_compare`, `test_no_mm_s_in_api_or_ui` (T-05), `test_unknown_unit_never_converts` |
| B-06 | B | `test_transposed_digits_never_autolink` (T-10), `test_serial_conflict_vetoes`, `test_decision_keyed_by_mention_key` |
| B-07 | B | `test_local_day_boundary_2330` (T-11), `test_undated_note_time_unknown` (T-12), `test_client_timestamp_ignored` (T-38) |
| B-08 | B | `test_held_claims_never_pair`, `test_conflict_grouping_c17` |
| B-09 | B | `test_undeclared_provenance_no_corroboration` (T-15), `test_c17_confidence_computed` (= engine value), `test_ui_uncalibrated_label` (T-32, with C) |
| D-02 (rest) | D | Gauge photos (6.9 bar, 69 dropped decimal, EXIF-6), paper form "Press 21", nameplate SN-0021, repair log "100 psi", "pressure 7.2" with no unit, derived daily summary, synthetic temperature channel (badged) |
| D-04 | D | `test_chain_verify_detects_edit`, `test_snapshot_hash_mismatch`, `test_manifest_includes_engine_lock_tesseract` |
| D-05 | D | `test_cross_case_claim_404` (T-25), `test_viewer_decision_403`, `test_spoofed_reviewer_field_422` (T-23), `test_versioned_cache_headers_private_immutable`, `test_latest_no_store`, `test_problem_json_types` |
| D-06 | D | `test_injector_seeded_reproducible`, `test_dev_holdout_disjoint` |
| D-10 | D | Goldens for Demos 0, 1a, 1b, 3, 4, 5, 5b (engine-level); `test_no_magic_literals_in_engine` (T-30) |
| C-02..C-06 | C | In parallel against the live API from h12 |

- **Entry:** M2 passed.
- **Exit (h24):**
  - all of the above are green;
  - a full demo build takes < 60 s in the image;
  - `make golden` is in pre-commit (from h16 for the goldens already blessed).
- **The h26 stretch gate** opens only if Demos 0–6 goldens (Demo 2 and 6 in held state) are green.

#### M4 — UI complete (h18 → h28)
| Task | Owner | Details |
|---|---|---|
| C-03..C-08 | C | All components in §C.5; proof for all four pointer kinds; envelope view (quiet days with reasons, n, med/MAD, T\*); integrity badge and Verify replay |
| B-10 | B | `rerun_after_decision`; `test_decision_rerun_under_2s` (API-level) |
| D-05 (decision) | D | Decision endpoint inside `BEGIN IMMEDIATE`; `test_20_parallel_decisions_one_wins` (T-24); `test_stale_base_version_untouched_item_accepted`; `test_supersede_requires_senior` |
| A-09 | A | `test_login_lockout_5_in_5min`, `test_session_rotated_on_login`, `test_cross_origin_form_post_403` (T-26), `test_write_requires_json_and_csrf` |
| C-07 | C | Demo 2 flow: candidate list with per-feature reasons → pick → reason ≥ 15 → card updates |
| A-11 | A | Playwright: `e2e_proof_under_1s`, `e2e_decision_card_under_2s`, `e2e_byte_flip_evidence_changed` (T-27), `e2e_xss_fixture_no_dialog_under_csp` (T-22), `e2e_all_panels_same_version` (T-29) |
| D-10 | D | Goldens for Demos 2 (after decision) and 6 (held) |

- **Exit:**
  - all 5 Playwright specs are green against the image under the **enforcing** CSP;
  - NFR-10: proof reached in ≤ 2 clicks from the story;
  - NFR-11: every badge has a text label.

#### M5 — Eval and hardening (h16 → h30, feature freeze at h30)
| Task | Owner | Details |
|---|---|---|
| D-06/D-07/D-08 | D | Seeded faults (unit swap, alias, removed source, contradicting note, late timestamp, value perturbation, derived duplicate); baselines computed (`test_baseline_output_generated`, N-4); metrics with CIs |
| D-09 | D | `make eval-holdout` refuses until the config commit is on the remote (`test_eval_report_has_pushed_config_commit`, T-31). The holdout runs once, at about h28. The report records P/R/F1 per fault, quiet-day false alarms (Wilson CI on ≥ 200 machine-days), entity-link acc@1/@3, accuracy per confidence bin, ECE and Brier (bootstrap CIs, bin counts), baseline outputs, and ≥ 30% external faults (or the U-2 disclosure) |
| A-10 | A | The full hostile corpus (7) is green |
| B-11 | B | Hypothesis: symmetry, totality, never-average, unit round-trip, unknown never converts, overlap commutativity, **gap monotonicity**, chain 1-byte detection |
| C-09/C-10 | C | CSP checked once in Report-Only on the final build, then enforced; eval page |
| — | All | `test_parallel_eval_runs_one_proceeds` (T-34), `test_network_off_build_succeeds` (T-33; run with `--network none` in Docker) |

- **Exit:**
  - the eval report is generated from the holdout and committed;
  - `make check` and `make e2e` are green on `main`;
  - tag `mvp-freeze`.

#### M6 — Freeze and rehearsal (h30 → h36)
| Task | Owner | Details |
|---|---|---|
| D-11 | D | Final image built twice (two laptops, same digest); `make demo` on both; manifest hashes are equal across the laptops (replay determinism); backup video recorded |
| A-12, B-12, C-11 | A, B, C | Bug fixes only (P0 regressions); no features |
| All | All | Slides updated with **computed** numbers from the engine (PRD §24.2 item 7); judge card printed |
| h33 | All | Full rehearsal with the HARDENING §6 checklist |
| h35 | D | `make anchor`: roots pushed to the remote; UI shows the roots |

- **Exit:** every item on the pre-demo checklist is ticked.

### D.4 Stretch (only after the h26 gate, only from buffer, all flag-gated, in the judge's order)
| ID | Item | h | Notes |
|---|---|---|---|
| S-01 | SSE "version ready" notice | 1 | `events` router reads a `version_events` table; polling stays as the fallback |
| S-02 | Ed25519 manifest signature, off-box key | 1 | Skipped unless key custody is met |
| S-03 | Groq VLM second reader, `record` mode | 3 | Only if a key is present and the team accepts network use; the demo itself runs in `replay` |
| S-04 | Isotonic recalibration fit | 2 | Dev labels → holdout ECE before and after |
| S-05 | Load bins (rotate terciles) | 2 | |
| S-06 | Groq LLM proposer + verifier | 4 | Very unlikely in 36 h; P1-03 |
| S-07 | XLSX | 2 | P1-07 |

---

## E. Product phases: from MVP to single-plant pilot

**Team:** the same 4 engineers (A platform/security, B engine, C frontend, D data/eval). On the plant side: an IT/OT contact (about 0.2 FTE), 2 maintenance engineers as reviewers and labellers (about 2 h/week each), and a pilot sponsor. **Calendar:** about 25 weeks, with P2 and P3 overlapping by one week.

### P1 — Hardening and stretch features (weeks 1–4)
| ID | Task | Owner | Closes |
|---|---|---|---|
| P1-01 | SSE live updates (notice only) from a `version_events` table; polling fallback | C + D | FR-UI-7 |
| P1-02 | Ed25519 manifest signing, private key off-box (`age`-encrypted on a team laptop or HSM token), `key_id` in the manifest, verification in `/integrity` | A | ADR-04 P1 |
| P1-03 | **`GroqLlmProposer`**: OpenAI-compatible client with `base_url=TRACE_GROQ_BASE_URL`, model from config (text model id is part of `config_hash` and of the cache key), `temperature=0`, JSON schema/JSON mode, no tools, `max_tokens` cap, timeout 30 s, 2 retries with jittered backoff, a per-build and per-day token budget (T-33). **Modes:** `off` (default; module never imported), `replay` (cache only; a miss means no proposals, logged), `record` (network on; writes the cache). **Egress controls:** `TRACE_LLM_EGRESS_ACK=true` is required, plus a per-case `allow_external_ai` flag set by an ingestor, plus a UI banner "document text is sent to Groq (US) for extraction proposals". **Redactor** runs before sending: emails, phone numbers, person names from the plant roster, and free-text IDs become placeholders, with a reversible span map. Numbers and units are never redacted. **Verifier** (5 checks from FR-ING-5) runs against the original text after de-redaction | B + A | FR-ING-5, T-07, T-08, T-33 |
| P1-04 | **`GroqVlmReader`** (Groq vision model, id from config and verified against Groq's model list at phase start): it is sent **only the cited crop**, EXIF already stripped. OCR vs. VLM disagreement beyond the gauge resolution → held (`reader_disagreement`) | A | FR-ING-4 P1, FR-TRUST-3, T-09 fully closed |
| P1-05 | Isotonic/Platt calibration fit on dev labels; `calibration_fit_id` in the config; the UI shows "calibrated (fit …)"; ECE ≤ 0.05 on the holdout | B + D | FR-TRUST-5, NFR-12, D6 |
| P1-06 | Load-aware envelopes per `rotate` tercile, with per-bin n fallback | B | FR-NORM-4 P1 |
| P1-07 | XLSX: `openpyxl` read-only + `defusedxml`; zip caps (entries ≤ 1,000, uncompressed ≤ 100 MB, ratio ≤ 100); `sheet` in the pointer | A | FR-ING-2 P1, T-16 |
| P1-08 | Full eval dashboard; threshold auto-tuning on dev seeds only | C + D | FR-UI-6, FR-LOOP-2 P1 |
| P1-09 | Schemathesis, full authz matrix, `fuzz_mutated_pdf_smoke` (T-20), `pip-audit`, CycloneDX SBOM, `/eval/run` rate limit, cross-machine determinism CI job | A + D | T-20, T-34, T-37, ADR-05 P1 |
| P1-10 | pypdfium2 gap closure: rotated pages (`FPDF_PageToDevice`), scanned PDFs (render → OCR), near-duplicate derivation **labelling** (no credit) | A | FR-ING-1 gaps, FR-TRUST-2 P1 |
| P1-11 | CI pipeline (GitHub Actions or the plant's GitLab): `make check`, `make e2e`, image build, SBOM, cosign signature | A | NFR-4, T-37 |

- **Exit criteria:**
  - every P1 named test is green;
  - with all AI modes `off`, the full suite passes under `--network none`;
  - with `record`, the 50-mutation test accepts 0 claims and the injection fixture changes 0 outcomes;
  - the holdout is re-run and ECE reported before and after calibration.
- **Risks:**
  - Groq model deprecation. **Mitigation:** model ids live in the config, cached responses keep replays valid, and changing the model bumps the config version.
  - Rate limits and outages. **Mitigation:** budget and backoff; rules-only fallback.
  - VLM weakness on gauge crops. **Mitigation:** disagreement only holds claims for review and never accepts them.

### P2 — Platform migration (weeks 5–9)
| ID | Task | Detail |
|---|---|---|
| P2-01 | **Postgres 16** `PgClaimStore` (psycopg 3, pool) | The same tables, with JSONB bodies. Append-only `BEFORE UPDATE OR DELETE` triggers in plpgsql (`RAISE EXCEPTION 'append-only'`), plus a `BEFORE TRUNCATE` trigger. Two roles: `trace_owner` (migrations only) and `trace_app`, with `REVOKE UPDATE, DELETE, TRUNCATE ON <evidence tables> FROM trace_app`. RLS policies keyed on `case_id` are prepared and disabled (single tenant). `tstzrange` generated columns with GiST indexes for the interval sweep. The port contract tests run against both stores |
| P2-02 | Migration tooling | Numbered SQL files plus a 60-line runner (no ORM, so no Alembic). `tools/sqlite_to_pg.py` copies records verbatim. Afterwards, **`/integrity` must stay green, because `record_hash` and `manifest_hash` are computed over JCS bodies and do not depend on the store**. Test: `test_migrated_chain_verifies` |
| P2-03 | **MinIO with Object Lock** | A bucket created with object lock and versioning on, default retention in COMPLIANCE mode for N days (plant policy; 365 for the pilot). `S3BlobStore` via boto3; keys are `sha256/<ab>/<cd>/<hash>`; `put` is conditional (`If-None-Match: *`). The API proxies originals (attachment, nosniff, `CSP: sandbox`), so there are no public or presigned URLs. Test: `test_locked_object_delete_denied` |
| P2-04 | **OIDC SSO** (Authlib) against the plant IdP (Entra ID or Keycloak) | Authorisation-code + PKCE in a BFF pattern: the server keeps the opaque session cookie, and tokens never reach the browser. IdP groups map to roles (viewer, reviewer, senior_reviewer, ingestor, evaluator). One local break-glass admin (argon2id, hardware-token custody, its use alerts). Identity still comes only from the session, and the decision stores the `sub` + display-name snapshot |
| P2-05 | **Temporal decision: not adopted for the pilot (ADR-16)** | 40 machines produce a few dozen builds a day, and AI calls are cached and budgeted. Builds use a Postgres job table (`SELECT … FOR UPDATE SKIP LOCKED`) drained by 1–2 worker containers, each running the same killable spawn child. Heartbeat and sweep are unchanged. **Trigger to adopt Temporal:** more than one worker host plus multi-step paid AI retries, **or** build p95 over 10 min, **or** more than 500 builds a day. Stage functions are already the activity boundary |
| P2-06 | Transactional outbox | A `version_events` row is written in the same transaction as `versions`. `LISTEN/NOTIFY` wakes the snapshot builder and the SSE fan-out |
| P2-07 | **Backups** | pgBackRest: full weekly, differential daily, continuous WAL archive to a second MinIO (off-host). MinIO bucket replication to a second site or NAS. Anchors pushed to the remote daily. **RPO 15 min, RTO 4 h.** A monthly restore drill in staging must finish with a green `/integrity` |
| P2-08 | **Monitoring** | OTel SDK spans named after the stages, exported to Tempo (optional) or logs. `prometheus-client` `/metrics` on an internal port. Grafana dashboards: builds, stage ms, proof latency, review-queue age, held counts, integrity status, Groq tokens and spend, backup age. Alertmanager: build failures > 3/h, stale build, integrity red (page), queue item > 1 working day (A6), backup older than 26 h, disk > 80%, Groq budget at 80% |
| P2-09 | Deployment | Docker Compose on an on-prem Ubuntu 24.04 VM (8 vCPU, 32 GB, 500 GB SSD): `api`, `worker`, `postgres`, `minio`, `caddy` (TLS from the plant CA), `prometheus`, `grafana`, `alertmanager`. Egress allowed **only** to `api.groq.com:443` and only when AI is enabled. Read-only rootfs, non-root, cosign-verified images, Renovate for dependency updates |
| P2-10 | Performance (NFR-8, pilot scale) | k6 load test: 50 concurrent users, p95 versioned read < 300 ms, proof < 1 s, 40-machine × 30-day case build < 2 min |

- **Exit criteria:**
  - full suite green against Postgres + MinIO;
  - a migrated demo chain verifies;
  - restore drill passed within the RTO;
  - SSO login with the plant IdP test tenant;
  - all alerts fire in a game-day test;
  - a light pen test (OWASP ASVS L2 subset) has no high findings.
- **Risks:**
  - Delays in IdP onboarding. **Mitigation:** start the paperwork in week 1; local accounts as interim.
  - Object-lock misconfiguration. **Mitigation:** the bucket policy is checked by a test; staging uses GOVERNANCE mode first.

### P3 — Pilot onboarding (weeks 9–13)
| ID | Task | Detail |
|---|---|---|
| P3-01 | Asset register import | A CMMS export (SAP PM or Maximo CSV) becomes the entity registry: IDs, serials, models, components and aliases, plus a data-quality report (duplicate serials, missing models) |
| P3-02 | Historian telemetry | Batch export (CSV/Parquet) per tag. `config/tags.yaml` maps tag → machine/channel, **unit and datasheet reference**. Documented units become `unit_status=known`; undocumented ones stay `sensor_native`. Resampling to hourly is a declared derived source |
| P3-03 | Real event logs | Work orders, alarm and failure logs, each with a declared `coverage_period` (A8). Missing coverage refuses the build (`log-coverage`) |
| P3-04 | Tolerances | `tolerances.yaml` filled from sensor datasheets, with each row citing its datasheet (A5) |
| P3-05 | **A1–A8 readiness checks** | `trace onboard check` writes a readiness report: A1 clock drift (error vs. spike alignment, > 15 min flagged), A2 fault durations ≥ 1 h, A3 alias coverage of report mentions, A4 quiet-day n per machine (pooled where < 19), A5 tolerance coverage, A6 reviewer roster and SLA, A7 `plant_tz` and shifts, A8 log coverage |
| P3-06 | **Labeller programme** | 2 plant engineers who did not build TRACE. Label mode in the review queue. 300 items over 4 weeks, 50 double-labelled (Cohen's κ ≥ 0.7). Labellers author ≥ 30% of the holdout faults. Dev and holdout are split by machine |
| P3-07 | Phrase ontology from real reports | Shift-report phrases (including local-language and shorthand variants) reviewed with engineers. Each phrase gets a quantifier (∀/∃) |
| P3-08 | Re-tune and data-egress approval | Thresholds tuned on dev; holdout run after the config is pushed. Plant IT approves Groq egress (DPIA-lite) or AI stays `off` |
| P3-09 | Training and runbooks | A 1-hour reviewer course; runbooks for "integrity red", "build stuck", "review backlog" and "restore" |

- **Exit criteria:**
  - all 40 machines registered;
  - readiness report green, or each failed assumption accepted in writing by the sponsor;
  - envelopes learned (n ≥ 19 or labelled as pooled);
  - plant-holdout quiet-day false alarms ≤ 5% (Wilson upper bound reported);
  - labelled-set conflict precision ≥ 0.90 and recall ≥ 0.85.
- **Risks:**
  - Historian export access. **Mitigation:** OT contact and a read-only export.
  - Clock drift (A1). **Mitigation:** a per-source offset is declared and shown, never silently corrected.

### P4 — Pilot operations and go/no-go (weeks 13–25, 12 weeks)
- **Weekly cadence:** an ops review covering SLOs, held items, review-queue age, incidents and Groq spend.
- **Monthly:** a restore drill, a calibration check (ECE on the newest labels), a drift-guard review, and dependency and CVE updates.
- **SLOs:**
  - 99% availability in plant working hours;
  - p95 read < 300 ms;
  - build < 2 min;
  - review queue median age < 1 working day;
  - integrity green 100% of the time.
- **Mid-point review at week 6.** Go/no-go at week 12. **GO only if all of the following hold:**
  1. engineer-confirmed conflict precision ≥ 0.85 in live operation;
  2. 0 gaps read as normal;
  3. quiet-day false alarm ≤ 5%;
  4. ECE ≤ 0.05 after calibration;
  5. reviewer time ≤ 2 h/week;
  6. no Sev-1 integrity incident;
  7. sponsor sign-off on value (at least 3 documented cases where a hidden disagreement was surfaced).
- **Risks:**
  - Reviewer fatigue. **Mitigation:** tune `τ_review` and batch the queue.
  - Seasonality breaking exchangeability. **Mitigation:** ADR-14's fallback, a rolling 30-day baseline behind a flag, measured first.

### P5 — Optional: multi-tenant SaaS (outline only, about 6 months, starts only after a GO)
- Tenant in the path, enforced RLS, per-tenant KMS keys with crypto-shredding (chain over ciphertext/HMAC; T-35, T-36).
- An edge-authorised CDN keyed by (tenant, case, version), never `public`; a stateless read tier with Redis; read replicas.
- Temporal workers with a GPU OCR/VLM pool; an AI gateway (cache, spend caps, provider failover: Groq primary, a second OpenAI-compatible provider).
- Kafka, Citus and TimescaleDB stay "planned only if" (≥ 3 consumers / multi-TB per tenant / real-time ingest).
- SOC 2 controls, canary releases, a second region, SBOM and cosign enforced at admission.

---

## F. Build risk register (top 12)

| # | Risk | P | I | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | The real M-21 on 14 Mar does not exceed T\* or lacks the error rows | M | H | h0 check (D-01) before any slide or golden; switch to the real day that does, or plant it with the injector and badge it "planted" | D |
| R2 | pypdfium2 gaps (generated chars, nominal font size, render-mode API missing in the bundled PDFium) | M | M | Our own char-loop text with an offset map; pixel std-dev test is primary; char-box-height fallback; capability probe recorded per artifact | A |
| R3 | Tesseract output differs between Windows native and the image | H | M | Replay mode against the committed `seed/cache/`; recording only inside the image; Tesseract version in the manifest | A |
| R4 | Quiet-day n < 19 for demo machines | M | M | Model-level pooling (N-3), labelled; h0 measures it | B/D |
| R5 | Contract churn after h8 breaks C | M | H | Freeze tag, CCR process, `contracts-check` in pre-commit, fixtures generated from the models | B |
| R6 | CSP blocks island hydration | M | H | CSP spike at h1 (C-01), not h30; Astro CSP or the post-build hasher; Playwright under the enforcing CSP | C |
| R7 | CRLF conversion changes CSV and PDF hashes on Windows | H | H | `.gitattributes` `seed/** -text`; smoke test hashes seed files against `seed/SHA256SUMS` | A |
| R8 | Docker Desktop/WSL2 failure on a demo laptop | M | H | Native `uv run` fallback rehearsed; two laptops; backup video; image pre-pulled | D |
| R9 | SQLite `database is locked` between child and API | L | M | WAL, `busy_timeout=5000`, short `BEGIN IMMEDIATE`, one build per case | D |
| R10 | Decision → card > 2 s | L | H | Cached claims, sweep pairing, precomputed views, LRU; measured at M3 (`test_decision_rerun_under_2s`) | B |
| R11 | No non-builder labeller (U-2) | M | M | D labels (wrote no rules) and it is disclosed; external faults authored from a written template by anyone outside the team | D |
| R12 | Stretch work eats the buffer and the core slips | M | H | h26 gate; stretch only from buffer; flags default off; a P0 regression after h30 reverts the stretch commit | Lead |

---

## G. Definition of Done

**Task-level (every task ID):**
1. Merged to `main` through a PR reviewed by someone other than the author. Correctness-floor PRs are reviewed by D, and security PRs by B.
2. `make check` is green: ruff, eslint, mypy/tsc strict, import-linter, contracts-check, tests.
3. Every named test listed for the task in §D.3 exists, is named exactly as in HARDENING, and passes. New behaviour has a unit test, and any invariant has a property test.
4. No demo literals in the engine (T-30 grep). No document text in logs. No new network calls (`--network none` test).
5. If the task touches a hot path, its perf budget is measured and recorded.
6. No contract change without an approved CCR, with schemas and types regenerated.
7. Goldens are still green, or re-blessed with the diff explained in the PR.
8. User-visible text: every outcome badge has a text label, and uncalibrated and synthetic badges appear where needed.

**Milestone-level:** every task meets the task DoD, the milestone's exit criteria are met (§D.3), the image builds, `make demo` runs, `main` is tagged `m<N>`, and the standup records the buffer used.

**Phase-level (pilot):** exit criteria met, CI green including e2e and security jobs, runbook updated, an ADR written for any decision, a rollback plan tested in staging, and sponsor sign-off.

---

## H. Traceability (requirements → tasks)

### H.1 Functional requirements
| Req | Tasks (MVP) | Product |
|---|---|---|
| FR-ING-1 text/PDF | A-02, A-03, A-04, D-02, C-04 | P1-10 |
| FR-ING-2 tables/logs | A-05, D-02 | P1-07, P3-03 |
| FR-ING-3 sensors | B-02, B-03, B-04, D-02, C-05 | P3-02 |
| FR-ING-4 images | A-06, D-02, C-04 | P1-04 |
| FR-ING-5 LLM | B-01 (port + FakeLlm), S-06 | P1-03 |
| FR-ING-6 provenance | A-07, D-03, B-09 | P2-03 |
| FR-NORM-1 units | B-05 | P3-02, P3-04 |
| FR-NORM-2 entities | B-06, C-07 | P3-01 |
| FR-NORM-3 timeline | B-07, C-06 | P3-05 (A1, A7) |
| FR-NORM-4 envelopes | B-03, C-08, D-01 | P1-06, P3-05 |
| FR-NORM-5 gaps | B-04, B-08 | — |
| FR-GATE-1 six checks | B-08, C-03 | — |
| FR-GATE-2 outcomes | B-08, B-11 | — |
| FR-GATE-3 conflict cards | B-08, C-03 | — |
| FR-GATE-4 never averaged | B-02, B-08, B-11, A-01 (lint ban) | — |
| FR-GATE-5 determinism | B-01, D-04, D-10 | P1-09 |
| FR-TRUST-1 reliability prior | B-09 | P3-06 |
| FR-TRUST-2 independence | B-09, A-07 | P1-10 |
| FR-TRUST-3 review holds | A-04, A-06, B-03, B-06, D-03, B-10 | P1-04 |
| FR-TRUST-4 confidence | B-09, C-08 | — |
| FR-TRUST-5 calibration | B-09 (label), D-08, S-04 | P1-05 |
| FR-EVID-1 address | B-01, D-03 | — |
| FR-EVID-2 extracted/inferred | B-01, D-10 | — |
| FR-EVID-3 append-only | D-03, D-04 | P2-01 |
| FR-EVID-4 storage | D-03, A-07, B-02 | P2-01, P2-03 |
| FR-UI-1 story | C-02, D-05 | — |
| FR-UI-2 proof | C-04, C-05, D-05, A-02 | — |
| FR-UI-3 timeline | C-06 | — |
| FR-UI-4 decision | C-07, D-05, B-10, A-09 | P2-04 |
| FR-UI-5 expert | C-08 | — |
| FR-UI-6 eval dashboard | C-10 | P1-08 |
| FR-UI-7 live updates | C-02 (polling), S-01 | P1-01, P2-06 |
| FR-UI-8 integrity/replay | D-04, C-08 | P1-02 |
| FR-LOOP-1 human in charge | B-10, C-07, D-05 | P3-09 |
| FR-LOOP-2 prove and tune | D-06, D-07, D-08, D-09 | P1-08, P3-06, P3-08 |

### H.2 Non-functional requirements
| NFR | Tasks |
|---|---|
| NFR-1 traceability | B-01 (validators), D-10 (100% pointers re-resolve test) |
| NFR-2 integrity | A-07, D-05 (recheck), A-11 (byte flip) |
| NFR-3 immutability | D-03, D-04; P2-01, P2-03 |
| NFR-4 determinism | B-01, A-08 (cache), D-04, D-10, D-11; P1-09 |
| NFR-5 explainability | B-08, B-09, C-03, C-08 |
| NFR-6 no silent fusion | B-02, B-08, B-11, A-01 (lint ban) |
| NFR-7 performance (hackathon) | A-08, D-05, B-10, A-11 |
| NFR-8 performance (production) | P2-10 (pilot scale); P5 |
| NFR-9 privacy/tenancy | A-06 (EXIF), A-09, A-01 (log scrubbing); P1-03 (redaction/egress), P2-04, P5 |
| NFR-10 usability | C-02, C-11 |
| NFR-11 accessibility | C-03, C-11 |
| NFR-12 honest confidence | B-09, C-08, D-08; P1-05 |

### H.3 Deliverables
| Deliverable | Tasks |
|---|---|
| D1 engine for text, image, tables, time series | A-02, A-03, A-05, A-06, B-02 |
| D2 unified state schema | B-01, D-05 (`/state`) |
| D3 ClaimRecord, extracted vs. inferred | B-01, D-10 |
| D4 evidence pointers for every modality | A-02, A-05, A-06, B-02, C-04, C-05 |
| D5 entity linking, timeline, conflicts | B-06, B-07, B-08 |
| D6 confidence accuracy and calibration | B-09, D-08, D-09 (S-04 / P1-05) |
| D7 inspection interface | C-02 … C-08 |
| D8 demonstrations | D-02, D-10, A-11, D-11 |

### H.4 Threats (the Tester's index)
| Threat | Task |
|---|---|
| T-01, T-02, T-04, N-3 | B-03 |
| T-03, T-13 | B-04 |
| T-05 | B-05 |
| T-06 | A-04 |
| T-07, T-08 | P1-03 (S-06) |
| T-09 | A-06, P1-04 |
| T-10 | B-06 |
| T-11, T-12, T-38 | B-07 |
| T-14 | B-02 |
| T-15 | B-09 |
| T-16..T-19 | A-07, A-10 |
| T-20 | A-08, P1-09 |
| T-21 | A-06 |
| T-22, T-29 | C-09, A-11 |
| T-23, T-24, T-25 | D-05 |
| T-26 | A-09 |
| T-27 | D-03, D-04, A-11 |
| T-28 | A-08 |
| T-30 | D-10 |
| T-31, N-4 | D-07, D-09 |
| T-32 | B-09, C-08 |
| T-33 | A-01, P1-03 |
| T-34 | D-05, P1-09 |
| T-35, T-36 | P5 |
| T-37 | A-01, P1-09, P1-11 |
| N-1 | D-03 |
| N-2 | D-11 |
