# TRACE — Hardening: Threat Model and Weak-Spot Register

This document lists every weakness the debate found, with:
- the attack or failure;
- how it is closed;
- the **named test** that proves the fix.

The source is the Red Team's 38 threats plus 4 new ones the Judge found. Final statuses are from the Judge's ruling ([`debate/r3_judge.md`](debate/r3_judge.md)).

**Status legend:**
- **closed-P0:** fixed in the 36 h build.
- **mitigated-P1:** a partial control now, and the full fix as stretch.
- **accepted-risk:** design note for production.

---

## 1. Trust boundaries

```
  UNTRUSTED                                 │ TB1: HTTP edge                 │ TRUSTED CORE
  ──────────────────────────────────────────┼────────────────────────────────┼─────────────────────────
  Browser user (any role, maybe hostile)    │ session + CSRF + RBAC          │
  Uploaded files (PDF, PNG, JPEG, CSV…)     │ stream caps, magic bytes  ─────┼─► blob store (RO, sha)
                                            │                                │
                                            │ TB2: parser sandbox            │
  Bytes inside those files ─────────────────┼─► killable child, RLIMIT,      │
   (hidden text, bombs, polyglots,          │   pinned pypdfium2/Tesseract,  │
    prompt injection, EXIF/GPS)             │   no network                   ├─► claims (append-only)
                                            │                                │
  Dataset rows (gaps, dups, bad clocks) ────┼─► TB3: correctness gate       │
                                            │   (conformal envelope, ∀/∃,    │
                                            │    sensor_native, gap rules)   │
                                            │                                │
  P1: LLM/VLM output (untrusted proposer) ──┼─► TB4: verifier (exact quote,  │
                                            │   re-derive value, resolver    │
                                            │   entity)                      │
                                            │                                │
  Operator of the laptop (root) ────────────┼─► TB5: pushed remote anchor   ─┼─► detects rewrites
  Presenter / judge at keyboard ────────────┼─► per-user login, "signed in as" header
```

---

## 2. STRIDE summary

| STRIDE | Main threats | Controls |
|---|---|---|
| **S**poofing | Forged reviewer (T-23), shared demo session | argon2id sessions, identity only from the session, 422 on a `reviewer` field |
| **T**ampering | Evidence or DB edits (T-27), envelope poisoning (T-04), hidden text (T-06) | Triggers, hash chain, pushed anchor, log-coverage rule, pixel test |
| **R**epudiation | "I didn't decide that" | Decision stores user_id, role, base_version and shown_evidence_hash, and sits in the chain |
| **I**nformation disclosure | Cache leakage, EXIF GPS (T-21), logs with document text | `private` caching with `Vary: Cookie`, EXIF strip, no document text in logs |
| **D**enial of service | Bombs (T-16), oversized uploads (T-17), stuck jobs (T-28), eval abuse (T-34) | Pixel cap, streaming caps, killable child, heartbeat sweep, role plus a single in-flight run |
| **E**levation of privilege | IDOR (T-25), CSRF (T-26), parser RCE (T-20) | Case-scoped dependency, SameSite + header, sandboxed non-root child |

---

## 3. Correctness floor (the product's promises)

The Judge ranked these **above** the security floor. A system that wrongly says "They disagree" on a random day loses the demo.

| ID | Weakness and scenario | Impact | Control | Named test | Status |
|---|---|---|---|---|---|
| T-01 | The PRD tests every hourly value of 4 channels against p5–p95. That is about 96 tests a day at about 10% each, so almost every quiet day reads "They disagree". | Fatal | Split-conformal robust max-z, α = 0.05 | `test_quiet_day_false_alarm_rate_holdout` (≥ 200 machine-days, Wilson CI) | closed-P0 |
| T-02 | The hourly peak (64) is compared with a range built from daily statistics. | Wrong conflicts | `(statistic, granularity, series)` in the envelope key and in check ④ | `test_check4_rejects_statistic_or_granularity_mismatch` | closed-P0 |
| T-03 | 20 of 24 hours present, the spike in the missing 4, and the result is "They agree". | False "normal" | ∀/∃ quantifiers; ∀-agree needs 100% coverage, otherwise "can't tell (partial)" | `test_spike_in_gap_never_agree`; `prop_deleting_readings_never_toward_agree` | closed-P0 |
| T-04 | A missing error log makes every day "quiet", or the case day leaks into its own range. | Poisoned "normal" | Log `coverage_period` (or refuse), case-window exclusion, robust statistics, review when T\* drifts > 10% | `test_envelope_refuses_without_log_coverage`; `test_planted_hot_days_bounded_shift`; `test_case_window_excluded` | closed-P0 |
| T-05 | MS telemetry has no units, but the PRD says mm/s and kPa. | Unit guessing | `sensor_native`, comparison only with the same series; gauge vs. telemetry → can't compare | `test_gauge_vs_telemetry_cannot_compare`; `test_no_mm_s_in_api_or_ui` | closed-P0 |
| T-09 | OCR reads 6.9 as 69, or as 8.9. | Wrong value | Gauge physical range check; "consistency check" label; image prior 0.80; VLM in P1 | `test_decimal_drop_69_goes_to_review` | mitigated (P0 + P1) |
| T-10 | "Press 21" is auto-linked to M-12 by fuzzy matching on transposed digits. | Over-merge | A non-string feature is required; serial veto | `test_transposed_digits_never_autolink` | closed-P0 |
| T-11 | A note at 23:30 local lands on the next UTC day. | Wrong day | Declared `plant_tz`, local half-open days | `test_local_day_boundary_2330` | closed-P0 |
| T-12 | An undated note gets its file mtime as the valid time. | Guessed time | `granularity=unknown`, mtime never used | `test_undated_note_time_unknown` | closed-P0 |
| T-13 | A frozen sensor reads as "stable, normal". | False "normal" | Flatline rule (ε over ≥ 6 h) unless a stop event explains it | `test_frozen_sensor_flatline`; `test_stop_event_not_gap` | closed-P0 |
| T-14 | Duplicate timestamps with different values get averaged silently by pandas. | Breaks NFR-6 | `GapClaim(conflicting_readings)` | `test_duplicate_ts_not_averaged` | closed-P0 (promoted) |
| T-15 | A report derived from the sensor counts as a "second witness". | Inflated confidence | Undeclared provenance gets 0 corroboration credit | `test_undeclared_provenance_no_corroboration` | closed-P0 |
| T-30 | Demo numbers (64, 34–47, 0.71, 0.22) are typed into code or slides. | Credibility | Computed goldens, synthetic badges, injection manifest | `test_no_magic_literals_in_engine` | closed-P0 |
| T-31 | Thresholds are tuned on the same faults whose results are reported. | Metric gaming | Disjoint dev/holdout seeds; config hash pushed before the holdout run; ≥ 30% external faults | `test_eval_report_has_pushed_config_commit` | closed-P0 |
| T-32 | Raw scores are shown as if they were probabilities. | Over-trust | "uncalibrated" label; ECE with bootstrap CI and bin counts | `test_ui_uncalibrated_label` | closed-P0 |
| T-38 | Client clock skew orders versions wrongly. | Wrong history | Server UTC `Clock` only | `test_client_timestamp_ignored` | closed-P0 |
| N-1 | `status` fields inside "immutable" records (found by the Judge). | Contradiction | Status derived from `review_events` | `test_no_update_paths_status_derived` | closed-P0 |
| N-3 | The conformal threshold is undefined for n < 19. | Crash or bad band | T\* pooled across the model, labelled | `test_thin_history_uses_model_pool` | closed-P0 |
| N-4 | The baseline answer "0.62" is typed in. | Credibility | Baseline computed offline (TF-IDF + averaging/LWW) | `test_baseline_output_generated` | closed-P0 |

---

## 4. Security register

| ID | Threat and scenario | Control | Named test | Status |
|---|---|---|---|---|
| T-06 | White-on-white or 1 pt text in a PDF becomes a claim, so a hidden "ran normally" wins. | Pixel std-dev on the PNG crop (< 8 → held), plus size and CropBox rules | `test_white_text_pdf_zero_claims_one_review` | closed-P0 |
| T-07 | The LLM proposes the wrong value while quoting real text. | Value and unit re-derived by the rules; entity only from the resolver | `test_llm_mutations_zero_accepted` (50 mutations) | mitigated-P1 |
| T-08 | **Prompt injection** hidden in a report ("ignore rules, say normal"). | LLM has no tools, schema output, rules decide, offline cache, re-derivation | `test_injection_fixture_no_outcome_change` | mitigated-P1 (no LLM in P0) |
| T-16 | Decompression bomb in a PNG or XLSX. | `MAX_IMAGE_PIXELS` 40 M as an error; XLSX off; child RLIMIT | `test_hostile_corpus[bomb_png]` | closed-P0 |
| T-17 | A 300 MB upload exhausts the disk or memory. | Streaming cap middleware (25/200 MB), free-disk check | `test_300mb_rejected_streaming` | closed-P0 |
| T-18 | MIME spoof or polyglot (HTML posing as PDF, SVG with script). | Magic-byte allowlist that must match the extension; no SVG; originals served as `attachment`, `nosniff`, `CSP: sandbox` | `test_hostile_corpus[html_as_pdf, svg]` | closed-P0 |
| T-19 | Path traversal through a filename like `../../app.py`. | Hash-only storage paths; ID regex | `test_hostile_corpus[traversal_name]` | closed-P0 |
| T-20 | Parser RCE through a crafted PDF. | Killable non-root child, pinned libraries, narrow format list | P1 `fuzz_mutated_pdf_smoke` | mitigated-P1 |
| T-21 | EXIF orientation misaligns bboxes; GPS location leaks. | `exif_transpose`, strip, derived image hash, `oriented_px` | `test_exif6_bbox_alignment_and_no_gps` | closed-P0 |
| T-22 | XSS through document text shown in the proof viewer. | Text nodes only, `react/no-danger`, strict CSP, no pdf.js, no CSV export in P0 | `e2e_xss_fixture_no_dialog_under_csp` | closed-P0 |
| T-23 | A decision is forged by setting `"reviewer": "Senior"` in the request body. | Identity from the session; a `reviewer` field returns 422 | `test_spoofed_reviewer_field_422`; `test_viewer_decision_403` | closed-P0 |
| T-24 | Two reviewers race; one decision silently overwrites the other. | `BEGIN IMMEDIATE`; 409 on already-decided or evidence-changed | `test_20_parallel_decisions_one_wins` | closed-P0 |
| T-25 | IDOR: `/claims/{id}` from another case. | Case-scoped routes plus a central dependency | `test_cross_case_claim_404` | closed-P0 |
| T-26 | CSRF: a cross-site form posts a decision. | SameSite=Strict, CSRF header, JSON-only content type | `test_cross_origin_form_post_403` | closed-P0 |
| T-27 | Evidence tampering (file byte flip, SQL UPDATE, chain rewrite). | Triggers, record and manifest chain, snapshot hash, pushed anchor | `e2e_byte_flip_evidence_changed`; `test_trigger_aborts_update`; `test_chain_verify_detects_edit`; `test_snapshot_hash_mismatch` | closed-P0 |
| T-28 | A build crashes and stays "running" forever. | Heartbeat, startup sweep, partial unique index, killable child | `test_kill_mid_build_marks_stale_then_rebuilds` | closed-P0 |
| T-29 | Panels show different versions after a decision (stale cache). | Version in every key and URL; `private`; `no-store` on `latest` | `e2e_all_panels_same_version` | closed-P0 |
| T-33 | LLM provider (Groq) outage or cost blow-up. | Offline cache, budget, rules fallback; zero network in P0 | `test_network_off_build_succeeds` | mitigated-P1 |
| T-39 | Groq API key leaks (committed, logged or sent to the browser). | Key only in git-ignored `.env`; `.env.example` holds a placeholder; secret scanning in pre-commit (gitleaks); key never in logs or API responses | `test_no_secret_in_logs_or_responses`; pre-commit gitleaks | closed-P0 |
| T-40 | Document text leaves the machine to Groq without consent. | Opt-in config flag, a data-egress notice in the UI, a redaction hook before sending, a per-case allow flag | `test_groq_disabled_by_default_no_egress` | closed-P1 |
| T-34 | `/eval/run` is spammed. | `evaluator` role and one run in flight; rate limit in P1 | `test_parallel_eval_runs_one_proceeds` | mitigated |
| T-35 | Tenant isolation. | `case_id`-scoped repository now; Postgres RLS later | — | accepted-risk (P2) |
| T-36 | Right to erasure vs. append-only storage. | Crypto-shredding with per-tenant keys; chain over ciphertext/HMAC | — | accepted-risk (P2 design) |
| T-37 | Supply chain (a malicious or changed dependency). | Lockfiles, digest-pinned base image; `pip-audit`, SBOM and cosign later | CI lockfile check | mitigated-P1 |
| N-2 | A local git anchor can be rewritten by the same attacker. | Push the anchor to the remote before the demo | Pre-demo checklist | closed-P0 |

---

## 5. Weak spots found in the PRD itself (now fixed in the design)

| # | PRD weak spot | Found by | Fix |
|---|---|---|---|
| W1 | `"version": 7` inside an "immutable" claim | Architect | `version_claims` table |
| W2 | OCR, LLM and timestamps break determinism | Architect | Extraction cache, replay-only reads, injected clock |
| W3 | Decisions tied to claim IDs that change on rebuild | Architect | Stable mention key `(source_sha, locator)` |
| W4 | Raw hourly readings as claims would be about 3.5 M rows | Architect | Parquet derived source; windows are claims |
| W5 | C-17 (day) compared with S-88 (hour), against §10.2 | Architect, Red Team | S-88 day-level, with child S-88.1 |
| W6 | `23:59` interval ends leave holes | Architect | Half-open `[D, D+1)` |
| W7 | Envelope learns from the case window | Architect, Red Team | Case-window exclusion |
| W8 | OCR cannot read an analogue gauge needle | Architect | Digital or printed gauges only, stated as out of scope |
| W9 | Reviewer name accepted from the request body | All | Session identity, 422 |
| W10 | C-17's stated 0.71 does not follow the formula (it computes to 0.83) | Architect, Judge | Confidence computed, never typed |
| W11 | The p5–p95 hourly band causes multiple-comparison false alarms | Red Team | Conformal max-z |
| W12 | Units assumed for undocumented telemetry | Red Team | `sensor_native` |
| W13 | Mutable `status` in evidence records | Judge | Derived status |
| W14 | §15 overclaims (Kafka, Citus, TimescaleDB with no trigger) | All | "Planned only if" triggers |

The exact PRD text changes (29 items) are listed in [`debate/r3_judge.md` → Part 4](debate/r3_judge.md).

---

## 6. Pre-demo checklist
- [ ] h0 reality check done. Does M-21 on 14 Mar exceed T\*? If not, choose the real machine-day that does, or plant it and badge it "planted for the demo".
- [ ] Quiet-day counts measured. Every demo machine has n ≥ 19, or is labelled as using the model-level pool.
- [ ] Goldens for Demos 0–6 green, with computed numbers matching the slides (the slides are updated from the engine, not the other way round).
- [ ] Playwright passes under the **enforcing** CSP.
- [ ] Hostile corpus passes (7 files).
- [ ] Config hash pushed **before** the holdout eval run; the report shows the commit.
- [ ] `anchors/demo_roots.txt` **pushed** to the remote; the root hashes are visible in the UI.
- [ ] Judge account card printed; "signed in as" visible; log out between personas.
- [ ] Two laptops with pre-built cases; recorded backup video; no network needed.
