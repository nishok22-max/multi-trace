# TRACE — Round 3: JUDGE'S BINDING VERDICT

Inputs: `docs/TRACE_PRD.md` v1.1; R1/R2 from Architect, Pragmatist and Red Team.
Fixed stack: Python 3.11 + FastAPI + Pydantic v2; Astro + Tailwind + React islands.

**Ruling principle.** The product makes promises: "no data ≠ normal", "never guess", "every fact has an address", "never averaged". A broken promise costs more than a missing feature. So when it comes to hours, the correctness floor comes first, then the security floor, then visible features, then infrastructure. Where all three debaters agreed, I re-derived the result before accepting it. In four places I overrule that agreement or tighten it: the envelope threshold, the quiet-day training policy, the 409 semantics, and the git anchor.

**UNRESOLVED items: none.** Two confirmations are needed from the user. Neither blocks the build:
- **U-1.** The repo will be published under an AGPL-compatible licence. This is needed for PyMuPDF (item 6). If the answer is no, the fallback is pypdfium2.
- **U-2.** A non-builder labeller is available. If not, the disclosed fallback is in item 12.

---

## Part 1 — Verdicts on the 15 items

### 1. Overall shape
**VERDICT.** One repo and one deployable, a hexagonal modular monolith.
- `trace_core` is pure. It has no FastAPI, no sqlite3, no filesystem access and no `datetime.now()`. Its entry point is `build_case(manifest, config_bundle, decisions, clock) -> CaseVersion`, with stage functions `read → normalise → compare → score`.
- Ports are `typing.Protocol`: `ClaimStore`, `BlobStore`, `PdfReader`, `OcrReader`, `ExtractionCache`, `Clock`, `LlmProposer` (fake in P0).
- `import-linter` contract: `trace_core` must not import `trace_adapters` or `trace_api`.

**WHY.**
1. Determinism (NFR-4) can only be tested if the core is a pure function of explicit inputs.
2. §15's claim that "the engine runs unchanged in workers" is true only if stage functions are the activity boundary.
3. Four people can work in parallel against Pydantic contracts frozen at h8.
4. All three debaters converged here, and I verified it: no P0 requirement needs a network boundary.

**Losing arguments.** None argued for services.

**P0** the whole shape. **P1** none. **P2** stages deployed as separate worker pools.

**Residual risk.** The core leaks I/O through a "helper". **Mitigation:** the import-linter runs in pre-commit.

**Would change if** a stage needs a different runtime during the hackathon, such as a GPU-resident VLM. Then that one adapter becomes HTTP.

### 2. Pipeline execution
**VERDICT.**
- **Full build.** `POST …/build` returns `202 {build_id}`. The build runs in a **killable child process**: one `multiprocessing.get_context("spawn").Process` per build.
  - Wall timeout 180 s, then `terminate()` and status `failed_timeout`.
  - On Linux, `resource.setrlimit(RLIMIT_AS, 2 GiB)` inside the child.
  - Tesseract runs through `pytesseract(..., timeout=20)`, which is already a subprocess.
- **The `builds` table is operational, not evidence, so it is mutable.**
  - Columns: `status ∈ {queued, running, done, failed, failed_timeout, failed_stale}`, `heartbeat_at` (every 5 s), per-stage `ms` and counters, and a `build_key` with a UNIQUE constraint.
  - One build in flight per case, enforced by a partial unique index on `(case_id) WHERE status IN ('queued','running')`.
  - A startup sweep marks any `running` build whose heartbeat is older than 60 s as `failed_stale`.
- `build_key = sha256(sorted source sha256 ‖ config_hash ‖ sorted decision ids ‖ engine_git_sha ‖ lockfile_hash)`. If a version with this key already exists, it is returned and nothing is built.
- **Decision re-run is synchronous** in the API process, inside `BEGIN IMMEDIATE`.
  - It re-runs only link resolution → gate → trust → snapshot, over cached extracted claims. There is no parsing and no OCR.
  - If a build is in flight for that case, it returns `409 /problems/build-in-progress` with `Retry-After: 5`.
- There are no automatic retries. Re-POST is safe because of `build_key`.

**WHY.**
1. A child process is the only option that both keeps CPU-bound parsing off the event loop serving the <1 s proof view **and** can be killed when a parser hangs or is attacked.
2. The persisted row with heartbeat answers "is it done?" and means a crash cannot leave a build `running` forever.
3. SQLite WAL with `busy_timeout=5000` and `BEGIN IMMEDIATE` serialises the child and API writers across processes, so no in-process lock is needed.

**Losing arguments.**
- **Postgres + Procrastinate (Architect R1):** a second container plus a worker, and no P0 requirement needs durable retries. The Architect conceded.
- **Bare `BackgroundTasks` (Pragmatist R1):** it runs in-process, cannot be killed, and blocks the loop if declared `async`.
- **`ProcessPoolExecutor` (Pragmatist/Architect R2):** `future.result(timeout=)` does not stop a hung worker, and killing one breaks the whole pool. A timeout you cannot enforce is not a sandbox.

**P0** all of the above. **P1** SSE "build done" notifications; until then the UI polls every 1 s. **P2** Temporal activities with the same stage boundaries.

**Residual risk.** Spawn start-up adds about 1–2 s. The Windows native fallback has no RLIMIT. **Mitigation:** the demo runs in the Linux container, and the Windows run path is documented as "no memory cap".

**Would change if** builds exceed 60 s or the eval track needs parallel builds. Then use N child processes under a semaphore, still with no broker.

### 3. Hackathon storage
**VERDICT.** **One** SQLite file (`data/trace.db`), WAL mode, stdlib `sqlite3`, no ORM.

| Table | Kind | Key columns |
|---|---|---|
| `sources` | evidence, append-only | `case_id, source_id, sha256, modality, origin, derived_from_sources, coverage_period, synthetic` |
| `claims` | evidence | PK `(case_id, claim_id)`, `label`, `entity_key`, `attribute`, `valid_start`, `valid_end`, `claim_type`, `record_hash`, `body` JSON |
| `version_claims` | evidence | `(case_id, version, claim_id)` (also comparisons, conflicts) |
| `comparisons`, `conflicts`, `decisions`, `review_items`, `review_events` | evidence | `record_hash`, `body` |
| `versions` | evidence | `UNIQUE(case_id, version)`, `parent_manifest_hash`, `manifest_hash`, `snapshot_sha256`, `config_hash`, `engine_sha`, `build_key UNIQUE` |
| `extraction_cache` | evidence | `(input_sha, extractor_id, extractor_version, params_hash)` → artifact sha |
| `envelopes` | evidence | `envelope_id` = content hash (item 14) |
| `builds`, `sessions`, `users`, `login_attempts` | operational, mutable | — |

- **Append-only enforcement:**
  - `BEFORE UPDATE` and `BEFORE DELETE` triggers with `RAISE(ABORT,'append-only')` on every evidence table;
  - a repository layer with no update or delete methods;
  - the hash chain (item 4).
- **Status is derived, never stored mutably.** The PRD's `ReviewItem.status` and `ConflictRecord.status` are mutable fields inside "immutable" records. This was a bug that no debater caught. Status is now computed from `review_events` and decisions at snapshot time.
- **Intervals** are half-open `[start, end)` UTC strings in a fixed-width form, `YYYY-MM-DDTHH:MM:SSZ`, so string order equals time order.
- **Telemetry:** the MS CSV is split at ingest into one Parquet file per machine (pyarrow). Each split is a *derived source* with its own sha256, `derived_from_sources=[telemetry.csv]` and the split code version. Raw hourly readings are **not** claims.
- **Snapshots:** `snapshots/{case}/{v}.json`. Its sha256 is stored on `versions` and verified when the LRU is filled.

**WHY.**
1. No install and no Windows Docker risk.
2. Triggers give demonstrable enforcement: an UPDATE run live aborts.
3. `version_claims` removes the contradiction between `"version": 7` and immutability (W1).
4. Content IDs repeat across cases, so the PK includes `case_id`.

**Losing arguments.** Postgres 16 with `tstzrange` and `REVOKE` (Architect R1). `REVOKE` adds nothing when the app owns the schema on a laptop, and a case has hundreds of claims, so an exact Python interval sweep is enough. The PRD's "SQLite per case" fragments authz and migrations.

**P0** all. **P1** none. **P2** Postgres with the same triggers, `REVOKE UPDATE, DELETE` for a non-owner app role, and RLS.

**Residual risk.** `database is locked` under contention. **Mitigation:** `busy_timeout`, short `BEGIN IMMEDIATE` transactions, and only one build per case.

**Would change if** there are more than 2 concurrent writers per case or multiple hosts. Then move to Postgres.

### 4. Integrity
**VERDICT.**
- **Hashes:**
  - per source: streaming SHA-256 at upload, with the blob path `blobs/sha256/ab/cd/<hash>` opened `'xb'` and made read-only;
  - per pointer: `quote_sha256` plus `page_text_sha256`, `crop_sha256`, `row_sha256` (the raw CSV line bytes), and `window_sha256` (the canonical Arrow IPC slice);
  - telemetry: the partition hash is re-checked on every proof view, and the CSV → partition chain is verified once per build.
- **Records and versions:**
  - `record_hash = sha256(JCS(body − wall-clock fields))`, using RFC 8785 via the `rfc8785` package;
  - `manifest_hash = sha256(parent_manifest_hash ‖ sorted record_hashes ‖ config_hash ‖ engine_sha ‖ lockfile_hash ‖ sorted source sha ‖ snapshot_sha256)`.
- **`GET …/integrity`** re-walks the chain. The expert view shows a green or red badge.
- **External anchor (P0).** The `manifest_hash` of every demo version is shown in the UI. It is appended to `anchors/demo_roots.txt` and **pushed to the remote repository before going on stage**.
  - I tighten the debaters' consensus here: a *local* commit can be rewritten by the same attacker, so only a pushed remote commit with a server-side timestamp is an anchor.
- **Ed25519 signing is P1, and only under real key custody:**
  - the public key is committed and pushed before the event;
  - the private key lives only on a team member's laptop (`age`-encrypted) and never on the serving box;
  - signing happens at publish time with a CLI;
  - the manifest carries a `key_id`.
  - If that custody cannot be met, do not ship signing.

**WHY.**
1. Triggers prevent accidents. The chain detects edits. The pushed anchor detects an edit to the chain itself. Those are three distinct guarantees.
2. Pointer-level hashes keep a re-check under 1 s.
3. A signing key in `.env` on the same box can be re-signed by anyone who can edit the DB (Red Team A-d is correct).

**Losing arguments.**
- **Merkle inclusion proofs:** no persona needs to prove one claim without the log. The sorted-hash commitment gives a deterministic root.
- **P0 signing at h28:** this is theatre without custody.

**P0** hashes, chain, snapshot hash, pushed anchor. **P1** Ed25519 with off-box key. **P2** Object Lock and an external transparency log.

**Residual risk.** Root access on the laptop can rewrite the data and re-render the UI. **Mitigation:** compare against the remote anchor, and state the threat model honestly.

**Would change if** a third-party auditor must verify a single claim offline. Then add Merkle proofs.

### 5. Determinism and versioning
**VERDICT.**
- **IDs:** `claim_id = "clm_" + sha256(JCS(semantic fields + pointer + method{extractor, version, rule_id}))[:24]`. Display labels such as C-17 and S-88 sit in a separate `label` column, assigned from `seed/labels.yaml` by mention key.
- **No wall-clock fields in hashes.** Time comes from the `Clock` port and is server-side UTC.
- **Config bundle** `config/*.yaml`: tolerances, τ values, α, ontology with quantifiers, phrases, aliases, shifts, `plant_tz` and envelope params. `config_hash = sha256(canonical bundle)`, and the human tag `gate-v1.3+<hash8>` maps to the hash.
- **dateparser** always runs with `RELATIVE_BASE = observed_time`, a fixed `DATE_ORDER` and a fixed `TIMEZONE`.
- **Nondeterministic readers** (Tesseract, and later the VLM and LLM) store their raw outputs in `extraction_cache`. Replay reads only from the cache. **A cache miss under replay is an error.**
- **Canonicalisation:**
  - floats are serialised for hashing as fixed 6-decimal strings;
  - every collection is sorted by `(valid_start, claim_id)`;
  - pandas quantiles use an explicit `method="linear"`;
  - `PYTHONHASHSEED=0` is set in the image.
- **"Verify replay"** button: `POST …/versions/{v}/replay` rebuilds and compares `manifest_hash`.
- **HumanDecisions** are keyed to a stable **mention key** `(source_sha256, locator)`. If the evidence hash under that key changes, the decision becomes `stale` and the review item re-opens.

**WHY.** Byte-level equality makes NFR-4 testable. Mention keys keep decisions from being orphaned when the extractor version changes (W3).

**Losing arguments.** None remain. One honesty correction: "byte-identical on two laptops" holds for **replay from artifacts**, and for **fresh extraction only inside the pinned image**. Say exactly that.

**P0** all. **P1** cross-machine CI determinism job. **P2** none.

**Residual risk.** A transitive dependency changes float output. **Mitigation:** the lockfile hash is in the manifest, and the golden manifest test runs in pre-commit from h16.

**Would change if** never on the cache rule.

### 6. Extraction
**VERDICT.**
- **PDF: PyMuPDF behind the `PdfReader` port.** It is used for `rawdict` char bboxes, span size and colour, and page rendering to PNG at a fixed 150 dpi, cached by `(source_sha, page, dpi)` and hashed.
  - `char_start` and `char_end` index into the **hashed page-text artifact**. This makes FR-ING-1's acceptance test well defined.
  - AGPL is disclosed in the README, which depends on U-1. Production swaps to **pypdfium2** (Apache-2.0/BSD) behind the same port.
- **Hidden-text guard (T-06):**
  - a span with font size < 4 pt, or a bbox outside the page CropBox, is **held**;
  - in addition, the bbox crop of the rendered PNG must have greyscale std-dev ≥ 8 (0–255 scale), otherwise the span is held with the reason "text not visible".
  - The pixel test is primary. It catches white-on-white, text covered by a rectangle, and invisible render mode, without needing to know which trick was used.
- **OCR: Tesseract 5.x, pinned in the image.**
  - `image_to_data` gives word boxes and confidences.
  - The re-read crops the bbox with 8 px padding, upscales ×2 with Otsu binarisation, and runs `--psm 7` with a digit/unit whitelist. It is **labelled a "consistency check"**.
  - Plausibility: each authored gauge declares a physical range. A value outside it, or a dropped decimal (69 vs 6.9), goes to review.
  - `ImageOps.exif_transpose` and an EXIF strip produce a derived image with its own hash. OCR, bboxes (`coord_space=oriented_px`) and display all use that image.
- **Data-authoring rule:** gauges are digital or printed readouts. Analogue needles are out of scope and stated as such.
- **Tables:** CSV only in P0. XLSX is P1, which removes the zip-bomb surface.
- **LLM (P1).** Schema output, temperature 0, no tools, an offline recorded cache. The verifier requires:
  1. an exact match after NFC and whitespace collapse, with an offset map;
  2. a quote of at least 12 characters that is unique in the document, or else rejection;
  3. the value and unit re-derived by the rule number-unit parser from the quote, which must equal the proposal;
  4. the entity always taken from the resolver, never from the LLM;
  5. a qualitative class that differs from the phrase ontology's class sends the claim to review as "LLM-only interpretation".

**WHY.**
1. PyMuPDF is the only single library that gives offsets, bboxes, span attributes and rendering together, about 3 h cheaper than the alternatives.
2. The PNG proof keeps every PDF byte out of the browser.
3. Tesseract is deterministic on CPU and about 30 MB. EasyOCR pulls about 2 GB of torch, has GPU nondeterminism and downloads models at first run.

**Losing arguments.**
- **pdfplumber (Red Team R1):** it needs a second renderer and is 5–10× slower. The Red Team conceded.
- **Red Team R2 dropping re-derivation:** "value inside the quote" still accepts "6.9" proposed as 8.9 when both numbers are in the quote. Re-derivation of the value and unit only is about 20 lines.

**P0** PyMuPDF, PNG, hidden-text guard, Tesseract, re-read, plausibility, EXIF. **P1** LLM and verifier, VLM second reader (the real independence), XLSX. **P2** pypdfium2 swap.

**Residual risk.** Correlated OCR misreads. **Mitigation:** the plausibility check, a lower image extractor prior (0.80), and an honest label.

**Would change if** U-1 is "no". Then use pypdfium2 from day 1, about +3 h.

### 7. Entity resolution, timeline, review
**VERDICT.**
- **Resolver** as in §10.1: `rapidfuzz` WRatio, an alias table, context features, a named `digit_transposition` feature, and per-feature scores stored on each candidate.
  - **Auto-link** needs `score ≥ τ_link (0.85)`, a margin ≥ `δ_link (0.15)`, **and at least one agreeing non-string feature**.
  - A serial conflict is a hard veto.
  - Weights are tuned on **dev** alias seeds only. Whatever the holdout gives for "Press 21" goes on the slide.
- **Time:**
  - each case declares `plant_tz` (demo: `Asia/Kolkata`, shown in the UI);
  - naive dataset timestamps are interpreted as plant-local and labelled "assumed plant-local";
  - a day is `[D 00:00, D+1 00:00)` local, converted to UTC;
  - with no document date, `granularity=unknown`, and check 3 fails with "time unknown". `file_timestamp` is never used as the basis of valid time.
  - Overlap uses `max(start) < min(end)` on half-open intervals.
- **Review** sits between normalisation and the gate. Held items never form gate pairs.
  - A decision writes a HumanDecision claim and a `review_event`, then runs the synchronous re-run.
  - **Escalate** is a decision type. Auto-escalation after 1 working day is computed at read time from the `Clock`.
  - **"Mark conflict explained"** never changes the outcome or removes the card. It adds a status badge and a reason.

**WHY.** These are the T-10, T-11 and T-12 closures at low cost, and the reason strings *are* the content of Demo 2.

**Losing arguments.** None remain.

**P0** all. **P1** shift-level envelopes. **P2** an ML matcher (candidates only).

**Residual risk.** The `plant_tz` assumption itself. **Mitigation:** it is declared and shown, and A1 is checked at a pilot.

**Would change if** a real plant gives per-source timezones. Then `tz` becomes per source.

### 8. Frontend
**VERDICT.**
- **Astro static output** (`output: 'static'`), Tailwind, and **one `client:only="react"` island per page**: `/`, `/case?id=`, `/case/expert?id=`, `/review`, `/eval`, `/login`.
- FastAPI serves `dist/` from the **same origin**. In dev, Vite proxies `/api`.
- **Data:** TanStack Query, with query keys that **always include the version**. A version badge appears on every card.
- **Proof views:**
  - a single `RegionViewer` draws the server PNG or derived image with an absolutely positioned bbox overlay;
  - text is shown with React text-node slicing around `[char_start, char_end)`;
  - tables use a server window of ±25 rows with `scrollIntoView`;
  - sensor windows use ECharts (`echarts-for-react`) with `markArea` for the window, a band series for the alarm band, and LTTB sampling.
- **Timeline:** an ECharts custom series showing valid and observed time.
- **Security:**
  - `dangerouslySetInnerHTML` is banned by eslint `react/no-danger`;
  - CSP is `default-src 'self'; script-src 'self' <hashes>; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`;
  - hashes are emitted by Astro's built-in CSP support, or by a post-build hashing script if the version in use lacks it;
  - `build.inlineStylesheets: 'never'`;
  - the CSP is verified once in Report-Only mode.
- **Live updates: SSE (P1).** WebSocket is rejected.

**WHY.**
1. Static output gives one policy point, `SameSite=Strict` cookies and build-time CSP hashes.
2. Removing pdf.js removes the biggest frontend time sink and in-browser PDF JavaScript.
3. One island per page avoids a cross-island store.

**Losing arguments.**
- **Astro SSR (Architect R1):** a second runtime, a second auth surface, cookie forwarding. Conceded.
- **pdf.js:** text selection is not required.
- **TanStack Table, nanostores:** they fix problems this design does not have.

**P0** all except SSE. **P1** SSE, evaluation dashboard polish. **P2** none.

**Residual risk.** The CSP breaks hydration on demo day. **Mitigation:** the Report-Only check at h30, and a Playwright run under the enforcing CSP.

**Would change if** server-side personalisation is ever required, which it is not.

### 9. API
**VERDICT.**
- **REST under `/api/v1`, case-scoped everywhere:**
  - `/cases/{cid}/versions/{v}/{state|story|timeline|claims|comparisons|conflicts|review}`
  - `/cases/{cid}/claims/{id}/evidence`
  - `/cases/{cid}/claims/{id}/recheck` (POST)
  - `/cases/{cid}/review/{rid}/decision`
  - `/cases/{cid}/versions/{v}/{manifest|integrity|replay}`
  - `/cases/{cid}/latest`, which returns `307` to the versioned path
- **One `resolve_case_and_authorize` dependency** maps every ID to a case and checks the role.
- **Errors:** RFC 9457 `application/problem+json` with stable `type`s: `evidence-changed`, `already-decided`, `build-in-progress`, `unknown-unit`, `quote-not-verified`, `unsupported-media`, `payload-too-large`, `append-only`.
- **Pagination:** offset/limit over frozen versions.
- **Cache headers:**
  - versioned JSON: `Cache-Control: private, max-age=31536000, immutable`, `ETag: "<manifest_hash>"`, `Vary: Cookie`;
  - `latest`, `recheck` and writes: `no-store`;
  - hashed static assets: `public, immutable`;
  - the HTML shell: `no-cache`.
- **Decision body:** `{choice, reason (≥15 chars), base_version, shown_evidence_hash}`, validated with `extra="forbid"`. A `reviewer` field returns **422**, so a spoofing attempt is visible.
- **409 semantics.** This tightens the consensus. Return 409 **only** when:
  - **(a)** the item is already decided (`already-decided`, with the existing decision), or
  - **(b)** the item's current evidence hash ≠ `shown_evidence_hash` (`evidence-changed`).

  A stale `base_version` with an untouched item is **accepted** and recorded. Otherwise unrelated decisions would block each other.
- **Override** of an existing decision needs `senior_reviewer` and an explicit `supersedes` field.

**WHY.**
1. Case scope closes the PRD's IDOR (T-25).
2. `public` on authenticated content leaks across users through any shared cache (Red Team A-a is correct). Immutability is a freshness property, not an audience property.
3. Precise 409s stop lost updates without false conflicts.

**Losing arguments.**
- **Cursors, Idempotency-Key header:** conceded by everyone, and correctly.
- **"Ignore the spoofed field silently":** a 422 is more auditable.

**P0** all. **P1** Schemathesis. **P2** tenant in the path.

**Residual risk.** The 307 redirect cached by a browser. **Mitigation:** `no-store` on `latest`.

**Would change if** a public read-only share link is introduced. Then a separate signed-URL route may use `public`.

### 10. AuthN/AuthZ
**VERDICT.**
- **Seeded per-user accounts** with **argon2id** hashes (`argon2-cffi`, default parameters).
  - Passwords are generated at seed time with `secrets.token_urlsafe(9)` and written to `seed/credentials.local.txt`, which is git-ignored. The judges get a printed card for the `judge-reviewer` account.
- **Opaque server sessions:** `secrets.token_urlsafe(32)` in a `sessions` table, rotated on login, 8 h idle expiry, with logout.
- **Cookie:** `HttpOnly; SameSite=Strict; Path=/`, plus `Secure` when served over TLS. Browsers accept Secure cookies on `localhost`; LAN mode requires mkcert TLS.
- **Writes** require the `X-TRACE-CSRF` header and `Content-Type: application/json`.
- **Login throttling:** 5 failures per username per 5 minutes, then a 5-minute lock.
- **Binding:** `127.0.0.1` by default. `TRACE_LAN=1` is an explicit opt-in that requires TLS.
- **Roles:** `viewer`, `reviewer`, `senior_reviewer`, `ingestor` (uploads), `evaluator` (`/eval/run`).
- **Identity comes only from the session.** Each decision stores `user_id`, a display-name snapshot, `role`, `base_version` and `shown_evidence_hash`.

**WHY.**
1. The requirement is **individual attribution** (US-3, FR-UI-4). A per-role PIN is a shared secret, so any reviewer can sign as any other. That fails attribution as surely as pick-a-name does.
2. The cost difference between per-user passwords and PINs is about 30 lines.
3. Opaque server sessions need no signing secret, which removes the default-`secret_key` foot-gun.

**Losing arguments.**
- **Pick-a-name (Pragmatist R1):** anyone on the LAN is "Senior". Conceded.
- **Red Team R2's PIN/localhost:** localhost-only still lets every presenter at the keyboard be anyone, so I keep localhost **as well as** passwords, not instead of them.
- **JWT:** rejected by all.

**P0** all. **P1** a full authz matrix test, admin UI. **P2** OIDC at the gateway, per-tenant ACLs.

**Residual risk.** A shared demo laptop with a logged-in session. **Mitigation:** a visible "signed in as" header, logout between demo personas.

**Would change if** the host provides SSO. Then use OIDC.

### 11. Observability
**VERDICT.**
- `structlog` JSON with `request_id, case_id, build_id, version, config_hash, stage`.
- **Never log document text, quotes or OCR text.**
- **Per-stage `ms` and counters stored on the build row** and shown in the expert view: claims by modality, held, gaps, rejected quotes, re-check mismatches, stale builds, 409s and login lockouts. This proves NFR-7 on screen.
- Stage names equal the future OpenTelemetry span names.

**WHY.** Judges see the expert view. Nobody opens Jaeger. The audit trail is the data plus the chain, not the logs.

**Losing arguments.** OTel/Prometheus in P0. Conceded by the Architect.

**P0** as above. **P1** OTel auto-instrumentation, `/metrics`. **P2** alerting and runbooks.

**Residual risk.** None material.

**Would change if** a multi-process production deployment. Then OTel.

### 12. Testing
**VERDICT.**
- **Golden tests:** Demos 0–6 built from seed, pinning the outcome, the check table, the computed numbers and `manifest_hash`. The goldens pin **computed** values after the h0 data check, never the PRD's numbers.
- **Hypothesis properties:**
  - gate symmetry;
  - gate totality (exactly 1 of the 4 outcomes);
  - never-average: no derived numeric value lies strictly between conflicting parents unless it equals an observed parent;
  - unit round-trip;
  - unknown units never convert;
  - half-open overlap commutativity;
  - **gap monotonicity**: deleting readings never moves an outcome toward "agree";
  - hash-chain single-byte detection.
- **Named correctness tests** are listed in the threat register (Part 2).
- **Hostile corpus**, 7 files: bomb PNG, HTML-as-PDF, SVG, traversal filename, white-text PDF, EXIF-6 photo, XSS text.
- A **minimal authz test**: a viewer POSTing a decision gets 403, and a cross-case claim gets 404.
- **Playwright** runs under the enforcing CSP:
  - Demo 0 proof opens in < 1 s;
  - Demo 2 decision updates the card in < 2 s;
  - a tamper (byte flip) shows a red "evidence changed";
  - the XSS fixture triggers no dialog;
  - every panel shows the same version.
- **`tsc --noEmit`** on the generated types is the contract test.
- **Evaluation hygiene:**
  - dev and holdout fault seeds are disjoint;
  - the config hash is **committed and pushed before the holdout run** and printed in the report;
  - the non-builder labeller authors at least 30% of the faults. If U-2 fails, person D, who wrote no rules, labels instead, with that disclosed.

**WHY.** Invariants catch exactly what judges probe, and the goldens double as the h33 smoke test.

**Losing arguments.** Schemathesis and the full authz matrix in P0. Both are P1.

**P0** all above. **P1** Schemathesis, full matrix, mutated-PDF fuzzing. **P2** none.

**Residual risk.** The holdout is still authored by insiders. **Mitigation:** disclosure plus per-fault-type failures published.

### 13. Deployment and scale path
**VERDICT.**
- **Hackathon:**
  - one Linux image built multi-stage (Node builds `dist/`; then `python:3.11-slim` + `tesseract-ocr` + `tesseract-ocr-eng`, pinned by digest);
  - non-root, read-only root filesystem, one `data/` volume, no outbound network needed;
  - committed `uv.lock` and `package-lock.json`, installed with `npm ci`;
  - a native fallback with `uv run`;
  - two laptops, pre-built cases, a recorded backup video;
  - `make demo` seeds and builds.
- **Scale path:**
  1. a CDN in front of **immutable versioned JSON**, with authorization **validated at the edge** (signed cookie or token) and the cache key `(tenant, case, version)`, so all authorised users of a tenant share hits without `public` leakage;
  2. a stateless read tier with Redis;
  3. Postgres with the same triggers, RLS and read replicas;
  4. S3 Object Lock for blobs;
  5. Temporal **when** paid OCR/VLM/LLM calls need durable retries;
  6. a transactional outbox with LISTEN/NOTIFY driving the snapshot builder and SSE.
- **Kafka, Citus and TimescaleDB are "planned only if":** Kafka with 3 or more independent consumers, Citus at multi-TB per-tenant write volume, TimescaleDB with real-time ingest.

**WHY.** 1M *readers* is a cache problem, and frozen versions are perfectly cacheable. Every other box must earn its place through write volume.

**Losing arguments.** §15 as written overclaims. All three debaters agreed, and I concur.

**P0** the container. **P1** SBOM, `pip-audit`. **P2** the rest.

**Residual risk.** Edge auth is complex. **Mitigation:** it is a design note, not built.

### 14. Correctness floor: envelope and gate statistics
This is the most consequential ruling. It replaces PRD §10.3–10.6.

**(a) Why the PRD rule fails.** The PRD tests "every hourly value of 4 channels inside p5–p95". That is about 96 tests per day at about 10% exceedance each, so a quiet day almost never passes (T-01). The deck's "34–47" appears to be exactly such a p5–p95 hourly band.

**(b) The test: robust max-z with a split-conformal threshold.** For machine *m*:
1. **Quiet days Q:**
   - no error, maintenance or failure within ±3 days;
   - every event log's declared `coverage_period` covers the day (otherwise the build **refuses** with `/problems/log-coverage`);
   - telemetry has 24/24 hours on every channel;
   - the day is **outside the case window ±3 days**.
2. **Per-channel robust centre and scale** from the hourly values of Q: `med_c`, `s_c = 1.4826·MAD_c`. If `MAD_c = 0`, the channel is excluded and listed as "degenerate scale".
3. **Daily family statistic** over the channels C in the phrase's scope: `T_d = max_{c∈C, h∈d} |x_{c,h} − med_c| / s_c`.
4. **Threshold.** The ascending order statistic `T* = T_(k)` of `{T_d : d∈Q}`, with `k = ⌈(1−α)(n+1)⌉`, `α = 0.05`, `n = |Q|`.
   - Under exchangeability, this **guarantees P(false alarm on a new quiet day) ≤ α** with no Bonferroni guesswork.
   - It is undefined when `n < 19`. Then **T\* is pooled from the T_d of all same-model machines**, which is valid because T_d is unitless. `med_c` and `s_c` stay per machine if n ≥ 10, otherwise they come from the model level. The result is labelled "thin history / model-level".
5. **Displayed alarm band** per channel: `med_c ± T*·s_c`. The p5–p95 hourly range may be shaded lighter, labelled "typical, not the alarm threshold".
6. **Raw confidence of a sensor-state claim:**
   - `1 − p` with the conformal p-value `p = (1 + #{d∈Q: T_d ≥ T_D})/(n+1)`;
   - multiplied by `coverage_fraction` and by `history_factor` (1.0, or 0.8 for thin history);
   - labelled "uncalibrated".
- **Training policy is a config parameter.** For retrospective cases, including the demo, use `all_except_case_window`. For live monitoring in production, use `before_only`.
  - This overrules the R2 "before only" consensus for the demo. Back-of-envelope: with about 0.22 events per machine-day and a ±3-day exclusion, about 20% of days are quiet. Before 11 March that is roughly 14 days, which is below n = 19.
  - Excluding the case window ±3 days already removes leakage.
  - **Person D measures the actual quiet-day counts at h0.**
- **Robustness:** an envelope move of more than 10% in T\* between versions opens a review item.

**(c) Envelope identity.** `envelope_id = sha256(machine, channel_scope, statistic="robust_max_z", granularity="day", sorted quiet days, params, data partition hashes)`. Check 4 requires the claim's `(statistic, granularity, series_id)` to equal the envelope's.

**(d) S-88 is day-level.** S-88 is an inferred claim with:
- `attribute=operating_state`, `value=abnormal`, granularity day, valid `[14 Mar 00:00, 15 Mar 00:00)` local;
- statistic `T_D` versus `T*`;
- evidence: four `sensor_window` day claims plus the `envelope_id`.

The 14:00–15:00 peak is a **child detail claim**, S-88.1 (hour granularity, vibration peak, `window_sha256`). C-17 (day) is compared with S-88 (day), so check 3 is well defined (W5).

The error rows feed separate comparisons: the "ran normally" ∀ scope includes "no error events". The card groups all disagreeing pairs of C-17 into one conflict card, with the error rows as supporting context. Single-channel phrases ("high vibration") use C = {vibration} with its own T\*.

**(e) Quantifiers** live in the ontology, on every phrase class.
- **∀ phrases** ("ran normally", "no issues"):
  - **disagree** needs any observed violation (`T_D > T*` over the observed hours) or an error/failure event in the window;
  - **agree** needs **100% coverage** of every channel in scope and `T_D ≤ T*`, with logs covering the window;
  - otherwise **"We can't tell (partial: n h missing)"**.
- **∃ phrases** ("vibration noticed"): **agree** needs an observed violation; **disagree** needs full coverage with no violation.
- With partial data the max is taken over fewer tests, so "disagree" on partial data is conservative.
- The 80% `min_coverage` **only labels gaps** and never licenses "agree".
- Check 5 fails only at zero coverage. Partial coverage flows into check 6's quantifier rule.

**(f) Gaps.**
- Missing hours produce `GapClaim(missing)`.
- A flatline is variance ≤ ε (`ε = 1e-6·s_c`) over ≥ 6 h, **unless** a stop or maintenance event explains it. Then it is "stopped", not a gap.
- **Duplicate `(machine, channel, ts)` readings with different values are never averaged.** That hour becomes `GapClaim(conflicting_readings)` (T-14, promoted to P0 because it *is* NFR-6).

**(g) Units.**
- MS telemetry is `unit_status = "sensor_native"`, displayed as "sensor units (undocumented)". It is never converted.
- Check 4 passes only against an envelope learned from the same `series_id`.
- **Gauge vs telemetry → "They can't be compared: telemetry unit undocumented."**
- Assuming kPa or psi for MS pressure would be precisely the "guessing units" that §2.2 forbids. The fact that values around 100 resemble psi is a coincidence, not a datasheet.

**(h) Confidence formula.**
- `raw = extractor × entity_link × time_precision × unit_factor × reliability_adj × (1 + λ·independent_corroboration)`, clipped to [0, 1];
- `reliability_adj = 0.5 + r` (the neutral r = 0.5 maps to 1.0); `λ = 0.2`;
- corroboration counts only between sources whose provenance is **declared** and disjoint. Undeclared provenance gives 0 credit.
- With the PRD's own components, C-17 = 0.95·0.97·0.90·1·1·1 = **0.83**, not 0.71.

**P0** all of (a)–(h). **P1** load-aware `rotate` terciles (same construction per bin), shift-granularity envelopes, Platt/isotonic recalibration. **P2** none.

**Residual risk.**
- Exchangeability fails because of seasonality or drift.
- The real M-21 on 14 March does not exceed T\*.

**Mitigation:**
- report the measured holdout false-alarm rate with a 95% Wilson CI. The test fails only if the CI lower bound is > 5%.
- run the h0 reality check. If the day does not exceed T\*, pick the real machine-day that does, or plant it with the seeded injector and label it "planted for the demo".

**Would change if** the holdout false-alarm rate is materially above α. Then use a de-seasonalised baseline, such as a rolling 30-day med/MAD.

### 15. Security floor
**VERDICT.** These P0 controls total about 8.5 h, inside the ledger.
- **S1** Per-user argon2id login, opaque sessions, identity only from the session, 422 on a `reviewer` field, `127.0.0.1` binding by default.
- **S2** `SameSite=Strict`, the `X-TRACE-CSRF` header, a JSON-only content type on writes.
- **S3** The precise 409 rules (item 9), senior-only supersede.
- **S4** The killable build process, heartbeat sweep, one build per case.
- **S5** Triggers, chain, snapshot hash on LRU fill, pushed remote anchor.
- **S6 Uploads stay enabled but restricted to the `ingestor` role.** Rules:
  - streaming caps of 25 MB for documents and 200 MB for telemetry, enforced in middleware before the body is read;
  - a magic-byte allowlist of {PDF, PNG, JPEG, CSV, TXT, MD} that must agree with the extension;
  - **no SVG, TIFF or XLSX**;
  - `Image.MAX_IMAGE_PIXELS = 40e6`, with the warning turned into an error;
  - a PDF page cap of 50;
  - client filenames are never used in a path;
  - a free-disk check.
- **S7** Originals are served with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`. Display images are derived and EXIF-stripped.
- **S8** The eslint ban and the CSP from item 8.
- **S9** The central `resolve_case_and_authorize` dependency.
- **S10** No document text in logs, and no network calls in P0.
- **S11** A non-root, read-only-rootfs container.

**WHY uploads stay on.** The PRD's API includes upload, and a judge will ask "upload my file". The hardening costs 1.5 h, and disabling the endpoint would leave the sandbox untested.

**Losing arguments.**
- "Disable upload in demo mode" (Red Team R2 option): it hides the feature instead of securing it.
- A cgroup-tuned sandbox plus fuzzing in P0: the killable child with RLIMIT covers T-20 to the level its L/H rating warrants.

**P1** fuzzing, `pip-audit`, SBOM, rate limits on `/eval/run`. **P2** cosign, tenant RLS, crypto-shredding.

---

## Part 2 — (a) Final threat register

| ID | Final status | Closing control | Named test |
|---|---|---|---|
| T-01 quiet-day false alarms | closed-P0 | Conformal max-z, α = 0.05 (item 14b) | `test_quiet_day_false_alarm_rate_holdout` (≥200 machine-days, Wilson CI) |
| T-02 statistic mismatch | closed-P0 | Envelope key + check 4 | `test_check4_rejects_statistic_or_granularity_mismatch` |
| T-03 partial "agree" | closed-P0 | ∀/∃ quantifiers, 100% coverage for ∀-agree | `test_spike_in_gap_never_agree`; `prop_deleting_readings_never_toward_agree` |
| T-04 envelope poisoning | closed-P0 | Log `coverage_period`, case-window exclusion, robust stats, >10% T\* drift review | `test_envelope_refuses_without_log_coverage`; `test_planted_hot_days_bounded_shift`; `test_case_window_excluded` |
| T-05 invented units | closed-P0 | `sensor_native`, same-series envelope only | `test_gauge_vs_telemetry_cannot_compare`; `test_no_mm_s_in_api_or_ui` |
| T-06 hidden PDF text | closed-P0 | Pixel std-dev on the PNG crop + size/CropBox rule | `test_white_text_pdf_zero_claims_one_review` |
| T-07 LLM wrong value | mitigated-P1 | Value/unit re-derivation, resolver-only entities | `test_llm_mutations_zero_accepted` (50 mutations) |
| T-08 prompt injection | mitigated-P1 | No tools, schema, re-derivation, offline cache | `test_injection_fixture_no_outcome_change` |
| T-09 OCR misread | mitigated (P0 plausibility, P1 VLM) | Range plausibility, "consistency check" label, prior 0.80 | `test_decimal_drop_69_goes_to_review` |
| T-10 over-merge | closed-P0 | Non-string feature required, serial veto | `test_transposed_digits_never_autolink` |
| T-11 day boundary/TZ | closed-P0 | `plant_tz`, local half-open days | `test_local_day_boundary_2330` |
| T-12 guessed time | closed-P0 | `granularity=unknown`, mtime never used | `test_undated_note_time_unknown` |
| T-13 flatline vs stop | closed-P0 | ε variance + stop/maintenance suppression | `test_frozen_sensor_flatline`; `test_stop_event_not_gap` |
| T-14 duplicate timestamps | closed-P0 (promoted) | `GapClaim(conflicting_readings)`, no mean | `test_duplicate_ts_not_averaged` |
| T-15 independence laundering | closed-P0 | Undeclared provenance = 0 credit (near-duplicate detection is P1, labelling only) | `test_undeclared_provenance_no_corroboration` |
| T-16 decompression bomb | closed-P0 | `MAX_IMAGE_PIXELS` error, XLSX off, child RLIMIT | `test_hostile_corpus[bomb_png]` + health check during upload |
| T-17 oversized upload | closed-P0 | Streaming cap middleware | `test_300mb_rejected_streaming` |
| T-18 MIME/polyglot | closed-P0 | Magic allowlist, no SVG, attachment/nosniff/sandbox | `test_hostile_corpus[html_as_pdf, svg]` |
| T-19 path traversal | closed-P0 | Hash-only paths, ID regex | `test_hostile_corpus[traversal_name]` |
| T-20 parser RCE | mitigated-P1 | Killable non-root child, pinned libraries, CSV/PDF/PNG/JPEG only | P1 `fuzz_mutated_pdf_smoke` |
| T-21 EXIF/PII | closed-P0 | `exif_transpose`, strip, derived hash, `oriented_px` | `test_exif6_bbox_alignment_and_no_gps` |
| T-22 XSS | closed-P0 | Text nodes, `react/no-danger`, CSP, no pdf.js; no CSV export in P0 | `e2e_xss_fixture_no_dialog_under_csp` |
| T-23 forged decision | closed-P0 | Session identity, 422 on `reviewer` | `test_spoofed_reviewer_field_422`; `test_viewer_decision_403` |
| T-24 racing decisions | closed-P0 | Already-decided / evidence-changed 409, `BEGIN IMMEDIATE` | `test_20_parallel_decisions_one_wins` |
| T-25 IDOR | closed-P0 (single tenant) | Case-scoped routes + central dependency | `test_cross_case_claim_404` |
| T-26 CSRF | closed-P0 | SameSite=Strict + header + JSON-only | `test_cross_origin_form_post_403` |
| T-27 tampering | closed-P0 (detection) | Triggers, chain, snapshot hash, remote anchor | `e2e_byte_flip_evidence_changed`; `test_trigger_aborts_update`; `test_chain_verify_detects_edit`; `test_snapshot_hash_mismatch` |
| T-28 stuck jobs | closed-P0 | Heartbeat sweep, partial unique index, killable child | `test_kill_mid_build_marks_stale_then_rebuilds` |
| T-29 stale cache | closed-P0 | Version in every key and URL, `private`, `no-store` on latest | `e2e_all_panels_same_version` |
| T-30 typed-in numbers | closed-P0 | Computed goldens, synthetic badges, injection manifest | `test_no_magic_literals_in_engine` (grep 64/34/47/0.71/0.22) |
| T-31 metric gaming | closed-P0 (process) | Disjoint seeds, config hash pushed pre-holdout, ≥30% external faults | `test_eval_report_has_pushed_config_commit` |
| T-32 uncalibrated shown as probability | closed-P0 | "uncalibrated" label, ECE bootstrap CI + bin counts | `test_ui_uncalibrated_label`; report check |
| T-33 LLM outage | mitigated-P1 (N/A in P0: zero network) | Offline cache, budget, rules fallback | `test_network_off_build_succeeds` |
| T-34 endpoint abuse | mitigated (P0 role gate + one run, P1 rate limit) | `evaluator` role, in-flight lock | `test_parallel_eval_runs_one_proceeds` |
| T-35 tenant isolation | accepted-risk (P2) | `case_id`-scoped repository now, RLS later | — |
| T-36 erasure vs append-only | accepted-risk (P2 design) | Crypto-shredding note; chain over ciphertext/HMAC | — |
| T-37 supply chain | mitigated-P1 | Lockfiles P0, digest-pinned base; `pip-audit`/SBOM P1 | CI lockfile check |
| T-38 clock skew | closed-P0 | Server UTC clock, version ordering | `test_client_timestamp_ignored` |
| N-1 mutable status in "immutable" records (new) | closed-P0 | Derived status from `review_events` | `test_no_update_paths_status_derived` |
| N-2 local git anchor rewritable (new) | closed-P0 | Push to remote before the demo | Pre-demo checklist |
| N-3 conformal threshold undefined for n<19 (new) | closed-P0 | Model-level pooled T\* | `test_thin_history_uses_model_pool` |
| N-4 baseline answer typed in ("0.62") (new) | closed-P0 | Baseline computed offline (TF-IDF top-k + averaging/LWW) | `test_baseline_output_generated` |

---

## Part 3 — (b) Hour ledger (4 × 36 h = 144 h)

Each person has 5.5 h of staggered sleep and food, leaving **30.5 working hours each, 122 in total**.

Checkpoints:
- **h1** Tesseract smoke test on every laptop; h0 data reality check done.
- **h8** Pydantic schemas frozen; TS types generated.
- **h10** walking skeleton: one text claim and one sensor claim → gate → a card on screen.
- **h16** eval track starts; golden test in pre-commit.
- **h26** P1 starts only if Demos 0–6 goldens are green.
- **h30** feature freeze; CSP in Report-Only.
- **h33** rehearsal.
- **h35** anchors pushed.

| A — Ingest + platform security | h | B — Engine + correctness floor | h | C — Frontend | h | D — Data, store, API, eval | h |
|---|---|---|---|---|---|---|---|
| Kickoff, repo, ports | 1 | Kickoff, schemas owner | 1.5 | Astro/Tailwind, same origin, types | 1.5 | **h0 reality check + quiet-day counts** | 1.5 |
| Text/PDF rules, offsets, PNG render | 5.5 | Telemetry Parquet split, day windows, duplicates (T-14) | 2.5 | Case workspace + 5-step story | 4 | Authored seed: PDFs, photos, repair log, synthetic temperature, labels.yaml | 5 |
| Hidden-text guard (T-06) | 1.5 | **Conformal envelopes, quiet days, log coverage, fallback (T-01/02/04)** | 4.5 | Conflict card + gate table | 3 | SQLite schema, triggers, version_claims, review_events | 2.5 |
| CSV cell pointers, coverage_period | 2.5 | Gaps, flatline, quantifier coverage (T-03/13) | 1.5 | RegionViewer, text mark, table window | 4 | Record hash, manifest chain, snapshot hash, anchors, replay | 2.5 |
| OCR, re-read, plausibility, EXIF (T-09/21) | 4.5 | Units, `sensor_native` (T-05) | 1.5 | Sensor chart (band, window) | 3 | API routes, cache headers, 409, IDOR dependency, RFC 9457 | 3.5 |
| Upload hardening (S6/S7) | 1.5 | ER resolver, features, veto (T-10) | 3 | Timeline | 2.5 | Fault injector, 7 types, seeded, dev/holdout | 3 |
| Build child process, heartbeat, cache (S4) | 2.5 | Timeline, `plant_tz`, unknown time (T-11/12) | 2.5 | Review queue, decision panel, login | 3 | Baselines: TF-IDF, averaging/LWW, no-gate | 2 |
| Auth (S1/S2) | 2.5 | Gate, 6 checks, outcomes, card grouping | 4 | Expert view, envelope view, integrity/replay badges | 3.5 | Metrics: P/R/F1, false-alarm CI, ECE/Brier bootstrap, reliability | 2.5 |
| Hostile corpus tests | 1 | Trust formula, independence (T-15) | 2 | CSP, lint, version badges (S8) | 1 | Holdout protocol + report (T-31/32) | 1.5 |
| Playwright 5 scripts | 2 | Decision re-run path | 1.5 | Minimal eval page | 1.5 | Golden tests + determinism | 1.5 |
| Integration/bugfix | 3 | Hypothesis properties + false-alarm harness | 3 | Integration/polish | 2.5 | Docker image, two laptops, rehearsal | 2 |
| Buffer | 3 | Integration + buffer | 3 | Buffer | 1 | Buffer | 3 |
| **Total** | **30.5** | | **30.5** | | **30.5** | | **30.5** |

- **Correctness floor** is about 13 h, mostly in B's column. **Security floor** is about 8.5 h, mostly in A's and D's columns.
- **Total buffer is 10 h.**
- **Stretch order if green at h26:** SSE (1) → Ed25519 with off-box key (1) → VLM second reader → recalibration fit → load bins → LLM proposer + verifier → XLSX.

---

## Part 4 — (c) Required changes to the PRD

1. **Header "Single source of truth":** replace with *"Demo numbers are computed by the engine from the raw data; where a computed value differs from the deck, the deck is updated. Authored and planted values are badged."*
2. **§9.3 ClaimRecord:** delete `"version": 7`. Add the field rule: *"Claims carry no version; membership is recorded in `version_claims(case_id, version, claim_id)`. `claim_id` is content-addressed; `label` (e.g. C-17) is a display alias."*
3. **All `…T23:59Z` ends**: in §9.2 Event `ev-shift-0314` and in §9.3 C-17, change `"end": "2015-03-14T23:59Z"` to `"end": "2015-03-15T00:00Z"`. Add to §10.2: *"All intervals are half-open [start, end); a day is [D 00:00, D+1 00:00) in the case's `plant_tz`, stored in UTC."*
4. **S-88 (§9.3 example):**
   - `statement`: *"Machine 21 operating state on 14 Mar 2015 was outside its learned alarm band (robust max-z T = ⟨computed⟩ > T\* = ⟨computed⟩); largest excursion: vibration ⟨64⟩ at 14:00–15:00"*;
   - `valid_time`: `{start: 2015-03-14T00:00 local, end: 2015-03-15T00:00 local, granularity: "day"}`;
   - `method.rule_id: "state.abnormal_if_robust_max_z_gt_conformal_q95"`;
   - `derived_from`: the four sensor-window day claims and `envelope_id`;
   - add a child claim S-88.1 (hour, vibration peak).
   - §9.2 Measurement: `statistic: "hourly_peak"` stays on S-88.1, and `unit: "mm/s"` becomes `"sensor_native"`.
5. **"Peak 64 vs normal 34–47"** (§9.3, §9.5, Demo 0, §10.3 step 4): replace with *"peak ⟨computed⟩ outside alarm band ⟨med ± T\*·s, computed⟩ (typical p5–p95 range ⟨computed⟩ shown for context)"*. Remove "the normal range is 34 to 47" from §10.3.
6. **Units:**
   - §9.6: the vibration row becomes `sensor_native (undocumented) | compared only with same-series envelopes`, and the same applies to the MS pressure, voltage and rotation channels;
   - §21.2-1 becomes *"MS telemetry units are undocumented; channels are `unit_status = sensor_native`, never converted, and compared only against envelopes learned from the same series. Physical units apply only to authored sources."*;
   - Demo 3: delete "Telemetry is in kPa" and add the outcome *"Gauge 6.9 bar vs telemetry pressure → They can't be compared (telemetry unit undocumented)."*;
   - ComparisonRecord check 4 detail becomes `"same series scale (sensor_native, series telemetry/machine:21)"`.
7. **Confidence (§9.3, Demo 0, §10.8):** add *"`reliability_adj = 0.5 + r`; λ = 0.2; corroboration only between sources with declared, disjoint provenance."* C-17 becomes **0.83** (computed). S-88 becomes *"1 − conformal p-value × coverage × history factor, computed"*. Both are labelled uncalibrated.
8. **FR-NORM-4 and §10.3:** replace with the item 14(b) algorithm, verbatim:
   - quiet-day criteria including log coverage and 24/24 telemetry;
   - robust max-z;
   - `T* = T_(⌈0.95(n+1)⌉)`;
   - n < 19 → model-level pooled T\*; n < 10 → model-level med/MAD;
   - training policy `all_except_case_window` (retrospective) or `before_only` (live).
9. **§10.4:** add a "Quantifier" column. "ran normally / no issues / all good" = **∀** (scope: all channels + no error events). "high vibration / vibration noticed" = **∃** (vibration). "pressure low" = ∃ (pressure, lower side). "stopped" = ∃ (rotate stop or failure/maintenance event). Add the agree/disagree rules from 14(e).
10. **§10.6:** replace with *"<100% coverage creates GapClaim(missing) for the missing hours; it never licenses 'agree' for a ∀ claim. Flatline = variance ≤ ε over ≥ 6 h unless a stop/maintenance event explains it. Duplicate timestamps with different values → GapClaim(conflicting_readings), never averaged."*
11. **Demo 1a:** the expected outcome becomes *"disagree if a violation is observed in the 20 available hours; if the violating hours fall inside the gap, 'We can't tell (partial: 4 h missing)'; never 'agree'."*
12. **FR-UI-7:** becomes *"Live updates (P1): 'this case changed' notice over Server-Sent Events."* In the §15 diagram and table, "WebSocket" becomes "SSE".
13. **§13 API:** replace with the case-scoped, version-pinned table from item 9.
    - The decision body becomes `{choice, reason, base_version, shown_evidence_hash}`, with the reviewer taken from the session.
    - Add `POST /auth/login`, `POST /auth/logout`, `GET …/versions/{v}/{manifest,integrity}` and `POST …/versions/{v}/replay`.
    - Document the 409 and 422 rules.
14. **FR-UI-4:** *"The reviewer identity comes from the authenticated session; a reason of at least 15 characters is required."*
15. **FR-EVID-4:** *"Hackathon: one SQLite database (WAL) with append-only triggers, a content-addressed blob store, Parquet per machine, hashed JSON snapshots."*
16. **FR-EVID-3 and §9.5:** *"ReviewItem.status and ConflictRecord.status are derived from append-only review events and decisions, never updated."*
17. **FR-ING-1:**
    - acceptance: *"`quote == page_text[char_start:char_end]` where `page_text` is the hashed extracted-text artifact"*;
    - add the hidden-text rule.
18. **FR-ING-2:** XLSX moves to P1.
19. **FR-ING-4:** "re-read the cited box to confirm" becomes *"re-read the cited box with a different configuration (a consistency check, not independent verification); values outside the gauge's declared physical range go to review; images are EXIF-oriented before reading."* Remove EasyOCR from P0.
20. **FR-NORM-2 and §10.1:** add *"and at least one non-string feature agrees; a serial conflict vetoes a candidate."*
21. **FR-NORM-3:** add *"No document date → granularity unknown (never file mtime). Case declares `plant_tz`."* Add assumption **A7**: *"Plant time zone is declared per case; naive timestamps are interpreted as plant-local."*
22. **FR-TRUST-2 and §10.7:** *"Undeclared provenance gives zero corroboration credit; near-duplicate detection (P1) only labels suspected derivation."*
23. **NFR-4:** add *"given the extraction-artifact cache; fresh OCR is reproducible inside the pinned image."*
24. **§12.1 and §12.2:**
    - add *"Quiet-day false-alarm rate ≤ 5% on ≥ 200 holdout quiet machine-days (Wilson 95% CI)"*;
    - add *"dev/holdout seed split; config hash pushed before holdout"*;
    - ECE is reported with a bootstrap CI and bin counts.
25. **§12.3 and Demo 0 baseline:** replace *"Machine 21: probably fine (0.62)"* with *"the baseline's actual output (offline TF-IDF top-k retrieval + averaging/last-write-wins answer), recorded in the eval report."*
26. **§14.1:**
    - Frontend becomes *"Astro (static) + Tailwind + React islands, ECharts, TanStack Query; proof pages rendered server-side to PNG (no pdf.js)"*;
    - PDF becomes *"PyMuPDF (AGPL, disclosed; production: pypdfium2)"*;
    - Images become *"Tesseract 5 (pinned)"*;
    - Data becomes *"pandas + pyarrow, SQLite (single file)"*.
27. **§22:** add *"₹0 licence assumes TRACE is distributed under AGPL-compatible terms or PyMuPDF is swapped for pypdfium2."*
28. **§15:**
    - CDN becomes *"edge-authorised cache keyed by (tenant, case, version); never `public` for authenticated content"*;
    - Kafka, Citus and TimescaleDB are marked *"planned only if"* with the triggers from item 13;
    - an outbox replaces dual writes.
29. **§24 slide fixes:** add *"Slides 5–7: replace 34–47, 0.71, 0.94 and 0.62 with computed values; Slide 7 Demo 3: telemetry is 'can't be compared'."*

---

## Part 5 — (d) Top 10 judge questions

1. **"Pick a random quiet day. Does 'ran normally' say 'disagree'?"** Rarely, by construction. The threshold is the conformal 95% quantile of the machine's own daily max-z, which bounds the quiet-day false-alarm rate at 5% across all channels and hours together. The holdout rate is ⟨x%⟩ with its CI. Here it is live.
2. **"Is the alarm band computed or typed in?"** Computed. Open **Envelope**: it shows the quiet-day list with the reason each day qualified, med/MAD, T\* and n, and the `envelope_id` hash. Press **Verify replay** and you get the same hash. A grep finds no demo literals in the engine.
3. **"Four hours are missing and the spike was in them."** The result is "We can't tell (partial: 4 h missing)". A ∀ claim agrees only with 100% coverage. A property test proves that deleting readings never moves an outcome toward "agree".
4. **"What unit is the MS vibration channel?"** It is undocumented, so we never convert it. We compare it only with envelopes learned from the same series. That is why the gauge in bar is "can't be compared" with telemetry.
5. **"Your OCR re-read uses the same engine. How is that verification?"** It isn't. It is a consistency check that catches crop and segmentation errors. Implausible values go to review. The independent second reader (VLM) is P1.
6. **"Can I forge a decision as 'Senior Engineer'?"** No. Identity comes from an argon2-authenticated session, and a `reviewer` field returns 422. The decision stores the evidence hash you were shown and is part of the hash chain. Two reviewers racing get exactly one success and one 409.
7. **"Tamper with the PDF now."** Flip a byte, then **Show me the proof** shows a red "evidence changed". A SQL UPDATE aborts at the trigger. A hand edit with the trigger dropped fails chain verification. The version root matches the anchor pushed to our remote repository before this session.
8. **"You wrote both the faults and the rules. Isn't P/R circular?"** We limit it. Seeds are split into dev and holdout. The config hash was pushed before the holdout run (commit shown). An outsider authored at least 30% of the faults. We publish baselines, per-fault failures and ECE with a CI.
9. **"Same inputs on two laptops: identical?"** Replay from the stored artifacts is byte-identical: content IDs, JCS hashing, and a manifest that records the code SHA, lockfile and Tesseract version. Fresh OCR is reproducible inside the pinned image.
10. **"How does this serve a million readers?"** Versions are immutable, so readers are served from an edge cache keyed by tenant, case and version, with authorisation at the edge. The engine runs unchanged in workers. Kafka and Citus are planned only if write volume demands them, and we can show the trigger for each.

---

## Ruling summary

- I accept the debate's convergence on shape, SQLite, static Astro, PNG proofs, Tesseract, sessions, and the CDN scale story.
- I overrule or tighten it in six places:
  1. the envelope uses a **split-conformal** max-z threshold, not an empirical p95/p99 guess;
  2. the demo trains on **all days except the case window**, because before-only likely starves n;
  3. builds run in a **killable process**, not a `ProcessPoolExecutor`;
  4. a **409** is returned only when the item is already decided or its evidence changed;
  5. the anchor must be **pushed** to the remote;
  6. per-user **passwords** win over per-role PINs.
- Uploads stay on, hardened and limited to `ingestor`.
- Ed25519 is P1, and only with an off-box key.
