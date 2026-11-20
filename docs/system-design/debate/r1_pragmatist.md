# TRACE — Round 1 — PRAGMATIST position

**Persona:** hackathon lead. 4 people, 36 hours, one live demo that must not fail. Every hard requirement in the PRD stays (never average, LLMs only propose, evidence pointer on every claim, append-only + hash-checked, valid vs observed time, explicit gaps, determinism, NFR-7). Everything else has to justify its hours.

**My budget frame.** 4 people × 36 h = 144 person-hours. Subtract ~20 for sleep/food/rehearsal slack and ~10 for demo-data authoring (PDFs, photos, the M21/14-Mar check). That leaves about **110 build hours**. Every choice below is costed against that. My rule is that infrastructure we can't demo, and that no hard requirement needs, costs zero hours.

**Proposed split:** A = ingestion (text/PDF/table/OCR), B = normalise + envelopes + gaps + gate + trust, C = frontend, D = data prep, then eval track from h16 (also owns Docker/demo laptop).

---

## 1. Overall shape: modular monolith, hexagonal core

**Choice:** one FastAPI process. Inside it, a pure-Python package `trace_core` with no FastAPI, no SQLite and no filesystem imports. Its entry point is `build_case(inputs, config, decisions, clock) -> CaseVersion`, and each stage (`read`, `normalise`, `compare`, `score`) is a pure function over Pydantic models. Four ports, each with exactly one adapter in P0:
- `ClaimStore` (SQLite)
- `BlobStore` (local content-addressed folder)
- `OcrReader` (Tesseract)
- `LlmProposer` (no-op / fake; P1)

**Reasons:**
- **Cost.** Ports are just Python `Protocol` classes, about 1 h total. Services cost 6–10 h in Dockerfiles, inter-service auth, network errors and duplicated schemas, and buy nothing a judge can see.
- **The core really does run unchanged in workers.** §15 says the engine runs unchanged in worker pools. A pure-function stage boundary is exactly a Temporal activity / queue job signature. Today FastAPI calls `build_case`; tomorrow a Temporal activity calls the same stage functions with a Postgres `ClaimStore` and an S3 `BlobStore`. That is the whole migration story, and it holds because the core is pure.
- **Testability.** Pure stages make golden tests and property tests trivial (§12).
- **Demo blast radius.** One process means one thing to restart.

**Expected counter (Architect):** "A monolith grows into a ball of mud; stages should be separate services so OCR can scale on GPUs." **Answer:** OCR-on-GPU is a *deployment* concern. In production the same package is deployed as several worker pools with different queue bindings. Package boundaries plus an import-linter rule (`trace_core` may not import `api` or `adapters`, ~15 min) give the modularity without the network.

**I'd change my mind if** a stage had to be written in another language, or had to hold a GPU model resident during the hackathon. Neither is in P0.

## 2. Pipeline execution: sync decisions, BackgroundTasks for builds, no queue

**Choice:**
- **Decision → re-run is synchronous** inside the POST request. It re-runs only normalise-for-affected-claims + gate + trust over the *cached extracted claims*, never re-OCRs, writes a new version, and returns the updated card payload. That keeps us inside the <2 s budget with a big margin; realistic time is 100–400 ms.
- **Full build** uses FastAPI `BackgroundTasks`. A `builds` row (`queued/running/done/failed`, per-stage timings) is polled by the UI every 1 s. A realistic build is 5–15 s: parse ~880k telemetry rows once into per-machine Parquet, then OCR 3–6 photos.
- **Idempotency:** `build_key = sha256(sorted source sha256s + config_hash + sorted decision ids + engine_version)`. If a version with that key exists, return it. This one line gives idempotent retries *and* is the determinism contract made concrete.
- **Retries:** none automatic. A failed build is a `failed` row with the error. The user clicks build again, and idempotency makes that safe.

**Reasons:** Redis + Arq/Celery is ~4–6 h with Windows pain (Celery dropped Windows support; Redis isn't native on Windows). It adds a second and third process that can die mid-demo, and it solves a concurrency problem we don't have: one presenter, one case at a time. NFR-7 is met without it.

**Expected counter:** "BackgroundTasks die with the process and have no retries; that's not production-grade." **Answer:** correct, and that's why §15 has Temporal. The hackathon has no requirement for durable jobs. The append-only store guarantees a crashed build leaves no half-version: the version row is written last, in one transaction.

**I'd change my mind if** builds took over 60 s (for example, EasyOCR on CPU across many photos) or we needed parallel builds for the eval track. Even then the fix is a `ProcessPoolExecutor`, not Redis.

## 3. Storage: SQLite (append-only log) + Parquet (telemetry) + frozen JSON snapshots

**Choice:**
- **SQLite**, one file in WAL mode, stdlib `sqlite3` with no ORM. Tables: `sources`, `claims`, `comparisons`, `conflicts`, `decisions`, `review_items`, `versions`, `builds`. Each row has a few indexed columns (`case_id`, `version`, `claim_id`, `modality`, `claim_type`) plus a `body` JSON column holding the Pydantic model dump. One file instead of the PRD's "SQLite per case", because a case list over N files is annoying and gains nothing. The `case_id` column gives the same isolation, and this is also the Citus shard key later.
- **Append-only enforcement:**
  - `BEFORE UPDATE` and `BEFORE DELETE` triggers with `RAISE(ABORT, 'append-only')` on every evidence table. That's 15 minutes of work and it's demoable: run an UPDATE live and it fails.
  - The hash chain (§4) catches anything done outside SQLite.
  - "Reset demo" never deletes anything; it creates a fresh case from the seed.
- **Time series:** at ingest, the MS telemetry CSV is split into one Parquet file per machine (pandas + pyarrow). Each split file is registered as a *derived source* with its own SHA-256 and `derived_from_sources = [telemetry.csv]`. That keeps proof-view re-hashing on ~200 KB instead of ~80 MB, and it exercises the independence graph honestly.
- **Frozen snapshot:** at the end of each build, the full Unified Case State is written as `snapshots/{case}/{version}.json`. All GET endpoints serve that file through an in-process LRU. "Read endpoints serve frozen versions" (§13) is met literally, and it is exactly the object the production Snapshot Builder pushes to the CDN.

**Reasons:**
- Zero install.
- Triggers give *real* enforcement, not convention.
- Postgres in Compose costs ~2 h (drivers, migrations, Windows Docker Desktop quirks) and buys no demo-visible feature.
- DuckDB is a nice query engine, but pandas over one machine's 8,760 rows is microseconds. It would be one more dependency for nothing.

**Expected counter:** "Use Postgres from day one so the scale path is real; SQLite semantics differ." **Answer:** the `ClaimStore` port is about 10 methods. The SQL we write (inserts, select-by-case-version, triggers) is portable, and Postgres has equivalent triggers or `REVOKE UPDATE`. A port swap after the hackathon is a day of work; having Postgres during the hackathon is a risk.

**I'd change my mind if** someone on the team already has a working Postgres compose and Alembic template they've used before (then the cost is 30 min), or if we hit `database is locked`. The fix for that is a single writer lock in the adapter.

## 4. Integrity: SHA-256 per source + linear hash chain per version; signing is a 30-min stretch

**Choice:**
- **Sources:** SHA-256 at upload. Blobs are stored content-addressed (`blobs/9f/9f2c…`), opened with `'xb'` (write-once) and set read-only.
- **Proof view:** re-hashes the file and re-extracts the cited value (text slice, cell, crop re-OCR, window recompute). Show "re-checked just now" or "evidence changed".
- **Claim log:** each record carries `prev_hash` and `row_hash = sha256(prev_hash ‖ canonical_json(body))`, chained per case in insertion order. `versions.root_hash` is the last row hash of that version. A `verify_chain(case)` endpoint plus an expert-view badge. About 1.5 h, including canonical JSON.
- **Merkle tree:** no. A linear chain detects tampering, and nobody asks for inclusion proofs during a demo. Merkle only matters for proving one claim to an outside party without shipping the log. That's a §15 design note.
- **Signed snapshots:** Ed25519 (`cryptography` library) over `root_hash`, with a key generated at first boot. That's 30 min, but only after h28.

**Counter:** "A chain inside the same DB the attacker controls is theatre." **Answer:** the hackathon threat is accidental mutation plus tamper *evidence*, not a hostile admin. For production, the root hash goes to an external anchor (object-lock bucket or KMS-signed). I'd accept a Red Team demand to print the root hash in the UI so it can be compared out of band.

## 5. Determinism and versioning

This is where hackathon builds quietly fail, so I spend real hours here (~3 h total).

**Choice:**
- **Config:** `config/gate.yaml` holds τ_link, δ_link, τ_review, tolerances, envelope params and shift definitions. `config_version = "gate-v1.3+" + sha256(file)[:8]`, stored on every comparison and version.
- **Rule and extractor versions:** string constants (`rules:phrase_list_v2`, `envelope_check_v1`), plus `engine_version` from the git SHA or package version. Tesseract version and traineddata hash go into `method`.
- **Determinism killers we ban:**
  - **`uuid4()`:** all IDs are content-derived, e.g. `claim_id = "C-" + sha256(source_sha, pointer, rule_id)[:10]`.
  - **`datetime.now()` in core:** inject `clock`; `created_at` is excluded from content hashes.
  - **dateparser's implicit "now":** always pass `RELATIVE_BASE = document observed_time` and fixed `DATE_ORDER`/`TIMEZONE`.
  - **Dict/set iteration order:** sort every output list by `(valid_time.start, claim_id)`.
  - **Float formatting:** round normalised values to a fixed precision before hashing; canonical JSON uses `sort_keys`.
- **OCR:** results are cached by `(image_sha, bbox, tesseract_version, config)`. Replay is exact even if the OCR engine has minor non-determinism.
- **Replay:** `POST /cases/{id}/versions/{v}/replay` rebuilds from the stored source hashes + config + decisions and compares `root_hash`. A "Verify replay ✓" button in the expert view turns NFR-4 into a 5-second demo moment.

**Counter:** "Content-derived IDs collide when the same quote appears twice." **Answer:** `char_start` is part of the pointer, so the same quote at a different offset gets a different ID.

## 6. Extraction stack

- **OCR: Tesseract (`pytesseract`, `image_to_data` for word bboxes) + OpenCV crop for the re-read.** The re-read crops the bbox with padding, upscales 2×, runs `--psm 7` on a single line, and compares.
  - EasyOCR pulls in torch (~2 GB) and downloads models on first run, a classic hotel-wifi failure. It is also slow on CPU.
  - PaddleOCR is worse on Windows.
  - Tesseract is one apt line in Docker and the UB-Mannheim installer on Windows.
  - We *author* the gauge/form/nameplate photos, so we control legibility: high-contrast digital readout fonts plus one real phone photo for honesty.
  - Cost: 3–4 h including the re-read.
- **PDF: PyMuPDF.** `page.get_text("rawdict")` gives per-char bboxes, so `char_start/char_end → bbox` is direct, and `page.get_pixmap()` renders the page PNG for the proof view (see §8). pdfplumber is 5–10× slower and needs a separate renderer. AGPL is fine for a hackathon, and we flag it for production (where pdfplumber + pdf.js is the alternative).
- **LLM (P1):** in P0, only the `LlmProposer` port, a `FakeProposer` for tests, and **the verbatim-quote verifier**: exact `str.find` for all occurrences against the normalised source text. Zero matches means reject and log; more than one match means take the one nearest the proposed context, or reject if there's no context; offsets are always computed by us. That's 1 h and it makes "0 accepted unmatched quotes" testable now. A real provider (with temperature 0, prompt hash and model ID logged, responses cached by `(source_sha, prompt_hash, model)` for determinism) waits until after h28. The LLM never sets outcome or confidence; the type system enforces this, because a `Proposal` has no such fields.

## 7. Entity resolution, timeline, human review

- **ER:** exactly §10.1, with `rapidfuzz` (`token_set_ratio` / `WRatio`) + alias table from `PdM_machines` + context features (model, components, whether a maint/error record exists on that date). Weights live in config. No ML and no embeddings. The output is a ranked top-3 with reason strings, because the reasons *are* the demo for Demo 2. Cost 3 h. Hard-code nothing about "Press 21"; it must fall out of the score (0.71 vs 0.22), so tune weights against the seeded alias faults.
- **Timeline:** plain Python intervals with half-open `[start, end)` in UTC, original TZ kept, and a granularity enum. The overlap rule is from §10.2. The granularity-compatibility rule is that day-level text compares only against day aggregates. Shift map comes from config. No interval-tree library at this scale. Cost 2–3 h including relative-date resolution.
- **Where review sits:** after normalise and before gate. Anything `held_for_review` (ambiguous link, OCR vs re-read mismatch, unknown unit, low confidence) is excluded from gate pairs, and the gate records check 1 or 4 as failing with "held for review". The decision POST writes a `HumanDecision` claim (reviewer from the session, reason required, `supersedes` the review item). It re-runs from normalise forward and returns the new card. Escalate is another decision type that sets `assignee_role=senior`. Auto-escalate after 1 working day is computed at *read* time from `opened_at` versus the injected clock. No cron needed.

## 8. Frontend: static Astro, a few big islands, no pdf.js

- **Output mode: `static`.** No SSR adapter and no Node server to keep alive. Pages are `/`, `/case`, `/case/expert`, `/eval` and `/review`, with the case ID passed as `?id=`, which sidesteps `getStaticPaths`. In the demo build, FastAPI serves `dist/` via `StaticFiles`, so there is **one origin, no CORS**, and one process. In dev, use Vite `server.proxy` `/api → :8000`.
- **Islands:** **one large `client:only="react"` island per page** (`<CaseWorkspace>`, `<ExpertView>`, `<EvalDashboard>`). Astro owns the layout, nav, static explainer copy and Tailwind shell. Many tiny islands don't share React context, so you end up wiring nanostores between them; that's a 2–3 h hydration and state-sync tax for zero user value. Inside `<CaseWorkspace>`: story, conflict cards, proof drawer, timeline, review panel.
- **State:** TanStack Query only. A decision mutation `onSuccess` sets the new version and invalidates `['case', id]`. There is no global store, and no nanostores unless we split islands.
- **Proof viewers:** one `<RegionViewer>` component handles both images *and* PDF pages.
  - The backend renders the PDF page to PNG (PyMuPDF), and the frontend draws bboxes as absolutely positioned divs scaled by `naturalWidth`.
  - **This deletes pdf.js and its worker configuration under Vite/Astro, which is the #1 frontend time sink I've seen.**
  - Text/MD: `<pre>` with a `<mark>` around `[char_start, char_end)`.
  - Tables: the backend returns ±15 rows around the cell, and the frontend renders a plain `<table>` with the cell highlighted and `scrollIntoView`. No grid library.
- **Charts: ECharts** (`echarts-for-react`) for both the sensor chart (line + `markArea` for the window + band series for the envelope) and the timeline (custom/bar series with two rows for valid vs observed time). One library learned once. Recharts can't do a decent interval timeline. vis-timeline is a second library.
- **Live updates: none in P0.** The decision response carries the new version; builds poll. SSE (`sse-starlette`, ~1 h) is the first stretch item if someone is idle, because it maps directly to the §15 "notice, not data" design. WebSocket is P2 per FR-UI-7.

## 9. API design

- **Shape:** REST exactly as in §13 under `/api/v1`. Pydantic v2 models are the single source of truth. Run `openapi-typescript` and `openapi-fetch` (types only, no generated runtime) from a `make types` script: about 1 h, and it kills schema drift between person A/B and person C. Commit the generated file, and freeze the schemas at h8.
- **Errors:** RFC 9457 `application/problem+json` through one exception handler, mapping `NotFound`, `AppendOnlyViolation`, `ValidationError`, `BuildFailed` and `EvidenceChanged`. 30 min, and cheap polish.
- **Pagination:** offset/limit on `/claims` and `/comparisons` only (expert view). Every other endpoint returns the whole frozen version slice, which is small. No cursors.
- **Versioning:** URL prefix plus `?version=` for case state. That's enough.

**Counter:** "Cursor pagination and ETags are needed for the CDN design." **Answer:** for the design doc, yes. ETag = `root_hash` is free with frozen versions, and I'll add that header (5 min) because it's the honest bridge to §15.

## 10. AuthN/AuthZ

**Choice:** pick-a-name login from a seeded `users.yaml` (name, role ∈ {reviewer, senior, viewer}), with **no passwords**. It sets a Starlette `SessionMiddleware` signed cookie. Endpoints that write check the role. The reviewer name comes from the session, not the form body, so it can't be spoofed by a typo. The reason stays a required field. Cost: 1 h.

**Not JWT:** same-origin cookies are simpler, and JWT adds refresh/storage questions we don't need. In production, the gateway does OIDC and passes identity in a header to the same role check.

**Counter (Red Team):** "No passwords means anyone can be anyone." **Answer:** true, and labelled as such on the login screen ("demo identities"). The PRD requirement is *attribution* (name + reason recorded and immutable), which we meet. Real authentication is a production gateway concern. I would add a shared demo PIN if judges are allowed to click around on our network.

## 11. Observability

- **`structlog`** JSON lines with `case_id`, `build_id`, `version` and `stage` bound to every log line. 30 min.
- **Pipeline metrics stored in the data:** each build row records per-stage `ms`, `claims_in/out`, `held_for_review`, `rejected_llm_quotes` and `ocr_reread_mismatches`. The expert view shows them. That's the observability judges will see, and it proves NFR-7 on screen.
- **OpenTelemetry: not in P0.** Auto-instrumentation is 30 min, but a collector plus Jaeger is another container and nobody looks at traces in a demo. It's listed in §15 with the span names already matching our stage names, so adoption later is mechanical.

## 12. Testing

| Test | Hours | Why |
|---|---|---|
| **pytest unit**: units (pint), ER thresholds, gate's 6 checks, envelopes, gaps, independence | 4 (spread) | PRD-required |
| **Never-average invariant** (NFR-6): walk all inferred claims, assert none has ≥2 conflicting parents with a numeric value between them | 0.5 | Hard requirement |
| **Golden cases**: build Demos 0–5 from seed, canonical JSON, compare to committed `golden/*.json` and `root_hash` | 2 | *This is* the determinism test and the "nothing broke at h33" test |
| **Hypothesis** property tests: (a) bar↔psi↔kPa round-trips; unknown unit never converts; (b) gate is total, so every pair gets exactly one of the 4 outcomes; (c) any gap-flagged side → never "agree"; (d) quote verifier accepts only exact substrings | 1.5 | Catches exactly the bugs judges probe |
| **Contract tests** | 0 | Generated TS types + `tsc --noEmit` *is* the contract test |
| **Playwright**: one script runs Demo 0 (card visible, proof opens <1 s) and Demo 2 (decide → card updates <2 s) | 2, after h26 | Doubles as the pre-demo smoke check, run 15 min before going on stage |

Fault-injection P/R, ECE and Brier are the eval track's deliverable (D6), not "tests", and they run through `/eval/run`.

## 13. Deployment and scale path

**Hackathon:**
- **Docker Compose with one service.** A `python:3.11-slim` image with `tesseract-ocr` and `tesseract-ocr-eng` installed, built from a multi-stage Dockerfile whose first stage runs `npm run build` for Astro. FastAPI serves the API and static files. Volume for `data/`.
- **Plus a native run path** on the demo laptop (`uv run` / `pnpm build`) as a fallback.
- Two demo laptops; the second runs from the committed seed.

**Which §15 components are actually *earned*** (design only, but the Judge should know which survive scrutiny):
- **Earned:**
  - **CDN + frozen per-version snapshots.** Immutable versions are perfectly cacheable, and that alone carries the 1M-reader load (§15 sizing: 85% CDN hit).
  - **Object storage with object-lock.** Natural home for content-addressed blobs.
  - **Postgres** for the claim log, with the same triggers.
  - **A durable workflow engine (Temporal)** once real OCR/VLM/LLM calls need retries and timeouts. Our stage functions are the activities.
  - **Redis** as a read cache.
- **Not earned yet:**
  - **Kafka.** Write volume is small. A Postgres outbox table + `LISTEN/NOTIFY` (or Debezium later) drives the snapshot builder and live notices.
  - **Citus.** Reads are absorbed by the CDN, and a single well-indexed Postgres with read replicas serves the origin load until per-tenant data volume, not reader count, forces sharding. Keep `case_id` as the shard key so the option stays open.
  - **TimescaleDB.** Parquet per machine in object storage plus precomputed daily aggregates covers it until real-time ingest exists.
- **Kubernetes:** yes for production (worker autoscaling), but it's irrelevant to the 36 h build.

**I'd change my mind on Kafka** if multiple downstream consumers needed replayable ordered change streams, for example customer integrations.

---

## Top 10 risks to the 36 h build + live demo

| # | Risk | Fix |
|---|---|---|
| 1 | **Demo machine-day isn't real** (M21 / 14 Mar may not show error3@10, error4@14, peak≈64) | **Hour 0, person D:** query the real CSVs. If it doesn't match, pick the real machine-day that does, or use the seeded injector and label it "planted for the demo" (§21.2.5). Never let this surface at h30. |
| 2 | **Tesseract on Windows** (PATH, traineddata, `TesseractNotFoundError`) | Docker image is canonical. Windows dev uses UB-Mannheim + `pytesseract.tesseract_cmd` from env. OCR cache by image hash. A smoke test at h1 on *every* laptop. |
| 3 | **Data authoring eats the build** (PDFs, gauge photos, forms, nameplate, repair log) | Person D owns it, done by h6. Generate PDFs from Markdown (via PyMuPDF `insert_text`/Story or a Word export) and gauges/nameplates with Pillow using clean fonts, plus one real phone photo. Commit everything to `seed/`. |
| 4 | **pdf.js worker config under Astro/Vite** | Avoid it entirely: server-rendered page PNG + bbox overlay (§8). |
| 5 | **CORS / ports / mixed origins** at demo time | Single origin: FastAPI serves Astro `dist/`. Vite proxy in dev. Never call `localhost:8000` from the browser by absolute URL. |
| 6 | **Integration hell at h30** (backend and frontend meet late) | **Walking skeleton by h10:** one text claim + one sensor claim → gate → a real card on screen, with crude stages. Then deepen. Schemas frozen at h8, TS types regenerated by script. |
| 7 | **Determinism breaks silently** (uuid4, `now()`, dateparser, set order, floats) | Ban list in §5. A golden-hash test in CI/pre-commit from h16. Replay button in the expert view. |
| 8 | **Live demo dependency on the network** (LLM API, model downloads, wifi) | P0 has **zero network calls**. Cases are pre-built in the seed. "Reset demo" creates a fresh case, so nothing is deleted. A recorded backup video. Laptop power settings set to never sleep. Warm the process before going on stage. |
| 9 | **Scope creep into P1** (VLM, LLM extractor, calibration fitting, load bins) | **Hard checkpoint at h26:** if Demo 0–5 golden tests aren't green, P1 is cancelled. Stretch work happens only on branches that don't touch `trace_core` gate logic. |
| 10 | **Eval track starved and the labeller isn't independent** | Person D switches to eval at h16 full time. Recruit the non-builder labeller (a friend from another team) at h0 and give them a labelling CSV template by h18. The seeded injector is written first, since ground truth comes by construction. |
| (+) | SQLite `database is locked` under BackgroundTasks | WAL mode + one process-wide writer lock in the adapter. |
| (+) | Island hydration/state bugs | One `client:only` island per page; no SSR hydration at all. |

## Hour ledger (approx., 110 build hours)

- Ingestion text/PDF/table: 10
- OCR + re-read: 4
- Telemetry + aggregates + envelopes + gaps: 8
- Units + ER + timeline: 8
- Gate + trust + independence: 8
- Store + hash chain + triggers + snapshots + replay: 6
- API + types + errors + auth: 5
- Frontend (story, cards, RegionViewer, chart, timeline, review, expert view): 26
- Eval track: 18
- Docker/deploy/Playwright/rehearsal: 7
- Buffer: ~10

Nothing in my plan spends an hour on a component that no demo scene shows and no hard requirement needs. Every hard requirement maps to a mechanism that is cheap *and* can be shown on stage: triggers, hash chain, golden replay, quote verifier, gap claims, never-average test.
