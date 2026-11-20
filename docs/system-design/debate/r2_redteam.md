# TRACE Design Debate — Round 2 (Rebuttal) — RED TEAM

Read: `r1_architect.md`, `r1_pragmatist.md`. Threat IDs refer to `r1_redteam.md`.

**Headline.** Both positions do well on *mechanism*: triggers, the hash chain, session identity, content-addressed IDs and replay. Both are almost silent on the correctness lies that a judge exposes by picking a second machine-day (T-01 to T-05). Neither mentions upload hardening or CSP. The Architect also brings in one new information-disclosure bug, and the Pragmatist brings in one new concurrency bug.

---

## 1. Attacks on the Pragmatist

**P-a. Pick-a-name login is attribution theatre once the laptop is on venue Wi-Fi.**
- "Reviewer from the session" only helps if getting a session is not one click on someone else's name. FastAPI on `0.0.0.0` lets anyone on the LAN sign as "Senior".
- Two more details: Starlette's `SessionMiddleware` needs a non-default `secret_key` from the environment, and the PRD's audit claim ("name and reason saved") becomes false if the name is self-chosen by an unauthenticated visitor.
- *Minimum fix (≤ 30 min):* bind to `127.0.0.1` for the stage demo. If judges click from their own devices, require a per-role demo PIN (hashed in `users.yaml`). The login screen already says "demo identities"; keep that.

**P-b. BackgroundTasks: no half-written version, but a job that never finishes.**
- Writing the version row last does prevent half-versions. But a crash or `--reload` leaves `builds.status='running'` forever, and the UI keeps polling every second.
- If the task is declared `async def` and calls Tesseract or pandas synchronously, it blocks the event loop. The < 1 s proof view (NFR-7) then fails exactly while a build runs.
- *Fix (15 min):* a stale-job sweep at startup, build tasks declared as plain `def` (so Starlette runs them in its threadpool), and one in-flight build per case.

**P-c. A sync decision with no `base_version` loses updates.**
- The SQLite writer lock *serialises* two reviewers' decisions; it does not *reject* the second. Reviewer 2 silently supersedes Reviewer 1's pick (M-12 over M-21) without ever seeing it.
- That is T-24, and it is a Demo 2 failure if two judges click at once.
- *Fix (30 min):* `base_version` on the decision, and **409 problem+json** if the item is already decided.

**P-d. Rendering the PDF page to PNG: better for security, and a chance to catch hidden text.**
- I concede that dropping pdf.js removes a whole attack surface (PDF JavaScript, the worker, CSP `worker-src` issues).
- Fidelity gap: `char_start/char_end` index the **text layer**, while the PNG shows the **rendered page**. They are different things. White-on-white or 1 pt text (T-06) is in the text layer, produces a claim, and the "proof" box on the PNG is empty.
- *Fix (≈ 1 h):* use the PNG. Crop the bbox from the rendered page and require pixel variance above a threshold. If it is near-blank, the claim goes to `held_for_review` with the reason "text not visible". The Pragmatist's own design gives the cheapest T-06 check available.

**P-e. Frozen JSON snapshots are an unprotected copy.**
- `snapshots/{case}/{v}.json` is not covered by the triggers, and GETs serve it from an LRU cache. Edit the file and the UI lies while the DB stays clean.
- *Fix (15 min):* store `sha256(snapshot)` on the version row, and verify it on first load and on cache fill.

**P-f. Tuning entity-resolution weights "so 0.71 vs 0.22 falls out" is fitting to the slide.**
- That is T-31 in miniature.
- Tune on dev alias seeds. Then **accept whatever the holdout gives and fix the slide.** Never the reverse.

**P-g. No OpenTelemetry: conceded.** It does not affect security or correctness. Per-stage metrics on the build row are what judges see. Keep my one rule: never log document text or quotes.

---

## 2. Attacks on the Architect

**A-a. "Version pages served `public, max-age=31536000, immutable`" plus server-side auth checks = a cross-user leak.**
- Any shared cache (a CDN, a corporate proxy, or the Astro node behind a cache) stores an authenticated page as `public` and serves it to the next person who asks.
- Immutable does not mean public. For authenticated content it must be `private, immutable`, or the CDN key must include the tenant and auth. This is a new **I**nformation-disclosure hole the Architect's design creates, with no counterpart in mine.

**A-b. Astro SSR doubles the auth surface.**
- Session checks have to happen in Astro middleware *and* in FastAPI.
- The Node server forwards cookies to the API server-side, which is a classic place to get bugs: cookie forwarding to the wrong host, a header-trusted `X-User`, or `set:html` on document text.
- It is also a second long-running process (Node) that can die mid-demo.
- The only benefit claimed (auth before render, less JS) is worth nothing for a 4-page single-tenant demo. Static Astro + same-origin `fetch` keeps exactly **one** policy point.

**A-c. A Postgres queue + worker + Node web + Jaeger is 5 containers on Windows Docker Desktop in 36 h.**
- Each is a demo-failure point. `REVOKE UPDATE` only beats SQLite triggers if the app connects as a non-owner role, and in a hackathon Compose file the app is almost always the owner.
- The SQLite trigger demo ("run an UPDATE live → ABORT") is equally convincing on stage. I concede Postgres is not needed for any threat in P0.

**A-d. An Ed25519 key in an env var on the same box signs nothing an attacker can't re-sign.**
- The attacker who can rewrite the DB and the blobs can read `.env` and re-sign.
- A signature only adds value with: (1) the **public key committed to the repo before the event**, (2) the private key **not** on the serving box (signing happens at snapshot-publish time from a team member's machine), and (3) a key ID in the manifest.
- Otherwise it is the same theatre the Architect accuses an in-DB chain of being. A cheaper *real* anchor: show the root hash in the UI and `git commit` the demo version roots before going on stage.
- Merkle inclusion proofs: nobody verifies them in a demo. They belong in a P2 design note.

**A-e. PyMuPDF AGPL is a licence issue, not a security issue.**
- It is a non-issue for a hackathon that discloses it. Both sides pick PyMuPDF, so I concede.
- The real risk is a C parser fed untrusted bytes (T-20). That only matters if judges can upload files (see floor item S6).

**A-f. Credit where due.** The Architect independently found:
- **W5**, a granularity/statistic mismatch (my T-02);
- **W7**, envelope leakage (T-04c);
- **W3**, decisions orphaned by claim-ID changes, which I missed and now adopt;
- **W10**, confidence numbers that don't match the §10.8 formula, which I missed and now adopt;
- a **gap-monotonicity** property test.

  Implemented honestly, that last test catches T-03 (deleting the spike hours must never move an outcome from "disagree" to "agree"). The Pragmatist's version ("gap-flagged side → never agree") does **not** catch it, because 20/24 coverage is not gap-flagged.

---

## 3. Which of my threats stay OPEN under each proposal

✓ = closed, ~ = partial, ✗ = open. P1/P2 items are listed only where it matters.

| Threat | Architect | Pragmatist |
|---|---|---|
| T-01 multiple-comparison false alarms on "ran normally" | ✗ | ✗ |
| T-02 statistic/granularity in the gate key | ~ (S-88 made day-level; the statistic itself is not keyed) | ~ (granularity rule only) |
| T-03 partial-coverage "agree" | ~ (monotonicity test, no mechanism) | ✗ |
| T-04 envelope poisoning (log coverage / leakage) | ~ (leakage closed, log coverage open) | ✗ |
| T-05 undocumented sensor units | ✗ | ✗ |
| T-06 invisible PDF text | ✗ | ✗ (but the PNG enables a cheap fix) |
| T-07 LLM attaches a wrong value (P1) | ✓ (value+unit inside the quote) | ~ (exact find only) |
| T-09 OCR plausibility | ~ | ~ |
| T-10 over-merge on string similarity alone | ~ (transposition feature) | ✗ |
| T-11 plant-local day boundaries | ~ (half-open UTC only) | ~ |
| T-12 guessed time when no document date | ✗ | ✗ |
| T-13 flatline vs a legitimately stopped machine | ✗ | ✗ |
| T-15 undeclared derived source | ✓ | ~ |
| T-16 to T-19 bombs, size limits, MIME spoofing, path traversal | ✗ | ✗ (content-addressed paths ✓ for T-19) |
| T-21 EXIF orientation / GPS | ✗ | ✗ |
| T-22 XSS / CSP | ~ (pdf.js, no CSP) | ~ (no pdf.js, no CSP) |
| T-23 forged decision | ✓ | ~ (see P-a) |
| T-24 racing decisions | ✓ | ✗ |
| T-26 CSRF | ✓ | ✗ |
| T-27 tampering | ✓ | ~ (snapshot copy, P-e) |
| T-28 stuck jobs | ✓ | ~ |
| T-29 stale caches | ~ (new public-cache leak, A-a) | ✓ |
| T-30 demo numbers live, not typed in | ~ (asserts PRD numbers as goldens) | ✓ (h0 data check) |
| T-31 metric gaming | ✓ (holdout seeds) | ✗ (P-f) |
| T-33 LLM / network outage | ~ | ✓ (zero network calls) |
| T-38 clock | ✓ | ✓ |

**Open in both: T-01, T-03 (mechanism), T-04a, T-05, T-06, T-12, T-13, T-16 to T-18, T-21, T-22 (CSP).** These form the floor below.

---

## 4. Non-negotiable P0 floor (incremental hours beyond what either ledger already budgets)

**Correctness, about 5.5 h.** This is the floor I will not trade.

| # | Item | Closes | h |
|---|---|---|---|
| C1 | Hourly violation = extreme band; daily statistic vs a daily-statistic envelope; test: ≤ 5% "disagree" on 200 held-out quiet machine-days | T-01 | 1.5 |
| C2 | Envelope key = (machine, channel, statistic, granularity); gate check 4 compares the key | T-02, W5 | 0.5 |
| C3 | Asymmetric coverage: a universal "agree" needs 100% coverage, otherwise "We can't tell (partial)"; plus the Architect's monotonicity property test | T-03 | 1.0 |
| C4 | Quiet day requires error, maintenance and failure log coverage; exclude the case window ± N days | T-04 | 0.5 |
| C5 | Telemetry unit = `sensor_native (undocumented)`; a gauge-vs-telemetry comparison returns "can't compare" | T-05 | 0.25 |
| C6 | Hidden-text check via pixel variance of the bbox crop on the rendered PNG | T-06 | 1.0 |
| C7 | `plant_tz` on the case; no document date → `granularity=unknown`, never the file mtime | T-11, T-12 | 0.5 |
| C8 | Flatline uses an ε tolerance and is suppressed by a stop or maintenance event | T-13 | 0.25 |
| — | *Process, 0 code hours:* demo numbers computed live, slide fixed to match; config hash committed before the holdout run; W10 confidence formula reconciled | T-30, T-31 | (0.5) |

**Security, about 3 h.**

| # | Item | Closes | h |
|---|---|---|---|
| S1 | Identity from session only; bind to `127.0.0.1` for the stage, or use per-role PINs on the LAN; non-default session secret | T-23 | 0.5 |
| S2 | `SameSite=Strict` + a custom CSRF header on writes | T-26 | 0.25 |
| S3 | `base_version` → 409 on decisions | T-24 | 0.5 |
| S4 | Stale-job sweep at startup, plain `def` build tasks, one in-flight build per case | T-28 | 0.25 |
| S5 | Snapshot hash verified on load; root hash shown in the UI and committed to git pre-demo | T-27 | 0.25 |
| S6 | Upload hardening: size cap, magic-byte allowlist, no SVG, `MAX_IMAGE_PIXELS`, `exif_transpose` at ingest. **Or** turn off the upload endpoint in demo mode (0.25 h) and move the hardening to P1. `exif_transpose` stays either way, because the one real phone photo carries EXIF. | T-16 to T-18, T-21 | 1.0 |
| S7 | `dangerouslySetInnerHTML` lint ban + one CSP header (`default-src 'self'; object-src 'none'; frame-ancestors 'none'`), checked in report-only mode once | T-22 | 0.5 |

**Total ≈ 8.5 h**, or about 7.5 h with S6 reduced to the demo-mode switch. That comes out of the Pragmatist's ~10 h buffer. Much of C1–C4 is a *re-specification* of gate and envelope work that is already budgeted, not new modules.

**Safe to defer to P1/P2:**
- P1: the subprocess parse sandbox (if uploads are off), Ed25519 signing (only with a pre-committed public key), OpenTelemetry, SBOM, pip hash pinning, `pip-audit`, rate limits on `/eval/run`, duplicate-timestamp detection (T-14), LLM hardening (P1 together with the LLM).
- P2: Merkle inclusion proofs, IDOR and tenant isolation beyond a central case-scope dependency (single tenant in the demo), crypto-shredding, cosign-signed images.

---

## 5. Agenda verdicts

| # | Item | Verdict | Final Red-team position |
|---|---|---|---|
| 1 | Shape | **KEEP** | Hexagonal monolith (all three agree). **CONCEDE** the subprocess sandbox to P1 if uploads are off in the demo. |
| 2 | Pipeline | **CONCEDE → MODIFY** | Pragmatist's BackgroundTasks, no queue, no Postgres queue. Add S4. Keep the Architect's 1.5 s fallback idea only as a note. |
| 3 | Storage | **KEEP** | Single SQLite (WAL) + triggers + Parquet per machine, with the per-machine files registered as derived sources (Pragmatist; this also fixes proof-view re-hashing). Add S5 snapshot hashing. Reject Postgres for P0. |
| 4 | Integrity | **MODIFY** | SHA-256 + a linear chain in P0; root hash shown in the UI and git-committed. **CONCEDE** Merkle (P2). Ed25519 is P1 *only* with an externally held key and a pre-committed public key. |
| 5 | Determinism | **KEEP** | Union of both: content IDs, clock injection, the dateparser `RELATIVE_BASE`, an OCR/LLM artifact cache, and "a cache miss under replay is an error" (Architect). |
| 6 | Extraction | **CONCEDE → MODIFY** | PyMuPDF (AGPL disclosed) + PNG rendering. Verifier = exact match + uniqueness + **value and unit inside the quote** (Architect); I drop full rule re-derivation as disproportionate. Add C6. Label the re-read a "consistency check". |
| 7 | ER / timeline / review | **MODIFY** | Half-open intervals + `plant_tz` (C7). Decisions keyed to a stable mention key (Architect W3, adopted). Tune weights on dev seeds only (P-f). |
| 8 | Frontend | **KEEP static, CONCEDE details** | Reject Astro SSR (A-a, A-b). Adopt the Pragmatist's one large `client:only` island, no pdf.js, and ECharts. Add S7. |
| 9 | API | **KEEP / CONCEDE** | Keep 409 / `base_version` and RFC 9457. Concede offset pagination. ETag = root hash. |
| 10 | Auth | **CONCEDE → MODIFY** | Drop argon2 passwords. Pick-a-name is acceptable **on localhost**, with a PIN if networked. Identity from session + a CSRF header (S1, S2). |
| 11 | Observability | **CONCEDE** | No OpenTelemetry in P0. Per-stage metrics on the build row. Never log document text. |
| 12 | Testing | **KEEP (narrowed)** | Golden + Hypothesis tests, including the Architect's gap monotonicity and my quiet-day false-alarm test (C1). Concede Schemathesis and the full authz matrix to P1; one role-check test stays. |
| 13 | Deployment | **CONCEDE** | One container + a native fallback (Pragmatist). The lockfile is committed. SBOM, digest-pinned base image and cosign go to P1/P2. Shared view on §15: the CDN of frozen versions is the real scale story, and Kafka and Citus are "not yet earned". |
