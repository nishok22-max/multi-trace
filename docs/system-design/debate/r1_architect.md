# TRACE — Round 1: ARCHITECT position

Stance: pick the option that a hostile judge cannot break during the demo, that keeps the PRD's invariants true *by construction* rather than by convention, and whose hackathon version is the same shape as the §15 production design (smaller, not different). Where robustness and 36 h collide I say so and give the cheapest robust variant.

---

## 1. Overall shape — modular monolith, hexagonal

**Choice.** One Python repo, one deployable image, three packages:
- `trace_core` — pure domain: Pydantic v2 models (§9), units, entity resolver, timeline, envelopes, gate, trust, Merkle/hash utilities. **No I/O, no FastAPI, no DB imports, no `datetime.now()`.** Every side effect goes through a port (`typing.Protocol`): `BlobStore`, `ClaimLog`, `ExtractionCache`, `OcrEngine`, `LlmProposer`, `Clock`, `Signer`.
- `trace_adapters` — Postgres, filesystem/S3 blob store, Tesseract, LLM HTTP client, Ed25519 signer.
- `trace_api` — FastAPI routers + the worker entrypoint.

The pipeline is one function: `build_case(manifest, config_bundle, decisions) -> CaseVersion`. The API calls it (via the job runner), the worker calls it, the test suite calls it, and in production each stage becomes a Temporal activity wrapping the same stage function.

**Reasons.**
1. Determinism (NFR-4) is only provable when the core is a pure function of explicit inputs; hexagonal ports are how you make the clock, IDs and model calls explicit.
2. §15 says "the engine runs unchanged inside worker pools" — that is only true if the engine has no opinion about where it runs.
3. 4 people can work in parallel on stage modules against frozen Pydantic contracts.
4. Services now would mean network contracts, deployment and distributed failure modes for zero benefit at demo scale.

**Expected counter.** "Ports and adapters is ceremony in 36 h." **Answer:** the ports are ~8 Protocol classes of 3–5 lines each; the payoff is that golden tests run the full pipeline in-memory in <5 s with fake OCR, which is what keeps the team honest at hour 30.

**Change my mind if:** a stage needs a different runtime (e.g. GPU OCR in a separate container) during the hackathon — then that one adapter becomes an HTTP call, the core still doesn't change.

---

## 2. Pipeline execution — durable job table + incremental re-run

**Choice.**
- **Full build** (`POST /cases/{id}/build`): enqueued into a **Postgres-backed job queue** (Procrastinate, or a 60-line `jobs` table using `SELECT … FOR UPDATE SKIP LOCKED`), executed by a separate `worker` process from the same image. Returns `202` + `job_id`; client watches via SSE.
- **Decision re-run** (`POST /review/{id}/decision`): runs **synchronously in the request**, but only the stages downstream of normalisation (link → gate → trust → snapshot) against **cached extraction artifacts**. Returns the new version in the response body.
- **Idempotency key** for a build = `sha256(manifest_hash ‖ config_hash ‖ decisions_hash ‖ code_version)`. Unique index on it: a duplicate request returns the existing version instead of a second build. Per-case **advisory lock** (`pg_advisory_xact_lock(case_id)`) serialises builds so versions are strictly ordered.
- Retries: stage-level, max 3, exponential back-off, only for adapter errors (OCR/LLM timeouts); domain errors are not retried and are recorded as a failed build with RFC 9457 detail.

**Reasons.**
1. `BackgroundTasks` runs in the API process: a restart loses the job, there is no retry, and CPU-bound OCR starves the event loop that serves the <1 s proof view.
2. A Postgres queue needs no extra infra (we already run Postgres, see §3), is transactional with the claim insert (enqueue + version reservation in one commit) and maps 1:1 to Temporal activities later.
3. NFR-7 "<2 s decision→updated card" is a *latency* requirement; pushing it through a queue adds polling delay. Gate + trust on one case is milliseconds of pure Python; extraction is never re-run on a decision.
4. Redis+Arq/Celery adds a second stateful dependency whose only job is something Postgres does.

**Expected counter.** "Synchronous re-run in a request handler is the anti-pattern you just rejected." **Answer:** it is bounded work (no I/O except one DB read/write, no OCR, no LLM) with a hard timeout; if it ever exceeds 1.5 s it falls back to enqueue + SSE. Only full builds are unbounded.

**Change my mind if:** profiling shows the downstream re-run of the demo case exceeds ~1 s — then everything goes through the queue and the UI does optimistic "re-running…" with SSE.

---

## 3. Hackathon storage — Postgres 16 + content-addressed blobs + Parquet

**Choice.**
- **PostgreSQL 16** in Docker Compose for claims, comparisons, conflicts, decisions, review items, versions, jobs, users. Claims stored as typed key columns (`claim_id`, `case_id`, `entity_id`, `attribute`, `valid_start`, `valid_end` as `tstzrange`, `claim_type`, `review_status`) + full canonical body as `JSONB`.
- **Blobs**: write-once content-addressed directory `blobs/sha256/ab/cd/<hash>` behind `BlobStore` (MinIO/S3 Object Lock in prod).
- **Telemetry**: **Parquet** (raw hourly MS telemetry, partitioned by machine) queried with **DuckDB/Polars in-process**. Raw hourly readings are **not** individual claims (see weak spot W4).
- **Append-only enforcement, three layers:**
  1. App DB role has `INSERT, SELECT` only; `UPDATE/DELETE/TRUNCATE` revoked on `claim_log`, `comparisons`, `decisions`, `sources`.
  2. `BEFORE UPDATE OR DELETE` trigger raising an exception (catches migrations and superuser mistakes).
  3. Hash chain: each `claim_log` row stores `seq`, `prev_hash`, `row_hash = sha256(prev_hash ‖ JCS(record))`. `GET /cases/{id}/integrity` re-walks the chain. Layers 1–2 *prevent*, layer 3 *detects*.
- Version membership is a separate append-only table `version_claims(case_id, version, claim_id)`: a claim is written once and belongs to many versions.

**Reasons.**
1. Same engine as production (Citus/Timescale are Postgres extensions): no SQL dialect or locking-semantics migration, no "files today, DB later" rewrite promised in FR-EVID-4.
2. API + worker write concurrently; SQLite's single-writer lock and per-case files make the job queue, advisory locks and cross-case queries (review queue across cases, eval runs) awkward.
3. `tstzrange` + GiST index gives the interval-overlap query (gate check 3, timeline) natively and correctly (half-open ranges).
4. Real role-based revocation is a stronger append-only claim to a judge than "we promise not to call UPDATE".

**Expected counter (Pragmatist).** "SQLite is zero-setup; Postgres is a dependency risk on venue Wi-Fi." **Answer:** `postgres:16-alpine` is pulled once before the event; tests use the same container (or `pytest-postgresql`). The ClaimLog port keeps an SQLite adapter possible (WAL mode, same triggers via `RAISE(ABORT)`), but we do not build two.

**Change my mind if:** any team laptop cannot run Docker. Then SQLite adapter with WAL + triggers + hash chain, single worker thread — invariants unchanged.

---

## 4. Integrity model — hash everything, Merkle per version, sign the manifest

**Choice.**
- **Per source:** SHA-256 streamed at upload; blob path *is* the hash, so a rewritten file is a different address.
- **Per evidence pointer** (cheap re-check, needed for NFR-7 <1 s): `text_span` → `sha256(quote)` + page-text artifact hash; `image_region` → `crop_sha256`; `table_cell` → `row_sha256` of the raw CSV line bytes; `sensor_window` → `window_sha256` of the canonical Arrow IPC slice. Proof re-check verifies the pointer-level hash *and* the source hash; the source hash of the 70 MB telemetry file is computed per Parquet row group (Merkle over row groups) so we never rehash the whole file on a click.
- **Per case version:** Merkle tree over sorted content-addressed IDs of claims, comparisons, conflicts, decisions → `version_root`. A **manifest** (`case_id, version, parent_version_root, source shas, config_hash, code git sha, extractor versions, decisions set, version_root`) canonicalised with **RFC 8785 JCS** and **signed with Ed25519** (`cryptography`). Proof view shows "claim ∈ signed version 7" via an inclusion proof.
- Hash chain (§3) orders the log across versions; Merkle gives per-claim inclusion proofs. Both, because they answer different questions.

**Reasons.** (1) Without an anchor outside the DB, an attacker who can rewrite a file can rewrite its stored hash too — the "re-checked just now" badge would be theatre. (2) Content addressing makes the frozen-version claim true structurally. (3) Signing is ~30 lines and one env-var key; KMS in production.

**Counter.** "Signing is gold-plating." **Answer:** it's the single cheapest feature that turns "trust us" into "verify us" in front of an auditor persona (US-2, NFR-2). It is P0.5: build it in hour 30 if the core is green; Merkle root is P0.

**Change my mind if:** time runs out — drop signing, keep root hash + chain; never drop the hash chain.

---

## 5. Determinism & versioning

**Choice.**
- **Content-addressed claim IDs**: `claim_id = "clm_" + sha256(JCS(semantic fields + evidence pointer + method{extractor, version, rule_id}))[:24]`. Display labels ("C-17", "S-88") are a separate stable `label` column assigned from a seeded fixture for demo matching.
- `created_at`, `job_id` and other wall-clock fields are **excluded** from hashed content; `Clock` port injects time.
- **Config bundle**: one YAML directory (gate tolerances, τ_link/δ_link/τ_review, ontology, phrase lists, alias table, shift definitions, envelope params) → `config_hash`; human tag `gate-v1.3` maps to a hash, never the other way round.
- **Extraction cache** keyed by `(source_sha, extractor_id, extractor_version, params_hash)` storing immutable outputs. OCR (Tesseract version + traineddata hash pinned in the image) and LLM (model id, prompt hash, temperature 0, response stored) are nondeterministic in principle; replay **reads the cached artifact**, so the pipeline is deterministic given the cache. A cache miss under `--replay` is an error, not a silent re-run.
- Floats canonicalised to fixed decimal precision before hashing; all collections sorted by ID before hashing or iterating.
- CI test: build demo case twice from scratch → identical `version_root`.

**Reasons.** Determinism is a *testable* NFR only if output is hashable; content-addressing makes "same input → same output" a byte comparison.

**Counter.** "Hash IDs are unreadable in the demo." **Answer:** labels exist for humans; the API accepts either.

**Change my mind if:** never on the cache; possibly on ID length.

---

## 6. Extraction stack

- **PDF: PyMuPDF** (`get_text("rawdict")`) for per-char bboxes, page rendering and speed; the extracted page text is itself stored as a hashed artifact and `char_start/char_end` are offsets *into that artifact* (FR-ING-1's acceptance test is then well-defined). pdfplumber as fallback. Flag: PyMuPDF is **AGPL** — fine for a hackathon, production needs the commercial licence or pypdfium2.
- **OCR: Tesseract 5** (pytesseract, `image_to_data` for word boxes + confidences). Deterministic on CPU, ~30 MB, apt-installable. Re-read uses a **different configuration**: crop + upscale + binarise, `--psm 7` with digit/unit whitelist. EasyOCR (≈1 GB PyTorch, GPU nondeterminism) and PaddleOCR (heavy paddlepaddle) rejected for P0; PaddleOCR is the preferred **independent second reader** for P1 because a second engine is real independence, the same engine twice is not.
- **LLM adapter (P1)**: `LlmProposer.propose(page_text) -> list[Proposal]` with JSON-schema structured output, temperature 0. Verifier: (a) exact `quote in page_text`; (b) if the quote occurs more than once, require an anchor/context or **reject** (ambiguous offset); (c) the proposed **value and unit string must appear inside the quote** — otherwise the model can cite a real sentence and attach an invented number; (d) offsets computed by us. All rejections logged as metrics.

**Counter.** "Tesseract is weak on gauges." **Answer:** correct — and no OCR reads an analogue needle (W8). Authored photos must show printed/digital values; that's a data-authoring rule, not an engine choice.

---

## 7. Entity resolution & timeline

- **Resolver**: deterministic, as §10.1, with normalisation (casefold, strip `#-.`, extract digit tokens) and an explicit **digit-transposition feature** (Press 21 ↔ M-12 is the Demo 2 story; make it a named reason, not fuzz noise). Each candidate stores per-feature scores; weights live in the config bundle.
- **Human review placement:** between normalisation and the gate. An ambiguous link fails check 1; the HumanDecision is keyed to a **stable mention key** `(source_sha, evidence locator)`, not to a claim ID (W3), so it survives rebuilds.
- **Timeline:** all intervals **half-open `[start, end)` in UTC** (fixes the `23:59` gap, W6). Gate candidate pairs found by grouping on `(entity_id, attribute_family)` then an interval sweep — O(n log n + k), not O(n²).
- **Granularity rule** from §10.2 enforced: day-level claims compare only with day-level inferred sensor claims (W5).
- **Envelopes** learned excluding the case window ± N days (leakage, W7), versioned and content-hashed (`env_ref` = hash).

---

## 8. Frontend

- **Astro output: `server` with `@astrojs/node` (standalone)**. Story, expert tables and conflict list are Astro components rendered on the server from the typed API client; islands only where interaction is needed. Version-pinned URLs (`/cases/{id}/v/{n}`) are immutable → `Cache-Control: public, max-age=31536000, immutable` → CDN-cacheable exactly like static. `/cases/{id}` (latest) is a short-TTL redirect.
  - Why not static: case IDs/versions are dynamic, so static means every page becomes a client-rendered island (shipping the whole app as JS and defeating Astro), and auth can't be checked before render.
- **Islands** (`client:visible` except proof viewer `client:load` on the proof route):
  - `ProofViewer` — discriminated by `evidence.kind`: `pdfjs-dist` (text layer + highlight rect from stored bbox), image with **plain SVG overlay** for bbox (no Konva/Fabric), table via **TanStack Table + TanStack Virtual** (`scrollToIndex(row)`), sensor via ECharts.
  - `SensorChart` and `Timeline` — **Apache ECharts** (one library): `markArea` for the shaded window, stacked band for the envelope, LTTB sampling for 8,760 points; custom series for the timeline with valid vs observed time as two markers joined by a line. Recharts rejected: SVG at thousands of points and no native bands.
  - `ReviewQueue` + `DecisionPanel`.
- **State:** TanStack Query for server state with a **module-singleton QueryClient** shared across islands; **nanostores** for cross-island UI state (selected claim, active version). Decision mutation invalidates `['case', id]` queries.
- **Live updates: SSE** (sse-starlette) — one-directional, auto-reconnect, works through proxies/CDNs; a WebSocket gives nothing here since clients only receive "version N ready". (Deviation from FR-UI-7, deliberate.)

**Counter.** "SSR adds a Node container." **Answer:** one more Compose service from the same repo; it buys server-side auth, less JS and immutable cacheable pages that line up with §15's CDN story.

**Change my mind if:** the team has no one comfortable with Astro SSR — then static + islands with a single `/case?id=` page.

---

## 9. API design

- REST, OpenAPI 3.1 generated by FastAPI from the same Pydantic models; evidence is a **discriminated union** (`Field(discriminator="kind")`) which `openapi-typescript` turns into a TS discriminated union. Client: **openapi-typescript + openapi-fetch** (types only, ~6 kB). CI fails if the generated client diff is uncommitted.
- Versioning: `/api/v1` for the contract; **resource versions in the path** for reads: `/cases/{id}/versions/{v}/claims`. `ETag = version_root`; reads of frozen versions are immutable.
- Pagination: opaque **cursor** (keyset on `claim_id` within a frozen version — stable because the set never changes). No offset.
- Writes: `Idempotency-Key` header on `build` and `decision`; decisions require `If-Match: <version_root>` → **409 version-conflict** when stale (two reviewers racing).
- Errors: **RFC 9457** `application/problem+json` with stable `type` URIs: `/problems/evidence-changed`, `/problems/version-conflict`, `/problems/unknown-unit`, `/problems/quote-not-verified`, plus `case_id`, `claim_id` extension members.
- Add `GET /cases/{id}/versions/{v}/manifest` and `/integrity` (§4).

---

## 10. AuthN / AuthZ

- **Server-side sessions**, HttpOnly + Secure + `SameSite=Lax` cookie, session row in Postgres; CSRF via SameSite + required custom header on mutations. JWT rejected for a browser app: no revocation, and storing it in JS-readable storage is an XSS exfiltration path.
- **The reviewer identity comes from the session, never the request body** (the PRD's `{reviewer, choice, reason}` body is spoofable — W9). Decision stores `user_id` + display-name snapshot.
- Roles: `viewer`, `reviewer`, `senior_reviewer` (escalations), `evaluator` (run eval), `admin` (publish config bundle). Hackathon: seeded users, argon2id hashes. Production: OIDC at the gateway, per-tenant ACL on `case_id`.

---

## 11. Observability

- **structlog** JSON with bound `case_id, version, job_id, stage, config_hash`.
- **OpenTelemetry**: FastAPI + psycopg auto-instrumentation; one span per pipeline stage; trace id stored on the version manifest so an auditor can jump from version to trace. Jaeger in Compose behind a profile (optional).
- **Metrics** (Prometheus `/metrics`): stage durations (NFR-7 SLO), claims by modality/type, outcomes by kind, review-queue size and oldest-item age (A6 escalation), quote-verifier rejections, re-check mismatches ("evidence changed" count — should be 0 and alert if not).
- The claim log is the audit trail; logs are operational. Never conflate them.

---

## 12. Testing

- **Golden cases**: Demos 0–6 as fixtures with expected outcome, check table and **expected `version_root`** (doubles as the determinism test). The PRD's numbers (64 vs 34–47, M-21 0.71 vs M-12 0.22) are assertions.
- **Hypothesis property tests**: gate symmetry `gate(a,b)==gate(b,a)`; never-average (no inferred claim whose parents are in conflict has a numeric value between them); unit round-trip and "unknown unit never converted"; overlap commutativity on half-open intervals; **gap monotonicity** (deleting readings can only move an outcome toward "can't tell", never to "agree"); quote verifier (accepted ⇒ `text[s:e]==quote`); hash chain detects any single-byte mutation.
- **Contract**: Schemathesis against the OpenAPI schema; TS typecheck of the generated client.
- **Playwright E2E**: proof per modality, Demo 2 decision flow asserting updated card **< 2 s**, a11y check (NFR-11) with axe.
- **Perf**: pytest-benchmark on build (<60 s) and recheck (<1 s) in CI.

---

## 13. Deployment and scale path

**Hackathon:** Docker Compose — `api` (uvicorn), `worker` (same image), `web` (Astro node), `postgres`, optional `jaeger`, volume for blobs. One `make demo` seeds and builds Demos 0–6.

**Part C, justified component by component:**
- **CDN on immutable version snapshots** — this is the real 1M-reader answer. Because versions are frozen and content-addressed, hit rate should be ≫85% (only "latest" pointers miss). This shrinks the 75-server estimate.
- **Kubernetes** — justified by heterogeneous worker pools (CPU vs GPU OCR node pools) and queue-depth autoscaling (KEDA). Not justified for the API alone.
- **Temporal** — justified: builds are multi-step, long-running, with paid OCR/LLM calls that must not be repeated on retry; activity-level idempotency + visibility. The Postgres queue is the stepping stone with the same activity boundaries.
- **Kafka** — *conditionally* justified: only once ≥3 consumers need the ordered change log (snapshot builder, live-update, search/analytics). Before that, a transactional **outbox** table + Debezium or LISTEN/NOTIFY is safer (no dual-write).
- **Citus** — weakest justification in the PRD. 1M *readers* is a read problem solved by CDN + replicas; Citus is justified only by write volume or tenant isolation at multi-TB claim scale. Start with Postgres + read replicas; shard by `tenant_id, case_id` when needed.
- **TimescaleDB** — justified for continuous ingest and continuous aggregates (daily stats feeding envelopes); Parquet remains the archival/replay format.
- **Object Lock (WORM)** on originals and an external timestamp/transparency log for version roots.

---

## Top 10 weak spots in the PRD and fixes

| # | Weak spot | Why it bites | Fix |
|---|---|---|---|
| W1 | **Claim carries `version: 7`** inside an "immutable" record | Either every rebuild rewrites claims (violates append-only) or IDs collide across versions | Content-addressed `claim_id`; version membership in a separate append-only table (§3, §5) |
| W2 | **Determinism vs OCR/LLM/`created_at`** | Same input can yield different OCR/LLM output and timestamps → NFR-4 unprovable | Extraction cache keyed by source sha + extractor version; replay from cache; exclude wall-clock fields from hashes; CI root-hash equality |
| W3 | **Decisions reference claim IDs** (`mention_claim: clm-ocr-55`) | Rebuild with a new extractor version changes IDs; decisions orphan or silently attach to different text | Key decisions to a stable mention key `(source_sha, locator)`; flag decisions as **stale** if the underlying evidence hash changes |
| W4 | **S-88 `derived_from` lists 24 raw-reading claims** | 100 machines × 8,760 h × 4 channels ≈ 3.5 M raw claims; storage and Merkle cost explode | Raw readings stay in Parquet; sensor claims point to a window with `window_sha256`; "extracted" status applies to the window artifact |
| W5 | **Granularity contradiction**: §10.2 says day-text is never compared with single hours, yet Demo 0 compares C-17 (day) with S-88 (valid 14:00–15:00, evidence window 00:00–24:00) | Gate check 3 is ill-defined exactly on the headline demo; a judge can poke it | Make S-88 a **day-level** inferred claim ("day max 64 outside 34–47"), with the 14:00–15:00 peak as a child detail; align valid time and evidence window |
| W6 | **Closed `…T23:59Z` interval ends** | 1-minute holes; inclusive/exclusive ambiguity breaks overlap at boundaries | Half-open `[start, end)` UTC everywhere; `tstzrange` in DB |
| W7 | **Envelope leakage/circularity** | If the case day or ±N days are in the quiet-day pool, or envelopes are re-learned per build, "normal" moves with the evidence | Exclude case window; envelopes versioned and content-hashed; envelope set pinned in the manifest |
| W8 | **"Gauge photo reads 6.9 bar" with OCR** | OCR cannot read analogue needles; a judge will ask | Author digital/printed gauges and forms; state the limitation; VLM second reader as P1 |
| W9 | **Reviewer name in request body** and no AuthN in P0 | Anyone can record a decision as anyone; destroys the audit trail claim | Session auth; reviewer from session; `If-Match` + 409 to prevent concurrent overwrite races |
| W10 | **Confidence numbers don't reconcile with §10.8** | 0.95×0.97×0.90×1.0×0.5 ≈ 0.41, not C-17's 0.71; a judge recomputing it will find the mismatch | Define `reliability_adj` explicitly (e.g. neutral prior maps to 1.0 multiplier, not 0.5) and **generate** demo numbers from the formula; store the formula version in the config hash |

Honourable mentions: (a) "hash-checked on every proof view" of a multi-MB telemetry file vs <1 s — solved with row-group Merkle (§4); (b) eval thresholds tuned and measured on the same injected faults — hold out fault seeds and one fault type from tuning; (c) the independence graph's "near-duplicate numbers" detection is unspecified — make it a deterministic rule with a threshold in config, and treat undeclared derivation as *possible* dependence (no corroboration credit) by default; (d) LLM quotes can be real while the attached value is invented — require value+unit inside the quote (§6).
