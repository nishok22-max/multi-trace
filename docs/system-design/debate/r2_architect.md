# TRACE — Round 2 (rebuttal): ARCHITECT

Ground rule for this round: an invariant must be true *by construction*, and that is all I am defending. The infrastructure I proposed in R1 was a means to that end. Wherever a cheaper mechanism gives the same guarantee within 36 h, I concede. Wherever one of the others weakens a guarantee, I keep my position.

---

## Verdicts per agenda item

### 1. Shape — KEEP, and ADOPT the sandboxed parser
All three of us converged on this shape: a pure `trace_core` behind Protocol ports, with `build_case(inputs, config, decisions, clock)`. I adopt Red Team's exception. All parsing of untrusted bytes (PyMuPDF, Pillow, Tesseract, openpyxl) runs in a **child process**. Each parse gets a 20 s timeout, a page cap of 50 and `Image.MAX_IMAGE_PIXELS` set as an error; memory is capped by the container cgroup. It is about 1 h of work: a `ProcessPoolExecutor(max_workers=2)` wrapped by the `Parser` adapter.

This also settles my strongest R1 objection to BackgroundTasks. CPU-bound OCR no longer runs on the event loop that serves the <1 s proof view. Isolation and latency are fixed by the same mechanism.

### 2. Execution — CONCEDE the Postgres queue; MODIFY toward Red Team
I drop Postgres + Procrastinate. Bare BackgroundTasks, though, is still not enough. The P0 floor is a **persisted `builds` row** with these properties:
- status and per-stage timings, as the Pragmatist proposed;
- a **heartbeat**, with a startup sweep that marks stale `running` rows as `failed_stale`;
- **one in-flight build per case**, enforced by a partial unique index on `(case_id) WHERE status IN ('queued','running')`;
- the idempotency `build_key`, which we all already share.

BackgroundTasks may then *dispatch* builds, because their state is durable. Decision re-runs stay synchronous: gate and trust only, on cached claims.

My argument against the Pragmatist: "no retries, the user clicks again" is acceptable. "A crashed build looks `running` forever" is not, because it blocks the per-case lock in front of a judge. The heartbeat costs about 20 lines.

### 3. Storage — CONCEDE SQLite; KEEP two structural rules
I accept one SQLite file in WAL mode, `BEFORE UPDATE/DELETE` triggers with `RAISE(ABORT)`, one process-wide writer lock and `UNIQUE(case_id, version)`. The Pragmatist's cost argument (no install, Windows) beats mine. With Postgres I could demo role revocation, but a trigger demos the same guarantee.

I do not concede two rules:
1. **Claims are written once and joined to versions through a `version_claims` table.** The Pragmatist's tables carry `version` on every row. That either duplicates every claim on each rebuild or turns `version` into a mutable field (my R1 weak spot W1).
2. **Intervals are stored as half-open `[start, end)` ISO-8601 UTC strings with a fixed width.** In that format, lexicographic order equals time order, so the overlap check is two indexed comparisons. That replaces `tstzrange`.

I accept the Pragmatist's per-machine Parquet split as a *derived source*. The condition is that its manifest records the parent CSV hash and the split code version. Re-check then verifies the ~200 KB partition hash, and the build verifies the chain from the partition back to the CSV once.

### 4. Integrity — CONCEDE the Merkle tree and P0 signing; KEEP the external anchor
- **P0:** each record gets `record_hash = sha256(JCS(body without wall-clock fields))`. Each version gets `manifest_hash = sha256(prev_manifest_hash ‖ sorted record hashes ‖ config_hash ‖ engine_sha ‖ source shas)`. That is Red Team's version-level chain.
- I drop the Merkle tree. Nobody needs a per-claim inclusion proof in the demo, and `sorted record hashes` already gives a deterministic root.
- **P1 (after h28):** Ed25519 signing of the manifest.

What I keep at P0 is a *non-DB anchor*. The current `manifest_hash` is shown in the UI and written to `anchors.txt`, which is committed to git at demo time. Without it, the chain sits in the same file an attacker edits. With it, Q7 ("tamper right now") is answered honestly, for zero extra code.

### 5. Determinism — KEEP; all three agree
I add from the others: dateparser with `RELATIVE_BASE` pinned to the observed time, and **never guess time**. An undated note gets `granularity=unknown`, so check 3 fails. `file_timestamp` is never used as the basis for valid time (T-12). The manifest also records the lockfile hash. The Pragmatist's "Verify replay" button is a better demo than my CI-only test, so I adopt it.

### 6. Extraction
- **pdf.js vs PNG: CONCEDE to the Pragmatist.** The PDF page is rendered server-side to PNG at a fixed DPI, cached by `(source_sha, page, dpi)` and hashed, then overlaid with the bbox. This has three benefits:
  1. it removes pdf.js worker configuration, the biggest frontend time sink;
  2. no attacker-controlled PDF ever executes in the browser, which closes part of T-22;
  3. one `RegionViewer` handles both images and PDFs, and its coordinate space is defined server-side (`coord_space = rendered_px@dpi`).

  What we lose is selectable text in the viewer. That is acceptable, because the cited quote is shown as text beside the image.
- **PyMuPDF vs pdfplumber: KEEP PyMuPDF, behind a `PdfReader` port.** Three reasons:
  1. `rawdict` gives char bboxes, fill colour, font size and render flags in one pass, which is exactly what T-06's hidden-text filter needs;
  2. it also renders the PNG, so with pdfplumber we would need a second library;
  3. it is 5–10× faster, which matters inside the <60 s budget.

  The AGPL obligation is met by publishing the repo, which a hackathon entry does anyway. For production, swap to pdfplumber + pypdfium2 behind the same port. I concede that Red Team's **T-06 filter is P0**: spans with fill ≈ background, size < 4 pt, an invisible render mode, or a position outside the crop box go to `held_for_review`.
- **OCR:** KEEP Tesseract. I concede the label: the re-read is a "**consistency check**", not verification (Q3). I adopt the physical-range plausibility check (T-09) and EXIF orientation handling (T-21), so OCR and display both use one derived, oriented image.
- **LLM verifier:** ADOPT Red Team's re-derivation rule. The rule parsers must reproduce the proposed value, unit and mention from the quote. That is stronger than my R1 "value appears inside quote".

### 7. Entity resolution and timeline — KEEP, plus ADOPT
I add a **non-string feature requirement** for auto-linking and a **serial-conflict hard veto** (T-10). I also add a case-level declared `plant_tz`: days are resolved locally as `[D 00:00, D+1 00:00)` and then converted, and naive dataset timestamps are interpreted in `plant_tz` and labelled as such (T-11). Review items carry `base_version`.

### 8. Frontend — CONCEDE static; one island per page
I drop Astro SSR. Red Team's argument wins: SSR means a second runtime, a second auth surface and CORS. With a static `dist/` served by FastAPI there is one origin, a `SameSite=Strict` cookie, and CSP hashes computed at build time. My CDN argument survives without SSR. The cacheable unit is the **immutable versioned JSON** (`/cases/{id}/versions/{v}/…`), not the HTML.

I also concede the Pragmatist's **one `client:only` island per page**, so nanostores go too. Separate React roots would need a cross-island store for no user-visible gain. The rest stays: TanStack Query with keys that include the version (T-29), ECharts for both the chart and the timeline, server-windowed tables, `dangerouslySetInnerHTML` banned by lint, and SSE as P1.

### 9. API — KEEP the core; CONCEDE two details
- **KEEP:** version-pinned read paths, `ETag = manifest_hash`, `If-Match`/`base_version` → 409, and RFC 9457.
- **CONCEDE cursor pagination.** A frozen version is immutable, so offset paging over it is just as stable. My reason for cursors disappears.
- **CONCEDE the `Idempotency-Key` header.** `build_key` already makes builds idempotent. For decisions, the 409 on an already-decided item covers it.
- **ADOPT Red Team's IDOR fix.** Routes become case-scoped (`/cases/{cid}/claims/{id}`, `/cases/{cid}/review/{rid}/decision`), with one central `resolve_case_and_authorize` dependency.

### 10. Auth — KEEP sessions; reject passwordless login
I agree with both on server-side sessions and identity taken from the session. On login I side with Red Team: **seeded users with argon2id passwords**. That is about 30 lines more than the Pragmatist's pick-a-name screen. The PRD's selling point is that a decision carries a name, and Q6 ("can I forge one?") must not be answered with "pick any name from the dropdown". Decisions record `user_id`, role, `base_version` and the evidence hash the reviewer was shown. Writes use `SameSite=Strict` plus a CSRF header. I concede the extra roles `ingestor` and `admin` as labels only.

### 11. Observability — CONCEDE OTel to P1
In P0: structlog JSON with no document text logged (Red Team's rule). Per-stage metrics are **stored on the build row and shown in the expert view** (the Pragmatist's idea). That is better than my Prometheus endpoint, because it proves NFR-7 on screen. Stage names match the future span names, so OTel adoption later is mechanical.

### 12. Testing — KEEP, plus ADOPT
- Golden tests with the manifest hash; Hypothesis invariants.
- `tsc` on the generated types as the contract test. Schemathesis moves to P1.
- One Playwright script.
- From Red Team: an authz matrix test, a 6-file hostile corpus (bomb PNG, HTML-as-PDF, traversal name, white-text PDF, EXIF-rotated photo, XSS text), **dev/holdout seed split with the config hash committed before holdout**, and the quiet-day false-alarm test (T-01).

### 13. Deployment — CONCEDE one container
SQLite plus static frontend means a single image: non-root, read-only root filesystem, one data volume, OCR binaries pinned. All three of us agree on the scale path: a CDN on frozen versions carries the 1M readers. Postgres and Temporal come when write volume or paid OCR/LLM retries demand them; Kafka and Citus are "planned only if".

---

## Red Team correctness threats T-01..T-05: exact fixes

I accept all five as P0. They are more dangerous than anything I raised in R1. T-02 and T-05 also overturn two of my own R1 statements: S-88 as "day max" against a daily-stat band, and "mm/s" in the ontology.

**T-01: multiple comparisons.** Replace the per-hour p5–p95 test with **one max-statistic per machine-day, calibrated for the whole family of tests**:
- For each quiet training day *d*, compute `T_d = max over channels c and hours h of |x_{c,h} − med_c| / (1.4826·MAD_c)`. `med_c` and `MAD_c` come from that machine's quiet hourly values.
- The normal threshold `T*` is the **95th percentile of `T_d`** over the quiet training days. By construction, at most about 5% of quiet days are flagged across all 4 channels × 24 hours together. No Bonferroni guesswork is needed.
- "Ran normally" is violated if `T_D > T*` **or** an error or failure event falls in the valid time.
- The displayed band per channel is `med_c ± T*·1.4826·MAD_c`. If that does not come out as 34–47, **the slide changes, not the engine** (T-30).
- Single-attribute phrases ("high vibration") use the same construction restricted to one channel.
- Test: across ≥200 holdout quiet machine-days, the disagree rate is ≤ 5%.

**T-02: statistic mismatch.** The envelope key becomes `(machine, channel, statistic, granularity, envelope_hash)`. Gate check 4 requires the claim's statistic and granularity to equal the envelope's. S-88 becomes a **day-granularity** claim with the statistic `T_D` ("day max robust-z 3.9 > T* 2.8"). The 14:00–15:00 peak of 64 is a child detail with its own window pointer. This also fixes my W5: C-17 (day) is compared against a day-level claim.

**T-03: gap hides the spike.** Each ontology phrase carries a **quantifier**:
- **∀ claims** ("ran normally", "no issues"):
  - "disagree" needs one observed violation;
  - "agree" needs **100% coverage** of the referenced channels over the valid time;
  - otherwise the outcome is **"We can't tell (partial: n h missing)"**.
- **∃ claims** ("vibration noticed"):
  - "agree" needs one observed violation;
  - "disagree" needs full coverage.
- The 80% `min_coverage` now only labels gaps; it never licenses "agree".
- Demo 1a stays "disagree", because the 14:00 violation was observed. Deleting the spike hours gives "can't tell".
- Property test: removing readings never moves an outcome toward "agree".

**T-04: envelope poisoning.** A day counts as quiet only if all of the following hold:
1. **log coverage is proven**: each event source declares a `coverage_period` in its manifest, and a missing or truncated log means the envelope build *refuses* with a problem response;
2. telemetry coverage is ≥ 23/24 hours on every channel;
3. no error, maintenance or failure event falls within ±3 days;
4. the day is **before** `case_start − 3d`.

If fewer than 10 such days exist, the engine falls back to the model-level envelope and labels it as such. Median/MAD and the quantile of `T_d` are robust: 5 planted hot days move `T*` only by about one order-statistic step. The envelope hash is stored on every comparison, and a move of more than 10% in `T*` between versions raises a review item.

**T-05: unsupported units.**
- The MS telemetry channels get a new `unit_status = "sensor_native"` (undocumented). Values are never converted, and the UI shows "sensor units (undocumented)", never "mm/s".
- Gate check 4 passes for a `sensor_native` claim **only against an envelope from the same `series_id`**.
- Gauge (bar) vs telemetry pressure gives **"can't be compared: telemetry unit undocumented"**.
- Demo 3 keeps its honest core: gauge 6.9 bar vs repair log 100 psi → ≈690 kPa → agree, and "7.2" with no unit → can't compare. "Telemetry in kPa" is deleted from the PRD (§9.2 Measurement, §9.6, §11 Demo 3, §21.2-1).
- Golden test: the gauge-vs-telemetry outcome is `cannot_compare/unknown_unit`, and the string "mm/s" appears in no UI or API output for MS channels.

---

## What I still hold against both

1. A `version_claims` membership table, not `version` stamped on each claim row.
2. An anchor outside the database (git-committed manifest hash) in P0.
3. Real passwords on seeded users, not pick-a-name.
4. A heartbeat and stale-job sweep on the build row.
5. Version-pinned, case-scoped URLs.

Each costs under 1 h, and each closes a hole a judge can open live.
