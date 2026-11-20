# QA-1 Review: Technician's Implementation Plan (correctness & architecture)

| Field | Value |
|---|---|
| Reviewer | QA-1 (correctness & architecture lead) |
| Plan under review | `docs/reviews/technician_plan.md` (2026-11-20) |
| Sources of truth | `TRACE_PRD.md` v1.2, `system-design/SYSTEM_DESIGN.md`, `DECISIONS.md`, `HARDENING.md`, `debate/r3_judge.md` |
| Binding decisions | Single-plant pilot; pypdfium2; Docker plus native fallback; Groq opt-in, zero network in MVP |

## 1. Verdict: **PASS-WITH-FIXES** (on condition)

The plan is strong. It carries almost every judge verdict into concrete tasks with named tests. The hexagonal layout and import-linter contracts are right, and so are fakes-before-adapters, contracts frozen at h8, the CRLF and `tzdata` handling, and the walking skeleton at h10. The pypdfium2 section is honest about its gaps.

It is **not executable as written**, though, because of three BLOCKERs:

1. **The holdout is used during development.** The holdout false-alarm test is an M3 exit gate at h24, four hours before the one-shot holdout run.
2. **The false-alarm rate is measured on its own training days.** The quiet-day rate would be computed on the same days that produced T\*, so it is ≤ 5% by construction.
3. **Partly hidden text gets through.** The hidden-text guard tests one union bbox, so a span that is only partly invisible still passes.

All three can be fixed in the plan text and add less than 1.5 h. None needs a change of architecture. The verdict becomes a plain PASS once the BLOCKERs are fixed and the MAJORs are fixed or explicitly accepted by the lead.

**Counts:** 3 BLOCKER, 23 MAJOR, 22 MINOR (48 findings).

---

## 2. Findings

Severity:
- **BLOCKER:** invalidates a P0 promise or a headline metric; fix before h0.
- **MAJOR:** a likely defect, a coverage hole or a schedule break; fix before the milestone it touches.
- **MINOR:** clarity, robustness or a pilot-phase gap.

### 2.1 Correctness floor and evaluation validity

| ID | Sev | Plan § | Issue | Concrete fix |
|---|---|---|---|---|
| Q1-01 | **BLOCKER** | D.3 M3 (B-03), D.3 M5 (D-09) | `test_quiet_day_false_alarm_rate_holdout` is a B-03 exit test due at h24, using the D-08 harness that is scheduled in M5. Under T-31 the holdout runs **once**, at about h28, after the config is pushed. Running it while B tunes envelopes is tuning on the holdout. That voids the headline "≤ 5% false alarm" claim. | Split the test in two. **`test_quiet_day_false_alarm_rate_dev`** runs on dev machines in M3 and pre-commit. **`…_holdout`** is marked `@pytest.mark.holdout`, excluded from `make test` and `check`, and run only by `make eval-holdout`. Move the Wilson harness from D-08 into B-03 (or D-08 part 1 before h20). |
| Q1-02 | **BLOCKER** | D.3 M3/M5, PRD §10.3 | Under `all_except_case_window`, Q holds every quiet day of the year. If the "≥ 200 holdout quiet machine-days" are drawn from Q, each test day helped set its own T\*. The measured rate is then in-sample and is ≤ 5% by construction, not a test of exchangeability. Nothing in the plan says evaluation days are held out of calibration. | Define the protocol in D-08 and D-09. For each evaluated quiet day *d*, recompute T\* with *d* ±3 days removed from Q (leave-one-block-out), **or** split each machine's quiet days into time-blocked calibration and test folds. Use holdout **machines** (disjoint from dev machines) for the reported number. Add `test_false_alarm_eval_day_not_in_calibration_set`. |
| Q1-03 | MAJOR | A.1-4, B.2 `golden-bless` | Goldens bless "the computed values after the first green build". An off-by-one in `k=⌈0.95(n+1)⌉`, a MAD without the 1.4826 factor, or a wrong pooling branch gets pinned as truth. No independent oracle exists. | Before the first bless, B writes `tests/unit/test_conformal_oracle.py` with hand-computed fixtures: n = 19 gives k = 19 (the max); n = 30 gives k = 30; n = 18 gives the pooled branch; n = 9 gives model-level med/MAD; MAD = 0 gives a degenerate channel; the p-value formula. D reviews the arithmetic. `golden-bless` refuses unless the oracle tests pass. |
| Q1-04 | MAJOR | C.3 `candidate_pairs`, A.2 | Pairs come from a "per-(entity, attribute) interval sweep". C-17 (`operating_state`) must also be paired with the error rows (`error_event`), because the ∀ scope includes "no error events" (judge 14d; PRD §9.5 `cmp-err3`/`cmp-err4`). A same-attribute sweep never produces those pairs. The Demo 0 card would then lose its supporting context, and a ∀ claim with no telemetry violation but an error event would wrongly **agree**. | Make `candidate_pairs` sweep over **ontology attribute groups**: each phrase's quantifier scope lists the attributes it covers (`operating_state` → {`operating_state`, `error_event`, `failure_event`, `maintenance_action`}). Add `test_forall_normal_vs_error_row_disagrees` and `test_forall_agree_requires_log_coverage_of_window`. Log coverage of the *case window* is a ∀-agree condition that the plan never mentions. |
| Q1-05 | MAJOR | C.3 stage order, FR-TRUST-3 | `apply_holds` runs before `candidate_pairs`, but `score` runs **after** the gate. The τ_review hold ("confidence below τ_review → held") therefore has no confidence to read when holds are applied. It is either silently skipped or would need a second gate pass. | Add `score_pre(claims, cfg)`, which computes components with corroboration = 0, before `apply_holds`. The τ_review hold uses that value. Post-gate corroboration may raise confidence but never creates or lifts a hold. Document this and add `test_low_confidence_claim_never_pairs`. |
| Q1-06 | MAJOR | C.1 `Interval` | `Interval.start/end: UtcStr` are required, with `start < end`. A claim with **no document date** (T-12, `granularity=unknown`) cannot be built without inventing an interval, which is exactly the guessing that T-12 forbids. | Make `Temporal.valid_time: Interval \| UnknownTime`, where `UnknownTime(granularity="unknown", reason)` has no bounds. Check 3 fails with "time unknown" whenever valid time is `UnknownTime`. Add a validator: `granularity == "unknown"` ⇔ no bounds. |
| Q1-07 | MAJOR | B-03, C.1 `Envelope`, C.3 `learn_envelopes` | Five gaps in the envelope design. (a) `Envelope` has no `series_id`, but check 4 must match `(statistic, granularity, series_id)` (judge 14c). (b) Pooled envelopes need defined check-4 semantics and must hash the pool members' partitions. (c) Single-channel phrases need their own scope envelope (C = {vibration}) and nothing generates it. (d) `QuietDay` does not store `T_d`, so the conformal p-value for S-88 confidence cannot be recomputed from evidence. (e) A.2 says only "case window ±3 d" is loaded, but learning needs the full history of every machine in the pool. | Add `series_id`, `pool_members: list[machine]` (included in `envelope_id`) and `QuietDay.t_d`. Have `learn_envelopes` take the ontology and emit one envelope per distinct phrase scope. State that envelope learning reads the full-year partitions; only the proof path is window-limited. |
| Q1-08 | MAJOR | A.5 lint, B-02 | NFR-6 is "backed by a lint rule", but the lint bans only `numpy.mean/average` and `statistics.mean`. The real risks are pandas: `pivot_table` (default `aggfunc="mean"`), `groupby().mean()` and `resample().mean()` in `trace_adapters/telemetry_split.py`, which is outside the ban's scope. | Add an AST check (`tools/check_no_mean.py` in pre-commit) that flags `.mean(`, `pivot_table(` without an explicit non-mean `aggfunc`, and `.resample(` across `trace_core` and `trace_adapters`, with an allowlist. Add `test_split_preserves_duplicate_rows` at the **adapter** level, not only in `read_sensor`. |
| Q1-09 | MAJOR | D.3 M5 (B-11) | The properties that guard the floor (gate totality, symmetry, gap monotonicity, never-average) are scheduled for M5, h16–h30. B sleeps h25–h29.5, so they are written late, possibly after the holdout run at h28. | Move the four floor properties into B-04 and B-08 (due h20). Leave unit round-trip, overlap commutativity and chain detection in B-11. |
| Q1-10 | MAJOR | D.3 M5 (D-09), A.1 | The `eval-holdout` gate checks only that `config_hash` is pushed. Engine code (rules, resolver weights in code, the gate) can change after the holdout run, and nothing records it. | `eval-holdout` must also require a clean tree, with `engine_sha` and `lockfile_hash` contained in a remote branch. The report prints all three. Any engine change after the run marks the report "superseded; second look disclosed". |
| Q1-11 | MAJOR | D.1, D.3 (no task) | D6 and FR-LOOP-2 need a **hand-labelled set of 150–300 items** (entity, value, time, outcome) for accuracy per confidence bin, ECE and Brier. No task or hours cover the labelling, and D-09 is 1.5 h. | Add D-12 "Label 150 items" (≈ 2.5 h) taken from D's 4 h reserve, scheduled h16–h21 before D sleeps. Alternatively, state that the MVP metrics use injected-fault ground truth only, and disclose that. |

### 2.2 Architecture, determinism and integrity

| ID | Sev | Plan § | Issue | Concrete fix |
|---|---|---|---|---|
| Q1-12 | MAJOR | C.2 ports, C.3 `read_sensor` | There is **no telemetry port**. `read_sensor(partitions, …)` and "reads use `pyarrow.dataset`" imply Parquet file I/O inside `trace_core/read/sensor.py`, which breaks hexagonal purity. TID251 bans `open`, but not `pyarrow.parquet` or `pyarrow.dataset`. | Add the port `TelemetryReader.read(series_id, start, end) -> pa.Table` and the partition hash to `EnginePorts`, with `FakeTelemetryReader`. Add import-linter "forbidden external modules" for `trace_core`: `sqlite3, pyarrow.dataset, pyarrow.parquet, pypdfium2, pytesseract, openai, httpx, socket, subprocess`. |
| Q1-13 | MAJOR | C.3 `snapshot(..., clock)`, D-04 | The snapshot takes a clock, and PRD §9.1 has `created_at` in the case state. If `snapshot_sha256` covers the wall-clock field, **Verify replay** (FR-UI-8) can never match `manifest_hash`. | Compute `snapshot_sha256` over JCS(snapshot − wall-clock fields), as for records. Alternatively, replay injects `FixedClock(version.created_at)`. Add `test_replay_identical_with_different_clock`. |
| Q1-14 | MAJOR | A.1-6, B.2 `seed` | Seeds are claimed to be "hash-stable", but `make seed` regenerates them per laptop. ReportLab embeds a creation date and a random document ID unless `invariant=1`. Pillow gauge text depends on which system fonts exist on Windows vs. Linux. Source shas would then differ by laptop: goldens blessed on one laptop fail on the other three in pre-commit, and D-11's "equal manifests" fails. | Generate once inside the image, **commit the bytes** and `seed/SHA256SUMS`, and make `make seed` verify only. If regeneration stays, use `rl_config.invariant=1` and a vendored TTF font. |
| Q1-15 | MAJOR | A.3, A.7, D.2 | PDF extraction is **not** in the extraction cache. `bbox_pt` floats and `font_sizes` from the Windows and manylinux PDFium builds may differ in low bits. Because the pointer is inside `claim_id`, any difference changes IDs and manifests across native and image. Separately, `CaseVersion.tesseract_version` records the **local** binary, so a native replay manifest ≠ the image manifest even when it is cache-driven. | Either record `PageText` artifacts in the extraction cache (replay from the cache, like OCR), or quantise boxes to 0.01 pt and exclude `bbox_*` from `claim_id`. In replay mode, take `tesseract_version` from the cache artifact's metadata. Add `CacheKey` fields for the binary version and the `traineddata` sha. Run `replay-verify` natively on Windows as part of D-11. |
| Q1-16 | MAJOR | C.1 `ReviewItem`, B-06, W3 | Decisions are keyed by mention key, but `review_id` derivation is unspecified. The route is `/review/{rid}/decision`. If `rid` hashes `claim_ids`, which change with the extractor version, decisions are orphaned and the review item reopens with a new ID. | Set `review_id = h(type, mention_key)` (or `h(type, sorted locator keys)` for multi-claim items). Specify the ID derivation for every record type (comparison, conflict, review, event, decision) in `ids.py`. Add `test_review_id_stable_across_extractor_version`. |
| Q1-17 | MINOR | A.3, `canonical.py` | The fixed 6-dp rule is not specified for `-0.0`, NaN/Inf, rounding mode, or floats nested in `features: dict[str, float]`. | Use `Decimal(repr(x)).quantize(…, ROUND_HALF_EVEN)`, normalise `-0.0` to `0`, and reject NaN/Inf. Add a property test over nested models. |
| Q1-18 | MINOR | A.7 `tzdata` | `zoneinfo` checks the system TZPATH before the `tzdata` wheel, so Linux and Windows can use different tz database versions. This is harmless for Kolkata in 2015, but not for a pilot plant with DST. | Set `PYTHONTZPATH=` (empty) everywhere so both platforms use the wheel. Record the `tzdata` version in the manifest. |
| Q1-19 | MINOR | A.3 | `PYTHONHASHSEED=0` is set only "in the image"; native runs differ. | Do not rely on it. Add a CI and pre-commit job that runs the goldens with `PYTHONHASHSEED=random`. |
| Q1-20 | MINOR | A.3 RLIMIT | `RLIMIT_AS` 2 GiB caps **virtual** memory. pyarrow (jemalloc) and the 256 MB SQLite mmap reserve address space, which can raise spurious `MemoryError` in the child. | Measure peak VSZ in `make smoke` with the full demo build. Consider `RLIMIT_DATA`, or cap with headroom. |
| Q1-21 | MINOR | D-04 | The manifest's `sorted record_hashes` does not state which tables it covers. | List them explicitly: claims, comparisons, conflicts, envelopes, review_items, review_events, decisions. Add `test_manifest_covers_review_events`. |

### 2.3 pypdfium2 plan (D.2)

| ID | Sev | Issue | Concrete fix |
|---|---|---|---|
| Q1-22 | **BLOCKER** | The hidden-text pixel test runs on the **union bbox** of the span. A partial attack passes: the visible text reads "Machine 21 had issues", and a hidden white "no " is inserted. `page_text` then says "had no issues" and matches the ∀ phrase. The union crop includes the visible word "issues", so std-dev ≥ 8 and the span is accepted. The same thing happens when white text sits over a visible table rule or image. | Run the visibility test **per character or per word** over the span. If any non-whitespace char fails (crop std-dev < 8, size < 4 pt, outside the CropBox, render mode 3, or fill alpha 0), hold the whole span. Better still, render the page with and without that text object (`page.remove_obj` on a copy) and require a pixel difference inside each char box. Add the fixture `hidden_negation.pdf` and `test_partial_hidden_span_held`. |
| Q1-23 | MAJOR | The span bbox is a union "of the char boxes in `[char_start, char_end)`". Generated chars (`\r\n`, inserted spaces) have empty or zero boxes, which pull the union to the origin. A multi-line quote's union also covers unrelated visible text, which corrupts both the overlay and the pixel test. | Skip generated and zero-area boxes. Store `bbox_pt` as a **list of per-line rects**. The pixel test and the `RegionViewer` overlay iterate over the lines. |
| Q1-24 | MAJOR | The text-normalisation contract is undefined. The plan hashes the raw `page_text` but cross-checks "after NFC". Phrase rules need whitespace and NFC tolerance. FR-ING-1 acceptance needs `quote == page_text[s:e]` exactly. Surrogate pairs: `FPDFText_GetUnicode` returns UTF-16 units per index, so a non-BMP char takes two indices. | Pin it down: `page_text` = the raw char loop with surrogate pairs joined (both pdfium indices map to one offset), **no** NFC. Rules match on a normalised view with an offset map back to raw offsets, as the LLM verifier does. Write the artifact in binary mode (no CRLF translation). Record a `text_canon_version` in the `PageText` artifact. Add `test_surrogate_pair_offsets` and `test_quote_spans_generated_linebreak`. |
| Q1-25 | MAJOR | Recheck "re-hashes only the cited artifact plus the source sha". FR-UI-2 and PRD §13 require **re-extracting** the cited value (`value_ok`). Hashing a stored artifact against its own hash does not prove it derives from the source. | Recheck re-runs `page_text(pdf, page)` (a few ms per page) and compares it to `page_text_sha256`. OCR crops re-read via the cache in replay; CSV rows are re-read from source bytes; Arrow slices are re-sliced from the partition. Keep the < 1 s budget by limiting it to the one cited page. |
| Q1-26 | MINOR | The font-size fallback "char-box height < 3 pt" uses tight boxes (`loose=False`). A lowercase x-height in 6 pt legitimate text is about 3 pt, so small print gets held. | Use `get_charbox(i, loose=True)` height < 4 pt, which matches the PRD threshold. |
| Q1-27 | MINOR | `render(draw_annots=False)` for the pixel test misses text covered by a white annotation. A viewer shows that text as covered, but the test sees it as visible. | Render with annotations for the hidden-text test. The proof PNG may stay without them, but then cache both. |
| Q1-28 | MINOR | The "no text layer" and "unsupported rotation" review items are not in the `ReviewItem.type` Literal, so `extra="forbid"` models raise. | Add `no_text_layer` and `unsupported_page` to the enum, and update `schema.d.ts` before the h8 freeze. |
| Q1-29 | MINOR | FR-ING-1 also accepts **`.txt`/`.md`**. No reader, offset semantics or proof view is defined for them, because there is no page PNG. | A-03: decode strict UTF-8 (strip BOM, keep the bytes so CRLF stays as-is). `page_text` = the decoded file, `page = None`. `TextSpanView` renders text-only. Add one fixture. |

### 2.4 Interfaces

| ID | Sev | Issue | Concrete fix |
|---|---|---|---|
| Q1-30 | MAJOR | FR-UI-4 (P0) has gaps. (a) "Mark conflict explained" has no route: conflicts are not review items, and decisions go only to `/review/{rid}`. (b) Auto-escalation after 1 working day (A6, "computed at read time from the Clock") has no task. (c) `DecisionRequest.choice: str` is not validated against the candidates or values. | (a) Open a `ReviewItem(type=conflict)` per ConflictRecord, or add `POST /cases/{cid}/conflicts/{cfid}/explain`. (b) Add it to B-10 or D-05: a derived `escalated` status at read time from `opened_at` + the `shifts.yaml` working calendar, with `test_auto_escalate_after_one_working_day`. (c) Make `choice` a discriminated union per review type and validate it against the item. |
| Q1-31 | MINOR | §0 and D-05 list 409 only for already-decided and evidence-changed. PRD §13 also has `build-in-progress` with `Retry-After`. | Add it to D-05 with `test_build_conflict_409_retry_after`. |
| Q1-32 | MINOR | `GET /cases/{cid}/entities/{eid}/envelope` and `GET /cases/{cid}/claims/{id}` are **unversioned**, while envelopes change per version (drift guard). This breaks T-29 "all panels same version" and makes the cache headers ambiguous. | Add `?v=` (required) or nest the routes under `/versions/{v}/`. Apply the versioned-JSON cache policy. Note it as a PRD §13 erratum. |
| Q1-33 | MINOR | `CaseVersion.views` = {story, timeline, review}, but `/state` (D2) is said to be "never computed per request". | Add a `state` view to the snapshot projections. |
| Q1-34 | MINOR | §C.3 lists `split_telemetry` under "Stage functions (pure)" but marks it adapter-side. | Move it to an adapters section. Only `read_sensor` (through the Q1-12 port) stays in core. |

### 2.5 Schedule and hour ledger

| ID | Sev | Issue | Concrete fix |
|---|---|---|---|
| Q1-35 | MAJOR | **B-01 is budgeted at 2.0 h but owns the h0–h8 window**. It covers about 25 frozen models with validators, 9 ports, 8 fakes, ConfigBundle and the schema export. Either B is idle for 6 h in the calendar (and the ledger is wrong) or B-01 is under-estimated by about 4 h. Either way the h8 freeze is the critical path for everyone. | Re-estimate B-01 at 4–5 h. Move the ports, fakes and port contract tests to A (A-01 has the same window) and ConfigBundle to D. Show the calendar per person: h0–h8 B = B-01 plus B-02 prep. |
| Q1-36 | MINOR | Ledger narrative arithmetic. The listed deltas (+2.5 +0.5 −1 −0.5 −0.5 −0.5 −0.5) sum to **0**, yet total buffer falls from 10 h to 8.5 h. The unlisted changes are A-01 +1, A-12 −1.5, C buffer +0.5 and the C-01 CSP spike. The "correctness floor ≈ 14 h" is really B-02..B-09 + B-11 = **24 h** (plus the harness). The "security floor ≈ 9 h" is ≥ 10 h. | Restate the deltas in full and correct the floor totals. The column sums themselves are correct (4 × 30.5). |
| Q1-37 | MINOR | A carries the newest risk (pypdfium2, R2) with only 1.5 h buffer and 1.5 h integration. The judge estimated +3 h; the plan gives +2.5 h. D's 4 h reserve is earmarked for B only. | Make D's reserve "B or A", and set a pypdfium2 checkpoint at h6 (offsets, boxes and render round-trip green) that triggers escalation. |
| Q1-38 | MINOR | Sleep windows: B is asleep h25–29.5, across the h26 stretch gate and the h28 holdout. D is asleep h21–25.5, across the D-10 goldens and the h24 M3 exit. | Move the holdout to h30 after B is back, or move B's sleep earlier (h22–26.5). Make the h24 M3 exit a B+C sign-off with D's goldens due by h21. |
| Q1-39 | MINOR | Named tests missing from §D.3: `test_no_update_paths_status_derived` (N-1), `test_no_secret_in_logs_or_responses` (T-39), `test_groq_disabled_by_default_no_egress` (T-40), the NFR-1 "100% pointers re-resolve" test, and a relative-time test (FR-NORM-3: "yesterday", "on shift 2"). | Add them to D-03, A-01, B-07 and D-10 respectively. |

### 2.6 Product phases (P1–P4)

| ID | Sev | Issue | Concrete fix |
|---|---|---|---|
| Q1-40 | MAJOR | P2-01 and P2-02 claim records are "copied verbatim" into **JSONB** and still verify. JSONB re-orders keys, drops duplicates and re-renders numbers. Verification would then depend on re-canonicalising parsed JSON (floats round-tripped through psycopg), not on the stored bytes. | Store `body_jcs BYTEA` (the canonical bytes, the source of truth) plus `body JSONB` (a derived query column). Integrity hashes `body_jcs`. The migration copies the bytes and checks `sha256(body_jcs) == record_hash` per row. Keep fixed-width `valid_start/end` text as authoritative; `tstzrange` is a generated column. |
| Q1-41 | MAJOR | Decision concurrency relies on SQLite `BEGIN IMMEDIATE`. On Postgres with 1–2 workers plus the API, T-24 (one of 20 wins) and version numbering (`UNIQUE(case, version)`) need an explicit lock. The plan says only that the "port contract tests run against both stores". | Use `pg_advisory_xact_lock(hash(case_id))` around decision, rerun and snapshot, plus the build commit. Run `test_20_parallel_decisions_one_wins` and a two-worker build race on Postgres in P2 CI. |
| Q1-42 | MAJOR | The pilot exit and GO criteria cannot be measured as written. "Precision ≥ 0.85 in live operation" has no minimum sample size or CI. "False alarm ≤ 5%" is a Wilson **upper** bound in P3 but the PRD and judge say it fails only if the **lower** bound > 5%; P4 does not say. "0 gaps read as normal" and "reviewer ≤ 2 h/week" have no measurement method. | Set N ≥ 100 adjudicated conflicts and report the Wilson CI. Pick one false-alarm rule and use it in P3 and P4. Add an automated invariant scan over all versions (no ∀-agree with coverage < 100%) as the "gaps read as normal" metric. Instrument time-in-review from `review_events`. |
| Q1-43 | MAJOR | P3-02 turns documented historian tags into `unit_status=known`. That silently opens a **new comparison path**: telemetry numeric vs. gauge or report numeric. The gate, tolerances, granularity rules (hourly mean vs. instant reading) and tests were never designed for it. | Add a P3 task "sensor-known-unit comparison" with defined statistic and granularity pairing, tolerance from the datasheet, goldens and an ADR. Until it lands, keep check 4 failing for sensor vs. authored even with known units. |
| Q1-44 | MINOR | The migration moves records only. The extraction cache, page-text artifacts and snapshots must move too, otherwise **replay** breaks even when integrity is green. Event order for derived status must also be preserved (`review_events` sequence). | P2-02 also copies cache, artifacts and snapshots with sha checks, and keeps the original `seq` column. The exit criterion adds `replay-verify` on the migrated demo chain. |
| Q1-45 | MINOR | Pilot time semantics are missing. DST in `plant_tz` makes local days 23 h or 25 h, which breaks "24/24 h" and `expected_points=96`. The `before_only` policy for live monitoring is never selected in P3 or P4. Historian resampling to hourly needs a declared statistic and a duplicate check **before** resampling. | Compute expected points from the local day length. Make `training_policy` explicit per case type in P3-08. Run the T-14 detection before resampling, and record the statistic in the window pointer. |
| Q1-46 | MINOR | Quiet-day log coverage is checked for "the day", but "no events within ±3 d" needs coverage of **d ± 3**. Otherwise days at the edge of coverage count as quiet even though events may be unseen. | The coverage predicate covers `[d−3, d+4)`. Add a test at the edge of coverage. |
| Q1-47 | MINOR | The flatline ε = 1e-6·s_c is 0 for degenerate channels (MAD = 0) and undefined under the model-level pool. | Use the model-level s_c if pooled. If s_c = 0, apply flatline with an absolute ε from config and label it. |
| Q1-48 | MINOR | Groq at temperature 0 is not deterministic, which is acceptable because of the cache. But the P1 exit criterion "50-mutation test accepts 0" must run in `replay` against recorded responses as well as `record`, or it is flaky. | Run both modes. Only the replay run gates CI. |

---

## 3. Coverage: requirements without an adequate task

All FR, NFR and D items appear in §H, so nothing is **unmapped**. The rows below are mapped but **under-covered**: the mapped task does not implement the acceptance criterion.

| Req | Gap | Fix ref |
|---|---|---|
| FR-ING-1 | No `.txt`/`.md` reader. The hidden-text guard can be bypassed by a partly hidden span. Offset normalisation is undefined. | Q1-29, Q1-22, Q1-24 |
| FR-NORM-3 | Unknown time cannot be modelled. No test for relative expressions. DST (pilot). | Q1-06, Q1-39, Q1-45 |
| FR-NORM-4 | No series_id or pool identity on envelopes. No per-scope envelopes. The acceptance metric (holdout false alarm) is invalid as planned. | Q1-07, Q1-01, Q1-02 |
| FR-GATE-1/6 | ∀ scope "no error events" and "logs cover window" are not wired into pairing or check 6. | Q1-04 |
| FR-GATE-4 / NFR-6 | The lint does not cover the pandas averaging paths. | Q1-08 |
| FR-TRUST-3 | The τ_review hold cannot run before the gate. | Q1-05 |
| FR-UI-2 / NFR-2 | Recheck does not re-extract (`value_ok`). | Q1-25 |
| FR-UI-4 / FR-LOOP-1 | No "Mark explained" route, no auto-escalation (A6), untyped `choice`. | Q1-30 |
| FR-UI-8 / NFR-4 | Replay is broken by wall-clock in the snapshot, uncached PDF floats, local Tesseract version and per-laptop seeds. | Q1-13, Q1-15, Q1-14 |
| FR-LOOP-2 / D6 | No labelling task or hours. The holdout gate ignores `engine_sha`. | Q1-11, Q1-10 |
| NFR-1 | The "100% pointers re-resolve" test is not named. | Q1-39 |
| D2 | `/state` view not precomputed. | Q1-33 |
| T-39, T-40, N-1 | Named tests absent from §D.3. | Q1-39 |
| PRD §13 | 409 `build-in-progress` missing. Envelope and claim routes unversioned. | Q1-31, Q1-32 |

---

## 4. Checklist results (as requested)

| # | Area | Result |
|---|---|---|
| 1 | FR/NFR/D → tasks | Mapped 100%. 14 under-covered rows (§3). |
| 2 | Correctness floor | **Partially compliant.** Conformal T\*, pooling, quiet-day criteria, sensor_native, duplicates, flatline, half-open/plant_tz, S-88/S-88.1, computed numbers and dev/holdout split are all present. Defects: holdout misuse (Q1-01/02), no T\* oracle (Q1-03), cross-attribute ∀ pairing (Q1-04), unknown time (Q1-06), envelope identity (Q1-07), d ± 3 coverage (Q1-46). It is scheduled before UI polish, but the properties come too late (Q1-09). |
| 3 | Hexagonal / determinism | Telemetry I/O leaks into core (Q1-12). Content IDs are fine except `review_id` (Q1-16). JCS edge cases (Q1-17). Snapshot wall-clock (Q1-13). Cross-OS: CRLF handled; tzdata, hash seed, PDF floats and seeds are not (Q1-14/15/18/19). |
| 4 | pypdfium2 | Char loop, `get_charbox`, `FPDFText_GetFontSize`, capability probes, CropBox and the rotation hold are sound. Defects: union bbox and partial hidden text (Q1-22/23), normalisation and surrogates (Q1-24), tight-box fallback (Q1-26), annotations (Q1-27), enum (Q1-28). |
| 5 | Interface consistency | Stage order bug (Q1-05). Missing routes and enums (Q1-28/30/31/32/33). |
| 6 | Milestones / ledger | Column sums are correct. The narrative and floor totals are wrong (Q1-36). The B-01 calendar is impossible (Q1-35). The holdout falls inside B's sleep (Q1-38). The properties are late (Q1-09). |
| 7 | Product phases | Postgres triggers, REVOKE and TRUNCATE are good. JSONB breaks the "verbatim" claim (Q1-40). Locking (Q1-41). Exit criteria cannot be measured (Q1-42). The known-unit path is untested (Q1-43). Replay data migration (Q1-44). |

**Re-review trigger:** the plan author fixes Q1-01, Q1-02, Q1-22 and replies to each MAJOR with "fixed" or "accepted risk + owner". QA-1 then re-checks §D.1, §D.2, §D.3 and §C only.
