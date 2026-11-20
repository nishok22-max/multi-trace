# TRACE: Round 2 rebuttal (Pragmatist)

**Summary.** The Red Team's correctness threats (T-01 to T-05, T-30, T-31) are the most important content in Round 1. I concede all of them. If we skip them, the demo works on Machine 21 on 14 March and fails on the first other day a judge picks. That is a hard requirement ("no data ≠ normal", "never guess"), so it beats my hour budget.

I also concede T-23 (forged decisions). A judge can see it, and a judge can exploit it in 10 seconds.

I hold the line on the infrastructure disputes: Postgres plus a queue, Astro SSR, pdf.js, Merkle trees and OTel. They cost hours and visible demo risk, and none of them closes a hard requirement that my cheaper options leave open.

---

## Correctness threats: all conceded, about 9.5 h total

| ID | Concession | Hours |
|---|---|---|
| **T-01** multiple-comparison false alarms | "Ran normally" is violated only by a **daily statistic** outside its daily-statistic envelope at an upper band sized on held-out quiet days, or by any error event. Example: daily max > p99 of the quiet-day daily max. A single hour must breach the extreme band (median ± 4·MAD). Acceptance: disagree rate ≤ 5% on 200 held-out quiet machine-days, reported in the eval. Simple arithmetic shows the PRD's p5–p95 rule would cry wolf: with four channels at p95, a quiet day already breaches about 19% of the time. | 2.0 |
| **T-02** statistic mismatch | The envelope key is `(machine, channel, statistic, granularity)`, and gate check 4 requires both sides to match it. This also fixes the Architect's **W5**. S-88 becomes a *day-level* claim ("day max 64 outside the daily-max envelope"), with the 14:00–15:00 peak as a child detail. Check 3 is then well-defined on the headline demo. | 0.5 |
| **T-03** partial-data "agree" | Asymmetric rule. "Disagree" can come from partial data. "Agree" with a universal claim needs 100% coverage; otherwise the outcome is **"We can't tell (partial: 4 h missing)"**. Demo 1a therefore shows "disagree" if the spike is in the readings we have, or "can't tell" otherwise. It is never "agree". Plus a Hypothesis property: deleting readings never moves an outcome toward "agree". | 1.0 |
| **T-04** envelope poisoning and leakage | A quiet day counts only if the error, maintenance and failure logs cover its date and telemetry coverage is ≥ 95%. Envelopes are learned only from days before the case window. Each comparison stores the envelope hash and the quiet-day list. Two tests: with the error log dropped, the envelope build refuses; with planted hot days, the band moves less than the tolerance. | 1.5 |
| **T-05** invented units | MS telemetry is labelled `sensor_native (undocumented)` and is compared only with its own series envelope. Demo 3 changes: the gauge (6.9 bar) and the repair log (100 psi) agree with each other at about 690 kPa. Telemetry vs gauge gives "can't compare: unknown unit". The string "mm/s" appears nowhere. This makes the demo *more* honest and cheaper, because no fudge table is needed. | 0.5 + slide fix |
| **W10** confidence arithmetic | Generate C-17's confidence from the §10.8 formula and define `reliability_adj` explicitly. If the result is not 0.71, the slide changes. | 0.5 |
| **T-30** demo integrity | Every demo number is computed from the CSV and the authored files. A golden test pins the outputs. A grep in CI asserts that no 64, 34 or 47 literals appear in the engine. Authored sources carry a `synthetic` badge, and planted faults are listed in an injection manifest. **If the computed numbers differ from the deck, the deck changes.** I already ran the M21/14-Mar reality check at hour 0, so this hardens it. | 1.0 |
| **T-31** metric gaming | Seeds are split into dev and holdout. The config hash is committed before the holdout run, and that commit is printed in the eval report. The non-builder labeller authors at least 30% of the faults. The per-fault-type confusion matrix, failures included, is published. | 1.5 |

I also concede, at almost no cost: half-open `[start, end)` intervals in plant-local time converted to UTC (T-11, W6); an undated note gets `granularity=unknown` and is never assigned the file mtime (T-12); ε-tolerance flatlines unless a stop event explains them (T-13); near-duplicate independence detection is P0, and undeclared provenance counts as zero corroboration (T-15). These total about 1.5 h, counted inside the stage budgets.

---

## Agenda items: KEEP / CONCEDE / MODIFY

**1. Monolith, hexagonal core: KEEP.** All three of us agree. One small concession: a `Clock` port and an `ExtractionCache` port are added to my four (+0 h).

**2. Execution: MODIFY (adopt Red Team's version, not Architect's).**
- I keep SQLite, and I keep the decision re-run synchronous.
- I add Red Team's job-row discipline:
  - a heartbeat on each build;
  - a startup sweep that marks stale builds `failed_stale`;
  - a per-case lock;
  - `UNIQUE(case_id, version)`.
- The Architect's valid point is that CPU-bound OCR starves the event loop serving the <1 s proof view. The fix is to run builds in a **`ProcessPoolExecutor` with a timeout** instead of `BackgroundTasks`. That same subprocess is also my parse sandbox (item 6).
- I **reject Procrastinate on Postgres**. It needs a second container and a separate worker process to keep alive on stage. Its only advantages are durable retries and multi-worker scaling, and nothing in P0 needs either. My sweep plus idempotency key make "click Build again" safe. The Architect's own "change my mind" clause lists an SQLite adapter with the same invariants.
- Cost: +1 h.

**3. Storage: KEEP SQLite. CONCEDE the version-membership table (W1).**
- Claims are written once with content IDs. A `version_claims(case_id, version, claim_id)` table records which claims belong to which version, so no claim body carries `version`. That fixes a real append-only contradiction (+0.5 h).
- I reject `tstzrange`/GiST. A case has hundreds of claims, and an in-Python interval sweep is exact and testable with Hypothesis.
- Append-only rests on triggers + a repository with no update or delete methods + the hash chain. With Postgres, `REVOKE` would add one more layer, but on a laptop where we hold superuser it guards against nothing extra.

**4. Integrity: KEEP the hash chain. MODIFY with pointer-level hashes. Signing is moved earlier, not into P0.**
- I accept `crop_sha256`, `row_sha256` and per-partition telemetry hashes, with the file root equal to the hash over the partitions. These hashes keep re-checks under 1 s (+0.5 h).
- The **manifest** = hash(previous manifest, *sorted* record hashes, config hash, engine SHA). That is effectively a one-level Merkle commitment.
- A full Merkle tree with inclusion proofs answers "prove one claim to a third party without the log". No persona in the demo asks that question, and it adds about 3 h of UI and proof format. I reject it for P0 and put it in the §15 design.
- Ed25519 signing of the manifest moves to **h28, if the golden tests are green** (0.5 h). The root hash is shown in the UI and committed to git at demo time. That is the external anchor the Architect wants, at near-zero cost.

**5. Determinism: KEEP, and CONCEDE W3.**
- A decision is keyed to a stable **mention key `(source_sha, locator)`**, not to a claim ID. It is marked *stale* if that evidence hash changes.
- A cache miss during replay is an error, not a silent re-OCR.
- Pretty labels (C-17, S-88) are a separate deterministic alias column.
- Cost: +0.5 h.

**6. Extraction: KEEP PyMuPDF and Tesseract. MODIFY to add a light sandbox and hidden-text detection.**
- **PyMuPDF vs pdfplumber.** I keep PyMuPDF. It gives char bboxes, page rendering (which my proof viewer needs), and span colour, size and render mode in one call. Those span properties are exactly what **T-06 hidden-text detection** needs: flag a span when its colour ≈ the background, its size is < 4 pt, it sits outside the crop box, or its render mode is invisible. That costs 1 h with PyMuPDF and is harder with pdfplumber, which would also need a second library to render pages. I concede the AGPL line in the README ("hackathon only; production swaps to pypdfium2, Apache/BSD, behind the same `PdfReader` port").
- **Sandbox.** I concede a *cheap* sandbox: parsing and OCR run in the `ProcessPoolExecutor` child with a 20 s timeout. I also add `Image.MAX_IMAGE_PIXELS` set to raise an error, a streaming upload cap (25 MB for documents, 200 MB for telemetry), a magic-byte allowlist with no SVG, and blobs named only by hash (T-16 to T-19). The container runs as non-root. I reject cgroup tuning and fuzzing for P0, since T-20 is rated L/H and is P1 by the Red Team's own table. Cost +1.5 h.
- **EXIF (T-21): concede.** `ImageOps.exif_transpose` produces a derived display and OCR image with its own hash. This is a *real demo bug*: our one honest phone photo would draw misaligned boxes without it (+0.5 h).
- **LLM verifier (P1).** I accept the Architect's and Red Team's re-derivation gate: the rules re-parse value, unit and mention from the quote, and a non-unique short quote is rejected. It is still P1, but the verifier and its 50-mutation test are written in P0 against the fake proposer (+0.5 h).
- **OCR re-read.** It is labelled a "consistency check", per the Red Team's Q3.

**7. Entity resolution and timeline: CONCEDE all additions.** These are config weights and two rules, so +0.5 h:
- a named digit-transposition feature;
- at least one non-string feature required before an auto-link;
- a serial conflict is a hard veto;
- review items record `base_version`.

**8. Frontend: KEEP static output and PNG proof pages. CONCEDE CSP and the no-raw-HTML rule.**
- **Static vs SSR.** The Architect's arguments for SSR are auth-before-render, less JS, and cacheable pages. None of them changes the outcome:
  - Auth is enforced at the API on every call; rendering a shell for an unauthorised user leaks nothing.
  - The case workspace is interactive almost end to end anyway.
  - The CDN story is *better* with static: an immutable shell plus immutable `/versions/{v}` JSON.
  - SSR adds a Node service to keep alive on stage, a second origin, and CORS.
  - The Red Team independently picks static, for security reasons.
- **PNG vs pdf.js.** I keep PNG, and the Red Team's own threat model strengthens the case. pdf.js brings PDF JavaScript, the annotation layer, worker configuration, and a `worker-src blob:` hole in the CSP. A server-rendered PNG with a bbox overlay has **zero PDF parsing in the browser**. We lose text selection, which no requirement asks for. Hours saved: about 3.
- **Concede:** a strict CSP and lint banning `dangerouslySetInnerHTML`. Text highlights come from slicing into React text nodes (T-22). +0.5 h.
- **Reject:** TanStack Table/Virtual (we use a server window of ±15–50 rows) and nanostores (one island per page).

**9. API: MODIFY.**
- I adopt versioned read paths `/cases/{id}/versions/{v}/…` (with "latest" as a redirect) and `ETag = manifest hash`.
- Decisions carry `base_version`. A stale or already-decided item returns **409** problem+json, and overriding a decision requires the `senior_reviewer` role (T-24).
- One central dependency resolves claim → case for every case-less route (T-25 IDOR).
- Offset pagination stays: frozen sets make offsets stable, so cursors buy nothing.
- Cost: +1.5 h.

**10. Auth: CONCEDE (T-23).** Pick-a-name loses to a judge typing `{"reviewer":"Senior Engineer"}`. The new design:
- a login page with seeded users and argon2id hashes (`argon2-cffi`);
- an opaque session ID stored in an SQLite sessions table;
- an `HttpOnly; SameSite=Strict` cookie, plus a required `X-TRACE-CSRF` header on writes (T-26);
- **the reviewer is taken from the session, and the body field is ignored**;
- the decision stores user ID, role, `base_version`, and the hash of the evidence shown; reason ≥ 15 characters;
- roles: viewer, reviewer, senior_reviewer, evaluator;
- a small authz matrix test.

Total 2.5 h, versus my original 1 h. Still no JWT, and the three of us agree on that.

**11. Observability: KEEP, no OTel in P0.**
- Per-stage timings and counters are stored on the build row and shown in the expert view. That covers rejected quotes, held items, gaps, re-check mismatches, stale jobs and 409s.
- This proves NFR-7 *on screen*. A Jaeger container proves it to nobody in the room.
- I concede the Red Team's "never log document text or quotes" rule (0 h).
- OTel stays a P1 with span names that already match the stage names.

**12. Testing: MODIFY.** I add:
- a 6-file hostile corpus (bomb, polyglot, traversal name, hidden text, EXIF-6, XSS text);
- a Playwright tamper test (flip a byte → red "evidence changed");
- the Hypothesis properties above (symmetry, gap monotonicity).

I reject Schemathesis, because generated types plus `tsc` cover the contract. Cost: +2 h.

**13. Deployment: KEEP one image (non-root, pinned base, hashed lockfile).** All three of us now agree that the scale story is a CDN of immutable versions, and that Kafka and Citus are not justified.

---

## Updated hour ledger (≈111 of ~110 available build hours; slack absorbs the overage)

| Area | R1 | R2 | Change |
|---|---|---|---|
| Ingestion text/PDF/table (+ hidden text) | 10 | 11 | T-06 |
| OCR + re-read (+ EXIF) | 4 | 4.5 | T-21 |
| Telemetry, envelopes, gaps (+ T-01..04) | 8 | 13 | correctness floor |
| Units, ER, timeline (+ T-05, W10, ER rules) | 8 | 9.5 | |
| Gate + trust + independence | 8 | 8 | |
| Store, chain, snapshots, replay (+ membership, mention keys, pointer hashes) | 6 | 7.5 | W1, W3 |
| API, types, errors (+ 409, IDOR) | 4 | 5.5 | T-24/25 |
| Auth | 1 | 2.5 | T-23 conceded |
| Security floor (process sandbox, upload caps, magic bytes, CSP) | 0 | 3 | T-16..19, T-22 |
| Frontend | 26 | 21 | expert view = plain tables; timeline polish cut |
| Eval track (+ T-30/31, holdout) | 18 | 17 | baseline uses TF-IDF retrieval, no hosted LLM |
| Tests (extra), deploy, Playwright, rehearsal | 7 | 8.5 | |
| Buffer | 10 | 0 | absorbed |

**Stretch (order, only if the golden tests are green at h28):** Ed25519 signing (0.5) → SSE (1) → OCR+VLM second reader → LLM proposer.

**Bottom line.** I pay about 15 h for correctness and security floors that a judge can probe. I fund them by cutting buffer and frontend polish, not by dropping a hard requirement. I don't pay the roughly 10 h, plus the stage-failure risk, that Postgres + Procrastinate, Astro SSR, pdf.js, Merkle inclusion proofs and OTel would cost, because none of them closes a hole that my options leave open.
