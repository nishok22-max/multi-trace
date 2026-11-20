<!-- Assembled from reviews/tester_plan.md; synthesis decisions recorded in §0 below. -->
# TRACE — Test Plan (MVP 36 h + Plant Pilot)

| Field | Value |
|---|---|
| Author | The Tester |
| Based on | `reviews/technician_revision.md` (v2, final; task IDs, milestones M0–M6, ledger), `reviews/qa1_review.md`, `reviews/qa2_review.md`, `system-design/HARDENING.md`, `system-design/DECISIONS.md` (ADR-15 S1–S11), `TRACE_PRD.md` v1.2 |
| Date | 2026-11-20 |
| Binding rule | Every test named in technician_revision §D.3, §E and §H is binding **under that exact name** (DoD G-3). Tests marked **†** are new: the Tester adds them to close an acceptance gap. Each † test has an owner and a milestone and is in scope for the DoD. |

---

## 0. Synthesis decisions (binding; resolved at assembly)
| Open item from the Tester | Decision |
|---|---|
| **Golden manifest hash vs. `engine_sha`.** Every commit would change `manifest_hash`. | Goldens pin a **`semantic_root`**: the manifest computed with `engine_sha`, `lockfile_hash` and `binary_versions` replaced by the constant `"golden"`, through the same `canonical.py`. Goldens also pin every computed demo value, outcome and check table. The **real** `manifest_hash` (with the true engine SHA) is still computed, chained, anchored and checked by `make replay-verify` and `/integrity`. Test: `test_golden_semantic_root_ignores_engine_sha` †. Owners: B and D confirm at h16, before the first bless. |
| **Hostile corpus contents.** | The 13-file list in §6.1 plus the generated stream is accepted as binding. It is a superset of the original 7 in HARDENING §4. Person A may add fixtures but not remove them; additions need a note in the PR. |
| **Unmapped IDs (§11).** | Accepted as documented. T-35 and NFR-9 are P5. NFR-8's "~1M readers" is a design claim, and the pilot load-tests only p95 < 300 ms and the 2-minute build. T-36 is partial (P2 policy test, P3 runbook drill, crypto-shredding in P5). |

---

## 1. Strategy

### 1.1 What we test first
The judge ranked the **correctness floor** above the security floor, and so does this plan. If TRACE wrongly says "They disagree" on a quiet day, or "They agree" across a gap, it fails the demo. A missing header does not lose it. So the order of priority is:

1. Correctness-floor invariants: property tests plus the conformal oracle.
2. Goldens for the demos.
3. Security floor S1–S11.
4. NFR-7 performance.
5. UI and e2e.

The test pyramid exists to stop us from proving the floor only through the browser.

### 1.2 Pyramid (MVP target counts)
| Level | Marker / tool | What it covers | Approx. count | Runs in |
|---|---|---|---|---|
| Unit | pytest, `tests/unit`, `tests/ports` | Models, validators, IDs, canonical form, rules, resolver, time, gate, scores, port contracts over fakes **and** real adapters | ~180 | pre-commit (`test-fast`) |
| Property | Hypothesis, `tests/properties` | Floor invariants (§4) | 16 | pre-commit (derandomised), nightly (deep) |
| Golden | `tests/golden` | Demos 0–6: pinned outcomes, check tables, computed values, roots | 9 demos / 11 files | pre-commit + `golden-randseed` |
| Integration / API | httpx `AsyncClient` against the app, real SQLite and blob dir, `tests/api`, `tests/authz` | Routes, 409s, cache headers, authz matrix, recheck, compute-then-commit | ~70 | `make test` |
| Security | `tests/hostile_corpus`, `tests/authz`, sentinel, socket guard | Hostile files, CSRF, origin, secrets, egress, upload caps | ~45 | `make test`, `make hostile` |
| Image / ops | marker `image`, `tests/ops` (docker CLI) | S11, loopback compose, dockerignore, `--network none`, digest equality, image secret grep | ~10 | D-11, `make check-image` |
| Perf | marker `perf`, `tests/perf` | NFR-7 budgets on the image and native Windows | 12 | `make check-perf` at M3, M4, M6 |
| E2E | Playwright, `e2e/specs` | Proof, decision, tamper, XSS/CSP, versions, story, a11y labels | 5 binding + 8 † | `make e2e` (image) |
| Eval | marker `holdout` / `eval`, `tests/eval` | Split hygiene, leave-block-out, Wilson, ECE/Brier, baselines, pushed hashes | ~14 | dev: `make test`; holdout: `make eval-holdout` only |

### 1.3 Tools (version classes; exact pins come from `uv.lock` / `package-lock.json` at h0)
| Tool | Class | Use |
|---|---|---|
| pytest | ≥ 8.3 | Runner. Markers: `holdout`, `perf`, `image`, `native`, `slow`, `pg`, `minio`, `oidc`, `record`, `quarantine` |
| pytest-xdist | ≥ 3.6 | `-n auto` for unit, property, golden and API tests. Perf, image and holdout tests run serially (`-p no:xdist`) |
| pytest-socket | ≥ 0.7 | `--disable-socket --allow-unix-socket` is global in `pytest.ini` (S10, T-40) |
| pytest-cov | ≥ 5 | Floor modules (`compare/`, `normalise/gaps.py`, `normalise/envelopes.py`, `review/holds.py`) need ≥ 95% branch coverage. Other modules are reported only |
| Hypothesis | ≥ 6.112 | Profiles: `precommit` (200 examples, `derandomize=True`), `ci` (1,000), `nightly` (10,000, example database on) |
| Schemathesis | ≥ 3.36, **P1** (P1-09) | Stateful fuzzing against `openapi.json` from `contracts-v1` |
| Playwright | `@playwright/test` ^1.48, Chromium only | Runs against the image under the enforcing CSP header. Timing assertions use the median of 5 runs |
| vitest + Testing Library | ^2.1 / ^16 | Island unit tests (`safeFormatter`, `textSlice`, `bbox`) |
| k6 | current LTS, **P2** | NFR-8 load test (§5.3). Locust is the fallback if k6 cannot be installed on the plant VM |
| gitleaks | v8 class | Pre-commit with the custom `gsk_` rule; CI with push protection from P1-11 |
| pip-audit / npm audit / trivy | ≥ 2.7 / npm 10 / trivy 0.5x | M5 one-shot (`make audit`); in CI from P1-09/P1-11 |
| import-linter | ≥ 2.1 | The `.importlinter` contracts in §A.4, plus the runtime twin `test_api_never_imports_pdfium` |
| ruff, mypy, tsc, eslint | per §B.3/B.4 | Static gates (`make lint type`); the eslint rules are tested in §6.7 |
| `tools/check_no_mean.py` | in repo | The AST never-average gate; its own unit test is `test_check_no_mean_flags_pandas_paths` † |

### 1.4 Test directory layout
```
backend/tests/
  conftest.py                 FixedClock, MemClaimStore, DictExtractionCache(replay), seeded users, socket guard
  unit/<module>/test_*.py     core and adapters (incl. test_conformal_oracle.py)
  ports/test_<port>_contract.py   parametrised: [fake, real]
  properties/prop_*.py        Hypothesis (strategies in properties/strategies.py)
  golden/demo_{0,1a,1b,2,3,4,5,5b,6}/   input_manifest.yaml, expected.json, expected_checks.json, README.md
  golden/test_golden.py       one parametrised test per demo
  hostile_corpus/files/       13 committed files (+ generator for the 300 MB stream; never committed)
  hostile_corpus/test_hostile_corpus.py
  authz/test_authz_matrix.py  matrix of roles × routes (§6.2)
  api/test_*.py               routes, 409s, headers, recheck, problems
  perf/test_*.py              marker perf → data/perf_report.json
  eval/test_*.py              split, protocol, Wilson, ECE/Brier, baselines; holdout tests marked `holdout`
  ops/test_*.py               marker image (docker inspect/run), compose/dockerignore parsers
  pilot/                      (P2+) marker pg/minio/oidc; same suites re-parametrised over PgClaimStore/S3BlobStore
  fixtures/                   -text in .gitattributes; small PDFs/PNGs/CSVs per test
frontend/src/**/*.test.ts     vitest
e2e/specs/{proof,decision,tamper,xss,versions,story,a11y}.spec.ts
ops/loadtest/k6/              (P2) scenarios + thresholds
```

### 1.5 Fixtures and seed data
- **Deterministic seeds.**
  - Seed PDFs, photos and logs are generated **once, in the image** (reportlab `invariant=1`, vendored DejaVu font, fixed RNG). The bytes and `seed/SHA256SUMS` are committed.
  - `make seed` only verifies the bytes. `test_seed_sha256sums_match` † runs in pre-commit, and a mismatch is a Sev-2 defect.
  - Injector seeds are integers in disjoint ranges: dev uses `1000–1999` and holdout uses `9000–9999`. Machines are split dev/holdout by `sha256("trace-split-v1"‖machineID)` parity. The fault manifests live in `seed/faults/{dev,holdout}/`.
- **Clock and IDs.** Every test uses `FixedClock("2015-03-15T09:10:00Z")` unless it is testing the clock itself. IDs are content-addressed, so goldens can pin them.
- **Extraction cache.** Tests run in **replay** mode against `seed/cache/`. Record mode runs only in the image (`make record-cache`, marker `record`). A replay miss is an error, so a test that hits one is a real failure and never a skip.
- **Golden files.** One directory per demo (§3). The JSON is canonical JCS, so diffs are stable.
- **Hostile corpus.** 13 committed files plus one stream generated at runtime (§6.1). Large sizes are always generated and never committed.
- **Holdout quarantine.** A Python audit hook in `conftest.py` raises if any test that is not marked `holdout` opens a path under `seed/faults/holdout/` or reads a holdout machine's partition. That test is `test_dev_suite_never_reads_holdout` †.
- **Users.** `tools/seed_users.py` creates `viewer1`, `reviewer1`, `reviewer2`, `senior1`, `ingestor1`, `evaluator1`, plus the judge persona. Passwords are generated per run and written to `seed/credentials.local.txt`, which is git-ignored and dockerignored. Tests read them from a fixture and never from the source code.

---

## 2. Acceptance matrix

Abbreviations:
- **Level:** U unit · P property · G golden · I integration/API · S security · Img image/ops · Pf perf · E e2e · Ev eval.
- **First passes at** is the milestone at which the test must first be green. It stays green from then on.
- **Owner** is A/B/C/D. Pilot tasks keep the same owners.

### 2.1 Functional requirements
| Req | Named test(s) | Level | First passes at | Owner |
|---|---|---|---|---|
| FR-ING-1 | `test_quote_equals_page_text_slice`, `test_surrogate_pair_offsets`, `test_quote_spans_generated_linebreak`, `test_plaintext_reader_offsets_crlf_preserved`, `test_white_text_pdf_zero_claims_one_review`, `test_partial_hidden_span_held`, `test_covered_text_held`, `test_render_stage_ms_recorded`, `test_no_text_layer_opens_review` †, `test_rotated_page_unsupported_review` † | U/I | M3 | A |
| FR-ING-2 | `test_cell_pointer_row_sha_and_offset`, `test_envelope_refuses_without_log_coverage`, `e2e_table_proof_scrolls_to_cell` † (FR-ING-2 acceptance) | U/E | M3 / M4 | A (+B), C |
| FR-ING-3 | `test_duplicate_ts_not_averaged`, `test_split_preserves_duplicate_rows`, `test_sensor_window_recompute_equals_claim` †, `test_derived_partition_has_derived_from_sources` † | U/I | M3 | B, A |
| FR-ING-4 | `test_decimal_drop_69_goes_to_review`, `test_exif6_bbox_alignment_and_no_gps`, `test_reread_mismatch_surfaced` †, `e2e_image_proof_bbox_outlined` †; P1: `test_ocr_vlm_disagreement_held` † (P1-04) | U/E | M3 / M4 / P1 | A, C |
| FR-ING-5 (P1) | `test_llm_mutations_zero_accepted`, `test_injection_fixture_no_outcome_change`, `test_proposal_extra_fields_rejected`, `test_llm_replay_miss_is_error`, `test_record_does_not_overwrite_cached_response`, `test_cache_key_changes_with_prompt_or_redactor` | U/I | P1 | A |
| FR-ING-6 | `test_source_provenance_fields_complete` †, `test_blob_put_existing_hash_is_noop_windows`, `test_undeclared_provenance_no_corroboration` | U/I | M3 | A, B |
| FR-NORM-1 | `test_gauge_vs_telemetry_cannot_compare`, `test_no_mm_s_in_api_or_ui`, `test_unknown_unit_never_converts`, `test_unit_swap_fault_detected` †, golden Demo 3 | U/G | M3 | B |
| FR-NORM-2 | `test_transposed_digits_never_autolink`, `test_serial_conflict_vetoes`, `test_decision_keyed_by_mention_key`, `test_review_id_stable_across_extractor_version`, `test_alias_faults_resolved` †, golden Demo 2 | U/G | M1 / M3 | B |
| FR-NORM-3 | `test_local_day_boundary_2330`, `test_undated_note_time_unknown`, `test_unknown_time_has_no_bounds`, `test_relative_time_yesterday_shift2`, `test_client_timestamp_ignored`, `test_time_shift_fault_detected` †, `e2e_timeline_all_kinds_one_axis` †; P3: `test_dst_day_expected_points` † (P3-02) | U/E | M1 / M3 / M4 / P3 | B, C |
| FR-NORM-4 | `test_conformal_oracle`, `test_quiet_day_false_alarm_rate_dev`, `test_quiet_day_false_alarm_rate_holdout`, `test_thin_history_uses_model_pool`, `test_envelope_per_phrase_scope`, `test_quiet_day_requires_coverage_d_pm3`, `test_case_window_excluded`, `test_envelope_drift_opens_review`, `e2e_expert_view_shows_envelope` †; P1: `test_load_bin_small_n_falls_back` † (P1-06) | U/Ev/E | M3 / M4 / M6 | B, D, C |
| FR-NORM-5 | `test_spike_in_gap_never_agree`, `prop_deleting_readings_never_toward_agree`, `test_frozen_sensor_flatline`, `test_stop_event_not_gap`, `test_flatline_degenerate_scale_abs_eps`, goldens Demo 1a/1b | U/P/G | M3 | B |
| FR-GATE-1 | `test_gate_checks_recorded_in_order` †, `test_forall_normal_vs_error_row_disagrees`, `test_forall_agree_requires_log_coverage_of_window`, `test_check4_rejects_statistic_or_granularity_mismatch`, golden Demo 4 | U/G | M3 | B |
| FR-GATE-2 | `prop_gate_totality`, `prop_gate_symmetry` | P | M3 (h20) | B |
| FR-GATE-3 | `test_conflict_grouping_c17`, `e2e_conflict_card_contents` † | U/E | M3 / M4 | B, C |
| FR-GATE-4 | `prop_never_average`, `test_duplicate_ts_not_averaged`, `test_check_no_mean_flags_pandas_paths` † | P/U | M0 (checker) / M3 | B, A |
| FR-GATE-5 | `golden-randseed` (all goldens under `PYTHONHASHSEED=random`), `test_comparison_stores_config_hash` †, `test_replay_identical_with_different_clock` | G/U | M3 | D, B |
| FR-TRUST-1 | `test_neutral_prior_beta11` † | U | M3 | B |
| FR-TRUST-2 | `test_undeclared_provenance_no_corroboration`, golden Demo 5 | U/G | M3 | B |
| FR-TRUST-3 | `test_held_claims_never_pair`, `test_low_confidence_claim_never_pairs`, `test_envelope_drift_opens_review`, `test_decimal_drop_69_goes_to_review`, `prop_held_never_pairs` †, goldens Demo 2/6 | U/P/G | M3 | B, A |
| FR-TRUST-4 | `test_c17_confidence_computed`, `test_confidence_components_stored` † | U | M3 | B |
| FR-TRUST-5 | `test_ui_uncalibrated_label`; P1: `test_calibration_fit_id_recorded` †, `test_ece_after_calibration_holdout` † (P1-05) | E/Ev | M4 / P1 | C, B |
| FR-EVID-1 | `test_all_pointers_re_resolve`, `test_claim_model_required_fields` † | U/I | M1 / M3 | B, D |
| FR-EVID-2 | `test_inferred_requires_derived_from_and_rule_id` † (validator) | U | M1 | B |
| FR-EVID-3 | `test_trigger_aborts_update`, `test_no_update_paths_status_derived`, `test_chain_verify_detects_edit`, `test_manifest_covers_review_events`; P2: `test_app_role_cannot_disable_trigger_or_truncate` | I | M1 / M3 / P2 | D |
| FR-EVID-4 | `test_failed_build_same_key_can_retry`, `test_blob_put_existing_hash_is_noop_windows`, `test_smoke_rejects_network_fs_for_db`; P2: `test_migrated_chain_verifies`, `test_locked_object_delete_denied` | I | M0 / M1 / P2 | D, A |
| FR-UI-1 | `e2e_story_five_steps` †, `test_views_precomputed_in_snapshot` † (state/story/timeline/review) | E/I | M4 / M3 | C, D |
| FR-UI-2 | `e2e_proof_under_1s`, `test_recheck_re_derives_value`, `test_page_png_cache_miss_404_not_render`, `e2e_image_proof_bbox_outlined` †, `e2e_table_proof_scrolls_to_cell` †, `e2e_sensor_chart_band_and_window` † | E/I | M3 / M4 | C, D, A |
| FR-UI-3 | `e2e_timeline_all_kinds_one_axis` † (valid + observed + UnknownTime chip) | E | M4 | C |
| FR-UI-4 | `test_spoofed_reviewer_field_422`, `test_viewer_decision_403`, `test_supersede_requires_senior`, `test_choice_validated_against_item`, `test_reason_min_15_chars_422` †, `test_explain_never_changes_outcome`, `test_auto_escalate_after_one_working_day`, `e2e_decision_card_under_2s` | I/E | M3 / M4 | D, B, C |
| FR-UI-5 | `e2e_expert_view_filters` † (modality, extracted/inferred, outcome) | E | M4 | C |
| FR-UI-6 (P1) | MVP: `e2e_eval_page_renders_report` † (minimal page); P1-08: `e2e_eval_dashboard_reliability_diagram` † | E | M5 / P1 | C |
| FR-UI-7 (P1) | MVP: `e2e_build_status_polls_1s` †; P1-01: `test_sse_notice_on_new_version` †, `test_sse_fallback_to_polling` † | E/I | M4 / P1 | C, D |
| FR-UI-8 | `e2e_verify_replay_green` †, `test_integrity_verifies_stored_bytes`, `test_snapshot_hash_mismatch`, `e2e_all_panels_same_version`, `test_manifest_root_matches_anchor` † | E/I | M4 / M6 | C, D |
| FR-LOOP-1 | `test_decision_audit_trail_who_what_why` †, `e2e_decision_card_under_2s`, `test_20_parallel_decisions_one_wins` | I/E | M4 | D, C |
| FR-LOOP-2 | `test_injector_seeded_reproducible`, `test_dev_holdout_machines_disjoint`, `test_baseline_output_generated`, `test_eval_report_has_pushed_config_commit`, `test_label_kit_roundtrip` † (D-12), §7 eval suite | Ev | M3 / M5 / M6 | D |

### 2.2 Non-functional requirements
| NFR | Named test(s) | Level | First passes at | Owner |
|---|---|---|---|---|
| NFR-1 | `test_all_pointers_re_resolve` (100% of claims in every demo version) | I | M3 | D |
| NFR-2 | `test_recheck_re_derives_value`, `e2e_byte_flip_evidence_changed`, `test_integrity_verifies_stored_bytes`; P2: `test_integrity_job_alerts_on_tamper` | I/E | M3 / M4 / P2 | D, C |
| NFR-3 | `test_trigger_aborts_update`, `test_no_update_paths_status_derived`; P2: `test_app_role_cannot_disable_trigger_or_truncate`, `test_locked_object_delete_denied` | I | M1 / P2 | D |
| NFR-4 | `golden-randseed`, `test_replay_identical_with_different_clock`, `test_replay_cache_miss_is_error`, `test_native_replay_verify_equals_image` † (D-11), `test_image_digest_equal_two_laptops` † (D-11); P1-09: cross-machine determinism job; P2: `test_upgrade_n_minus_1_chain_verifies` | G/I/Img | M3 / M6 / P1 / P2 | D, A |
| NFR-5 | `test_every_comparison_has_six_check_record` †, `test_confidence_components_stored` † | U | M3 | B |
| NFR-6 | `prop_never_average`, `test_duplicate_ts_not_averaged`, `test_split_preserves_duplicate_rows`, `test_check_no_mean_flags_pandas_paths` † | P/U | M3 | B, A |
| NFR-7 | §5.1 suite: `test_build_demo_all_under_60s_image`, `test_proof_evidence_p95_under_400ms_cold_lru`, `test_decision_rerun_p95_under_1500ms`, `test_versioned_read_p95_under_50ms_warm`, `test_recheck_under_300ms`, `test_decisions_on_two_cases_parallel_no_locked_error`, `test_decision_during_build_other_case_p95_under_2s`, `test_proof_p95_under_1s_during_decision`, `e2e_proof_under_1s`, `e2e_decision_card_under_2s` | Pf/E | M3 (build) / M4 (all) | D, C |
| NFR-8 | P2-10 k6: `load_versioned_read_p95_under_300ms` †, `load_proof_p95_under_1s` †, `load_build_40x30d_under_2min` †, `test_versioned_read_serves_precompressed_etag_per_encoding` | Pf | P2 | D |
| NFR-9 | `test_exif6_bbox_alignment_and_no_gps`, `test_logs_contain_no_document_text`, `test_no_secret_in_logs_or_responses`, `test_seed_contains_no_real_pii` †; P1: `test_redactor_never_redacts_numbers_units` †; P2: `test_bucket_lock_mode_matches_policy`, `test_oidc_principal_is_iss_sub_pair` | S/U | M5 / P1 / P2 | A, D |
| NFR-10 | `e2e_proof_within_two_clicks` † | E | M4 | C |
| NFR-11 | `e2e_badges_have_text_labels` † (every outcome badge has a text node; no colour-only state) | E | M4 | C |
| NFR-12 | `test_ui_uncalibrated_label` (API field and UI badge) | I/E | M4 | B, C |

### 2.3 Deliverables
| D | Evidence (tests) | First passes at | Owner |
|---|---|---|---|
| D1 Engine for text/image/table/time series | FR-ING-1..4 rows; goldens Demo 0, 3, 6 | M3 | A, B |
| D2 Unified state schema | `test_views_precomputed_in_snapshot` †, `test_state_view_schema_matches_contract` † (against `schemas/*.json`), `contracts-check` | M1 / M3 | B, D |
| D3 ClaimRecord extracted vs inferred | `test_inferred_requires_derived_from_and_rule_id` †, `test_sensor_native_has_no_normalized_fields` † | M1 | B |
| D4 Evidence pointers for all modalities | `test_all_pointers_re_resolve`, `e2e_proof_under_1s` parametrised over [text, txt, image, table, sensor] | M3 / M4 | D, C |
| D5 Entity linking, timeline, conflicts | FR-NORM-2/3 and FR-GATE rows; goldens Demo 0, 2, 4, 5b | M3 | B |
| D6 Confidence + accuracy/calibration eval | §7 suite; `test_ui_uncalibrated_label`; holdout report fields check `test_eval_report_required_fields` † | M5 / M6 | D, B |
| D7 Interface | §2.1 FR-UI rows; the 5 binding e2e specs | M4 | C |
| D8 Demonstrations | All 9 goldens; `make demo`; Playwright specs; pre-demo checklist §10 | M3 / M6 | D, C |

### 2.4 Threat register T-01..T-40, N-1..N-4
| ID | Named test(s) | Level | First passes at | Owner |
|---|---|---|---|---|
| T-01 | `test_quiet_day_false_alarm_rate_dev`; `test_false_alarm_eval_day_not_in_calibration_set`; `test_quiet_day_false_alarm_rate_holdout` (h31 only) | Ev | M3 / M3 / M6 | B / D / D |
| T-02 | `test_check4_rejects_statistic_or_granularity_mismatch` | U | M3 | B |
| T-03 | `test_spike_in_gap_never_agree`, `prop_deleting_readings_never_toward_agree` | U/P | M3 (h20) | B |
| T-04 | `test_envelope_refuses_without_log_coverage`, `test_planted_hot_days_bounded_shift`, `test_case_window_excluded`, `test_quiet_day_requires_coverage_d_pm3`, `test_envelope_drift_opens_review` | U | M3 | B (A) |
| T-05 | `test_gauge_vs_telemetry_cannot_compare`, `test_no_mm_s_in_api_or_ui` (scans every API response of every demo version **and** the built `dist/`) | U/I | M3 | B |
| T-06 | `test_white_text_pdf_zero_claims_one_review`, `test_partial_hidden_span_held`, `test_covered_text_held`, `test_hostile_corpus[hidden_negation]`, `test_visibility_fallback_labelled_lower_assurance` † | U/S | M3 | A |
| T-07 | `test_llm_mutations_zero_accepted` (replay gates CI; record runs too) | U | P1 | A |
| T-08 | `test_injection_fixture_no_outcome_change` | U | P1 | A |
| T-09 | `test_decimal_drop_69_goes_to_review`; P1 `test_ocr_vlm_disagreement_held` † | U | M3 / P1 | A |
| T-10 | `test_transposed_digits_never_autolink`, `test_serial_conflict_vetoes` | U | M3 | B |
| T-11 | `test_local_day_boundary_2330` | U | M3 | B |
| T-12 | `test_undated_note_time_unknown`, `test_unknown_time_has_no_bounds` | U | M1 / M3 | B |
| T-13 | `test_frozen_sensor_flatline`, `test_stop_event_not_gap`, `test_flatline_degenerate_scale_abs_eps` | U | M3 | B |
| T-14 | `test_duplicate_ts_not_averaged`, `test_split_preserves_duplicate_rows` | U | M3 | B |
| T-15 | `test_undeclared_provenance_no_corroboration` | U | M3 | B |
| T-16 | `test_hostile_corpus[bomb_png]` (→ `failed_resource`), `test_hostile_corpus[png_60mpx_rejected]`, `test_pdf_huge_mediabox_render_refused`; P1 `test_xlsx_zip_caps` † | S | M3 / M5 / P1 | A |
| T-17 | `test_300mb_rejected_streaming`, `test_chunked_upload_without_length_capped` | S | M3 | A |
| T-18 | `test_hostile_corpus[html_as_pdf, svg, pdf_renamed_csv, html_renamed_txt]`, `test_original_download_headers` | S | M3 / M4 | A, C |
| T-19 | `test_hostile_corpus[traversal_name]`, `test_id_regex_rejects_path_chars` † | S | M3 | A |
| T-20 | `test_api_never_imports_pdfium`, `test_hostile_corpus[pdf_51_pages]`; P1 `fuzz_mutated_pdf_smoke` | S | M3 / P1 | A |
| T-21 | `test_exif6_bbox_alignment_and_no_gps` | U | M3 | A |
| T-22 | `e2e_xss_fixture_no_dialog_under_csp` (incl. `<img src=x>` channel name in a tooltip), `test_safe_formatter_encodes_html` † (vitest) | E | M4 | C |
| T-23 | `test_spoofed_reviewer_field_422`, `test_viewer_decision_403` | I | M3 | D |
| T-24 | `test_20_parallel_decisions_one_wins` (SQLite); P2 the same test on `[pg]` plus `test_two_worker_build_race_pg` † | I | M4 / P2 | D |
| T-25 | `test_cross_case_claim_404`, `test_authz_matrix` † | I | M3 | D |
| T-26 | `test_cross_origin_form_post_403`, `test_login_requires_csrf_header` | S | M4 | A |
| T-27 | `test_trigger_aborts_update`, `test_chain_verify_detects_edit`, `test_snapshot_hash_mismatch`, `e2e_byte_flip_evidence_changed` | I/E | M1 / M3 / M4 | D, C |
| T-28 | `test_kill_mid_build_marks_stale_then_rebuilds`, `test_parent_restart_kills_orphan_child`, `test_child_oom_marks_failed_not_running` | I | M3 | A |
| T-29 | `e2e_all_panels_same_version`, `test_versioned_cache_headers_private_immutable`, `test_latest_no_store` | E/I | M3 / M4 | C, D |
| T-30 | `test_no_magic_literals_in_engine` | U | M3 | D |
| T-31 | `test_eval_report_has_pushed_config_commit` (config + engine + lock), `test_holdout_requires_clean_tree` †, `test_report_superseded_on_engine_change` † | Ev | M5 (dry run) / M6 | D |
| T-32 | `test_ui_uncalibrated_label` | I/E | M4 | B, C |
| T-33 | `test_network_off_build_succeeds`; P1 `test_groq_outage_build_completes_rules_only_under_60s`, `test_groq_429_honours_retry_after`, `test_budget_reservation_atomic_two_builds` | Img/I | M5 / P1 | D / A |
| T-34 | `test_parallel_eval_runs_one_proceeds`; P1 `test_eval_run_rate_limited` †; P2 the same test with 2 workers | I | M5 / P1 / P2 | D |
| T-35 | **No test** (accepted risk, P5). The partial MVP control (case-scoped repository) is covered by `test_cross_case_claim_404` and `test_authz_matrix` | — | P5 | — |
| T-36 | P2 `test_bucket_lock_mode_matches_policy`; P3 erasure-runbook drill `drill_erasure_request_documented` † | Img/drill | P2 / P3 | D |
| T-37 | `test_lockfiles_in_sync`, `make audit` (M5, recorded), image scan (trivy); P1 CI pip-audit + SBOM; P2 `test_deploy_refuses_unsigned_image` † | S/Img | M0 / M5 / P1 / P2 | A, D |
| T-38 | `test_client_timestamp_ignored` | U | M3 | B |
| T-39 | `test_no_secret_in_logs_or_responses`, `test_dockerignore_excludes_secrets`, `test_parse_child_env_has_no_groq_key`, `test_image_has_no_secrets` † (the D-11 grep, automated), gitleaks pre-commit; P1-11 gitleaks CI | S/Img | M0 / M3 / M5 / M6 | A, D |
| T-40 | `test_groq_disabled_by_default_no_egress`, `test_network_off_build_succeeds`; P1 `test_groq_base_url_must_be_allowlisted_https`, `test_unknown_model_fails_closed`, `test_egress_requires_ack_and_case_flag` †; P2 `test_egress_denied_except_allowlist` | S | M0 / P1 / P2 | A, D |
| N-1 | `test_no_update_paths_status_derived` | I | M1 | D |
| N-2 | `test_anchor_pushed_to_remote` † (`git ls-remote` contains the commit of `anchors/demo_roots.txt`; run by the pre-demo checklist), `test_manifest_root_matches_anchor` † | Img | M6 (h35) | D |
| N-3 | `test_thin_history_uses_model_pool`, `test_conformal_oracle` | U | M3 | B |
| N-4 | `test_baseline_output_generated` (and the output text pinned in golden Demo 0) | Ev/G | M5 | D |

### 2.5 Security floor S1–S11 (ADR-15)
| S | Named test(s) | First passes at | Owner |
|---|---|---|---|
| S1 sessions, identity from session, 127.0.0.1 | `test_spoofed_reviewer_field_422`, `test_compose_ports_loopback_only`, `test_lan_without_tls_refuses_start`, `test_login_unknown_user_constant_work`, `test_login_concurrency_bounded`, `test_session_rotated_on_login`, `test_session_token_stored_hashed`, `test_session_absolute_expiry`, `test_login_lockout_5_in_5min`; P1 `test_per_ip_login_throttle` † | M0 / M4 / P1 | A |
| S2 SameSite, CSRF, JSON | `test_write_requires_json_and_csrf`, `test_login_requires_csrf_header`, `test_cross_origin_form_post_403`, `test_foreign_host_header_400`, `test_cookie_samesite_strict_httponly` † | M4 | A |
| S3 precise 409s, senior supersede | `test_20_parallel_decisions_one_wins`, `test_supersede_requires_senior`, `test_stale_base_version_untouched_item_accepted`, `test_decision_already_decided_409` †, `test_decision_evidence_changed_409` †, `test_build_conflict_409_retry_after` | M3 / M4 | D |
| S4 killable child, sweep, one build per case | `test_timeout_kills_tesseract_grandchild`, `test_parent_restart_kills_orphan_child`, `test_kill_mid_build_marks_stale_then_rebuilds`, `test_build_key_idempotent`, `test_build_child_under_rlimit_builds_demo0`; P1-12 `test_windows_job_object_kills_on_close` † | M3 / P1 | A |
| S5 triggers, chain, snapshot hash, anchor | `test_trigger_aborts_update`, `test_integrity_verifies_stored_bytes`, `test_chain_verify_detects_edit`, `test_anchor_pushed_to_remote` † | M1 / M3 / M6 | D |
| S6 upload caps, allowlist, pixel cap, page cap, free disk | `test_300mb_rejected_streaming`, `test_chunked_upload_without_length_capped`, `test_hostile_corpus[*]`, `test_upload_refused_when_disk_below_1gb`, `test_upload_requires_ingestor_role` † | M3 | A |
| S7 originals as attachment | `test_original_download_headers` (5 headers; hostile filename never echoed) | M4 | C (A) |
| S8 no-danger, strict CSP | `test_html_responses_have_csp_header_with_frame_ancestors`, `e2e_xss_fixture_no_dialog_under_csp`, `e2e_no_csp_violations` †, `test_eslint_bans_danger_and_string_formatter` † | M0 (spike) / M4 | C |
| S9 central authorise | `test_cross_case_claim_404`, `test_authz_matrix` †, `test_every_route_uses_resolve_case_and_authorize` † (route introspection) | M3 | D |
| S10 no doc text in logs, no network | `test_logs_contain_no_document_text`, `test_groq_disabled_by_default_no_egress`, `test_network_off_build_succeeds` | M0 / M5 | A, D |
| S11 non-root, read-only rootfs | `test_image_nonroot_readonly` | M6 (D-11; dry run at M5) | D |

---

## 3. Golden demo tests

### 3.1 Mechanics
- `tests/golden/test_golden.py::test_golden[demo_X]` builds the demo case **in-process**. It uses the real core, `DictExtractionCache` in replay mode against `seed/cache/`, the real SQLite store in a temp dir and `FixedClock`. Then it compares the canonical JSON against `expected.json`.
- **What is pinned in every golden:**
  - the outcome and reason string of each pinned comparison;
  - the 6-row check table (`pass`/`fail` and the reason per check), in `expected_checks.json`;
  - the computed values listed per demo;
  - claim, comparison, conflict, review and envelope IDs;
  - `records_root` (the sorted record hashes over the 7 tables);
  - `manifest_hash`.
- **Open issue: `manifest_hash` vs `engine_sha`.** The manifest carries `engine_sha` and `lockfile_hash` (§C.1), so every commit would change `manifest_hash`. In the golden harness, both fields are set to the fixed string `"golden"` (`TRACE_GOLDEN_MODE=1`), and that **golden-mode manifest_hash** is what gets pinned. The real `manifest_hash` is pinned once, at `mvp-freeze`, by `test_manifest_root_matches_anchor` †. **B and D must confirm this before h16**, which is the first bless.
- **Determinism.** Every golden also runs under `make golden-randseed` (`PYTHONHASHSEED=random`, 3 runs), and natively through `replay-verify` at D-11.
- **No typed literals.** Expected values come only from blessed engine output. `test_no_magic_literals_in_engine` greps the engine and config for 64, 0.71, 0.22, 0.62 and the computed band ends. The PRD worked-example check (C-17 = 0.95 × 0.97 × 0.90 × 1.0 × 1.0 × 1.0 → 0.83) is an **oracle assertion** in `test_c17_confidence_computed`, not a golden literal.

### 3.2 Demo goldens
| Demo | Inputs | Expected outcome | Pinned |
|---|---|---|---|
| **0** Headline | `report_0314.pdf` p1 l4 (C-17); M-21 partition (W-0314 → S-88, S-88.1); `PdM_errors` rows 812 and 815; gauge photo 6.9 bar; nameplate | **They disagree.** One ConflictRecord grouping C-17's pairs; all 6 checks pass; error rows attached as context; no averaged value anywhere; "Machine 21", "M-21" and the serial linked to one entity | T_D, T\*, n, pooled flag, `envelope_id`, S-88.1 peak value and its hour `[14:00,15:00)`, band `med±T*·s` per channel, S-88 confidence (1−p × coverage × history), C-17 confidence 0.83 with its components, conflict ID, baseline answer text/score (N-4), golden-mode manifest_hash. h0 decision from `case.yaml` (real / alternative / planted + badge) |
| **1a** Partial gap | Demo 0 with telemetry hours `[02:00,06:00)` removed | Two sub-cases. (i) The violation lies in the available hours → **They disagree**. (ii) A variant where the violating hours fall inside the gap → **We can't tell (partial: 4 h missing)**. **Never "agree"** in either | GapClaim(missing) `[02:00,06:00)`, coverage 20/24, check 5 = pass, check 6 reason, outcomes of both sub-cases |
| **1b** Source missing | All M-21 vibration on 14 Mar removed, and a variant with the telemetry source dropped; a third variant drops the report | **We can't tell (data missing)**, with check 5 failing. With the report dropped, S-88 stands alone and no comparison exists | Whole-day GapClaim, check table, story text "sensor data for that day is missing", zero ConflictRecords |
| **2** Entity ambiguity (held) | Paper-form photo with "Press 21" | `ambiguous_entity` review item; ranked M-21 > M-12 with **computed** scores and per-feature reasons; check 1 fails ("can't be compared yet"). A second stage applies the decision fixture (`reviewer1`, reason ≥ 15 chars, choice M-21) → v+1 re-run, the card updates | Candidate scores and reasons, auto-link refusal reasons (τ_link, δ_link, non-string feature), `review_id`, `decision_id`, v and v+1 outcomes, parent manifest link |
| **3** Units | Gauge 6.9 bar, repair log 100 psi, "pressure 7.2" with no unit, telemetry pressure; plus the unit-swap fault variant | 6.9 bar ↔ 100 psi: **They agree** (≈ 690 kPa vs ≈ 689.5 kPa, within tolerance). Gauge ↔ telemetry: **can't be compared (telemetry unit undocumented)**. 7.2 ↔ others: **can't be compared (unknown unit)**. Swap variant: **They disagree** | `normalized_value` (6 dp) of each claim, the tolerance used, `unit_status`, all reason strings |
| **4** False-conflict guard | (a) report says "ran normally on 10 March"; (b) report about M-22 | **They can't be compared**: check 3 fails in (a), check 1 fails in (b). **Zero** ConflictRecords | Check tables, the reason for the first failed check, conflict count = 0 |
| **5** Independence | Auto-generated summary derived from telemetry ("vibration elevated") with declared `derived_from_sources` | No corroboration credit; S-88 confidence **equal** to the Demo 0 value; provenance edge present | `corroboration` component = 0, S-88 confidence equals Demo 0's (asserted by cross-golden equality), the edge in the independence graph |
| **5b** Late timestamp | Note observed 15 Mar 09:10, valid 14 Mar; fault variant shifts valid date to 13 Mar | Base: compared against the 14 Mar window (outcome as Demo 0). Variant: **can't be compared** (check 3) | `valid_time`, `observed_time`, `granularity`, check 3 result for both |
| **6** Reader disagreement (held) | Gauge photo whose OCR reads "69"; declared range 0–16 bar | `implausible_value` review item; the claim takes part in no comparison; the re-read is labelled "consistency check" | Review item, OCR value, re-read value, `held_reason`, comparisons including that claim = 0. The P1 VLM variant (6.9 vs 8.9 → `reader_disagreement`) is added in P1-04 |

### 3.3 Golden update procedure
1. **Who may regenerate.** Only by running `make golden-bless CONFIRM=1`. The target refuses unless `test_conformal_oracle` and every property test are green, and it prints the full diff. **B** blesses engine-driven changes and **D** blesses seed or data changes. The other one reviews.
2. **Review rule.** A bless PR must contain:
   - the printed diff;
   - one sentence per changed value saying *why*;
   - for any outcome change, a reference to the requirement or threat ID that justifies it.

   A non-author approves it (D for B, B for D). An outcome change on Demo 0, 1a or 1b also needs A's sign-off, because these are the floor demos.
3. **Never** hand-edit `expected.json`. `test_golden_files_bless_stamp` † checks the `blessed_by`, `oracle_sha` and `engine_sha` stamp in each file.
4. **After `mvp-freeze` (h30)** a golden may be re-blessed only to fix a Sev-1 defect, with A+B+D approval. The holdout report is then marked "superseded" (T-31), and the slides are regenerated from the new goldens.
5. The slides and talk track take their numbers from `golden/*/expected.json` (h32), never the other way round.

---

## 4. Property tests (Hypothesis)

Strategies in `properties/strategies.py` generate:
- claims (all modalities, `Interval | UnknownTime`, all unit statuses);
- sensor windows with arbitrary missing hours, duplicates and flatlines;
- envelopes, including pooled and degenerate ones;
- event logs with arbitrary coverage periods.

Every failure found is added back as an `@example` regression.

| # | Name | Invariant (exact statement) | Owner / due |
|---|---|---|---|
| 1 | `prop_gate_totality` | For every pair (a, b) of eligible claims, `gate(a,b)` returns exactly one outcome in {disagree, agree, cannot_compare, cannot_tell}, with a non-empty reason, never raises, and records checks 1..k **in order**. Here k is the first failing check, or 6 if none fails. | B, h20 |
| 2 | `prop_gate_symmetry` | `gate(a,b).outcome == gate(b,a).outcome`, and the check pass/fail vectors are equal. | B, h20 |
| 3 | `prop_never_average` | For any set of claims with conflicting values (including duplicate timestamps), no output claim, statistic or projection holds a value equal to an arithmetic mean of ≥ 2 distinct conflicting parent values unless that value also occurs in a parent. Every `ComparisonRecord.averaged` is `False`. | B, h20 |
| 4 | `prop_deleting_readings_never_toward_agree` | Order the outcomes agree > cannot_tell > disagree/cannot_compare by "toward agree". For any window W and any subset W' ⊂ W formed by deleting readings, `rank(outcome(W')) ≤ rank(outcome(W))` toward agree, i.e. deletion never turns non-agree into agree. For a ∀ claim, coverage < 100% ⇒ outcome ≠ agree. | B, h20 |
| 5 | `prop_held_never_pairs` † | For any claim set and review state, no ComparisonRecord references a claim in `held`. Post-gate `score` never changes the `held` set. | B, M3 |
| 6 | `prop_unit_roundtrip` | For known units u, v of the same dimension and finite x: `convert(convert(x,u→v), v→u) == x` within 1e-9 relative error. A claim with `unit_status ∈ {unknown, sensor_native}` never gets a `normalized_value`. | B, B-11 |
| 7 | `prop_overlap_commutative` | `overlap(I,J) == overlap(J,I)`. `[a,b)` and `[b,c)` never overlap. `UnknownTime` overlaps nothing. | B, B-11 |
| 8 | `prop_half_open_days_partition` † | For any plant_tz instant t, exactly one local day `[D 00:00, D+1 00:00)` contains t. Days are disjoint and contiguous across DST (pilot zones). | B, M3 |
| 9 | `prop_chain_detects_any_edit` | Flipping any single byte of any stored record body, or deleting, reordering or inserting a record in any version, makes the chain check fail at that version and at every descendant. | D, B-11 |
| 10 | `prop_canonical_deterministic` | For nested models with floats, `JCS(x)` is identical across runs and hash seeds. `-0.0` and `0.0` give the same bytes. NaN/Inf raise. `canonical(parse(canonical(x))) == canonical(x)`. Values are quantised to 6 dp with ROUND_HALF_EVEN. | B, M1 |
| 11 | `prop_ids_content_addressed` † | Permuting input record order, or changing wall-clock fields, never changes any `clm_/cmp_/cf_/rv_/env_` ID. Changing any semantic field always changes it. | B, M1 |
| 12 | `prop_conformal_bound` † | For any n ≥ 19 and any multiset {T_d}, `T* = T_(⌈0.95(n+1)⌉)`. On exchangeable synthetic quiet days, the empirical false-alarm rate over 10⁴ trials is ≤ 0.05 + 3σ. For n < 19, `pooled ≠ none`. | B, M3 |
| 13 | `prop_quote_offset_map` † | For any page text containing surrogate pairs, CRLF, generated breaks and NFC-variant sequences, mapping a match in the normalised view back through the offset map gives `quote == page_text[s:e]` exactly. | A, M3 |
| 14 | `prop_explain_never_changes_outcome` † | For any version and any `ExplainChoice` decision, the outcomes and ConflictRecords of v+1 equal v's. Only badges and events differ. | B, M4 |
| 15 | `prop_status_derived_monotone` † | `derive_review_status` is a pure function of (items, events, clock, calendar). Appending events never deletes earlier events. `escalated` appears iff the item is undecided and more than 1 working day has passed since `opened_at`. | B, M4 |
| 16 | `prop_hidden_char_holds_span` † | For a generated PDF span where any non-whitespace char is made invisible (white fill, mode 3, alpha 0, < 4 pt, outside the CropBox), the span produces 0 claims and 1 `hidden_text` review item. | A, M3 (`slow`; 50 examples) |

**Profiles:**
- `precommit` uses `derandomize=True`, so pre-commit runs never flake.
- `nightly` uses 10,000 examples, with the example database shared through the repo cache.

A property failure is **Sev-1** if it is one of #1–5 or #9, and Sev-2 otherwise.

---

## 5. Performance tests

### 5.1 NFR-7 (MVP)
| Test | Budget | How measured |
|---|---|---|
| `test_build_demo_all_under_60s_image` | each demo case < 60 s | Wall time on `time.monotonic()` from `POST /build` → 202 until `GET /builds/{bid}` = `done`, polled every 100 ms. Runs in the image with `--memory 3g --pids-limit 256 --read-only`, in **record** mode with a cold extraction cache (worst case) **and** in replay mode. The gate uses record mode. Per-stage ms (`spawn_import_ms`, read, render, gate, snapshot) come from build status. |
| `test_render_stage_ms_recorded` | 50-page PDF render < 6 s | Stage timer in the child |
| `test_proof_evidence_p95_under_400ms_cold_lru` | p95 < 400 ms | 20 iterations; the LRU is cleared before each run; `GET …/evidence` + `page.png` + `POST recheck`, timed client-side in-process with httpx |
| `test_versioned_read_p95_under_50ms_warm` | p95 < 50 ms | 100 warm reads across views |
| `test_recheck_under_300ms` | max < 300 ms | Largest demo source (25 MB-class PDF), 10 runs, 10 s coalescing defeated by unique claims |
| `test_decision_rerun_p95_under_1500ms` | p95 < 1.5 s | 20 decisions on fresh review items; request → 200 with the new version |
| `test_decisions_on_two_cases_parallel_no_locked_error` | 0 × `database is locked` | 2 threads × 20 decisions on different cases |
| `test_decision_during_build_other_case_p95_under_2s` | p95 < 2 s | A build of case A runs while 20 decisions run on case B |
| `test_proof_p95_under_1s_during_decision` | p95 < 1 s | Proof loop while decisions run |
| `e2e_proof_under_1s` | median of 5 < 1 s | Playwright: click "Show me the proof" → overlay rect visible and PNG `complete` (performance marks in the island) |
| `e2e_decision_card_under_2s` | median of 5 < 2 s | Playwright: submit decision → card shows the new version badge |

**Where they run.** The suite runs on the **image (Docker Desktop/WSL2) and natively on Windows** (replay mode, no RLIMIT, Defender state recorded) at the M3 exit (build budget only), the M4 exit (all budgets) and D-11. Both platforms must pass the budgets.

**Report.** `data/perf_report.json` records:
- the CPU, RAM and disk of the reference laptop;
- the OS build;
- the Docker Desktop version;
- whether Defender real-time scanning is on;
- p50, p95 and max for every test.

A budget miss on native only (with the image green) is Sev-3, unless native is the declared demo fallback for that laptop, in which case it is Sev-2.

### 5.2 Perf-test flake controls
- Warm-up runs are discarded (2 per test).
- The tests run serially, with no xdist.
- Other containers are stopped.
- A test fails only if the budget is missed on 2 consecutive runs. The first miss is recorded in the report.

### 5.3 NFR-8 pilot load test (P2-10, k6)
- **Environment.** Staging VM with the production spec: 8 vCPU / 32 GB, the pilot compose (PG16, MinIO, Caddy TLS), and seeded data for 40 machines × 1 year, 20 cases, 200 versions.
- **Users.** 50 virtual users with OIDC test-tenant sessions, pre-created and cookie-injected.
- **Scenario mix (per iteration):**
  - 75% versioned view reads (state, story, timeline, claims page), half of them with `If-None-Match`;
  - 10% evidence + `page.png`;
  - 5% recheck;
  - 5% `latest` redirect;
  - 3% decisions (on dedicated review items);
  - 2% build trigger.
- **Shape.** Ramp 0 → 50 over 5 min, then 30 min steady, then a 10 min spike to 100. A weekly 4 h soak runs at 25 users.
- **Thresholds** (`ops/loadtest/k6/thresholds.js`):
  - `load_versioned_read_p95_under_300ms` †: `http_req_duration{kind:read}` p(95) < 300;
  - `load_proof_p95_under_1s` †: p(95) < 1000;
  - errors < 0.1%;
  - 0 × 5xx;
  - `load_build_40x30d_under_2min` †: a 40-machine × 30-day build < 120 s while under load.
- **Also reported:** the LRU hit rate, and the ETag 304 share from `/metrics`.
- **Out of scope.** "About 1M concurrent readers" (NFR-8) is a P5 CDN claim. It is **not tested** in the pilot, and the report says so.

---

## 6. Security tests

### 6.1 Hostile corpus (`test_hostile_corpus[...]`, 13 files + 1 stream)
| File | Expected |
|---|---|
| `bomb_png` (header 20k × 20k) | Child → `failed_resource`, or held; the API stays alive (`/healthz` 200 during and after) |
| `png_60mpx_rejected` | Rejected by the header check before `load()`; not a warning |
| `html_as_pdf` | 415 `/problems/unsupported-media` (magic mismatch) |
| `svg` (with `<script>`) | 415; no SVG accepted |
| `traversal_name` (`../../app.py.pdf`) | Stored by hash only; the filename is never used in a path or header |
| `pdf_renamed_csv` | 415 (`%PDF` prefix banned for text types) |
| `html_renamed_txt` | 415 |
| `pdf_51_pages` | Upload 201; build holds the source `pdf-page-cap`; no PDFium in the API |
| `hidden_negation.pdf` | 0 claims from the span, 1 `hidden_text` review item |
| `huge_mediabox.pdf` | Render refused (> 40 M px); held |
| `white_text.pdf` | 0 claims, 1 review item |
| `exif6_gps.jpg` | Box aligned in `oriented_px`; the derived image has no GPS tag |
| `xss_text.pdf` (text `<img src=x onerror=…>`, channel name in CSV) | Stored as text; rendered only as text nodes (e2e) |
| *stream* `300mb` (generated) | 413 before or at cap + 64 KiB read; no temp file > cap (`test_300mb_rejected_streaming`) |

The 7 "original" files are listed as the Tester's reading of HARDENING (bomb_png, html_as_pdf, svg, traversal_name, white_text, exif6_gps, xss_text). **A must confirm this list before M3.**

### 6.2 Authorisation matrix (`test_authz_matrix` †, parametrised)
Rows are the routes in §C.4 and columns are the roles anonymous, viewer, reviewer, senior, ingestor and evaluator. The expected codes are:

| Route class | anon | viewer | reviewer | senior | ingestor | evaluator |
|---|---|---|---|---|---|---|
| `GET` versions/claims/evidence/latest/builds | 401 | 200 | 200 | 200 | 200 | 200 |
| `POST /cases`, `POST …/sources`, `POST …/build` | 401 | 403 | 403 | 403 | 2xx | 403 |
| `POST …/review/{rid}/decision` | 401 | 403 | 200 | 200 | 403 | 403 |
| decision with `supersedes` | 401 | 403 | 403 | 200 | 403 | 403 |
| `POST …/recheck` | 401 | 200 | 200 | 200 | 200 | 200 |
| `POST …/replay`, `POST /eval/run`, `GET /eval/report` | 401 | 403 | 403 | 403 | 403 | 200 |

Every cell is also run with a **foreign case ID**. The result must be 404 (never 403), so case existence does not leak (T-25). Every row is also run with a claim ID from case B under case A's path. `test_every_route_uses_resolve_case_and_authorize` † fails if a new route is not in the matrix.

### 6.3 CSRF, origin and session
- **Named tests:**
  - `test_write_requires_json_and_csrf`: form-encoded body → 415, and a missing `X-CSRF-Token` → 403, on every write, login included.
  - `test_cross_origin_form_post_403`: `Origin: https://evil.example` or `Sec-Fetch-Site: cross-site` → 403.
  - `test_foreign_host_header_400`
  - `test_session_rotated_on_login`
  - `test_session_token_stored_hashed`: the DB row ≠ the cookie value.
  - `test_session_absolute_expiry`: 12 h on FixedClock.
  - `test_login_lockout_5_in_5min`
  - `test_login_unknown_user_constant_work`: the median verify time for unknown and known users differs by < 20% over 30 tries, and the dummy-hash call is asserted through a spy.
  - `test_login_concurrency_bounded`: 20 concurrent logins → never more than 4 verifies in flight.
- **Cookie flags.** `test_cookie_samesite_strict_httponly` † asserts `SameSite=Strict` and `HttpOnly`, plus `Secure` and the `__Host-` prefix under TLS.

### 6.4 409 races and conflicts
| Test | Asserts |
|---|---|
| `test_20_parallel_decisions_one_wins` | 20 threads decide the same item: exactly one 200 and 19 × 409 `already-decided`; one decision record; one new version |
| `test_stale_base_version_untouched_item_accepted` | A decision on an untouched item whose `base_version` is stale → 200 (compute-then-commit, re-check of the evidence hash) |
| `test_decision_evidence_changed_409` † | `shown_evidence_hash` ≠ current → 409 `evidence-changed` |
| `test_decision_already_decided_409` † | A second decision without `supersedes` → 409 |
| `test_build_conflict_409_retry_after` | A second build while one is running → 409 `build-in-progress`, `Retry-After: 5` |
| `test_parallel_eval_runs_one_proceeds` | Two `/eval/run` → one 202 and one 409 (DB single-flight) |
| `test_recheck_rate_limited` | The 31st recheck in a minute → 429 `rate-limited` |

### 6.5 Secret-leak sentinel (`test_no_secret_in_logs_or_responses`)
1. The app starts with `GROQ_API_KEY=gsk_TESTSENTINEL0123456789abcdef` and the seeded passwords.
2. Run:
   - a good login;
   - a bad login;
   - a malformed login (422 path);
   - an upload;
   - a build;
   - a forced 500 (fault-injection route enabled only in tests);
   - a recheck.
3. Capture every response body and header, plus every structlog line, the uvicorn access and error logs, and the child's stderr.
4. Assert that neither the sentinel nor any password, nor its first 8 chars, appears anywhere.

`test_logs_contain_no_document_text` builds Demo 0 and greps the logs for every seed quote longer than 12 chars. `test_image_has_no_secrets` † runs `grep -r gsk_` over the image filesystem and checks that `/app/seed/credentials.local.txt` and `*.db` are absent.

### 6.6 Egress
- `pytest-socket` is on for the whole suite, so any test that opens an INET socket fails.
- `test_groq_disabled_by_default_no_egress` also asserts that `trace_adapters.groq` and `openai` are not in `sys.modules` after app startup **and** after a build child runs.
- `test_network_off_build_succeeds` runs `make demo` inside `docker run --network none` and requires every demo to reach `done`.
- **P2:** `test_egress_denied_except_allowlist` (game day). `curl https://example.com` from the api container fails, and the anchor push, IdP and backup target succeed through Squid.

### 6.7 CSP and frontend
- `test_html_responses_have_csp_header_with_frame_ancestors` checks every HTML route for the header (not a meta tag), the exact directives, XFO DENY, `Referrer-Policy`, COOP and Permissions-Policy.
- Playwright runs **only** against the image with the enforcing header. `e2e_no_csp_violations` † records `securitypolicyviolation` events and console errors on every spec and requires zero. This proves hydration works under the CSP (R7).
- `e2e_xss_fixture_no_dialog_under_csp` asserts:
  - no `dialog` event;
  - no `<img>` element inside the tooltip or proof DOM;
  - the payload is visible as literal text.
- `test_eslint_bans_danger_and_string_formatter` † runs eslint on a fixture file and expects both rule errors.

### 6.8 Upload caps
`test_300mb_rejected_streaming` instruments `receive` to count bytes. It requires:
- bytes read ≤ 25 MiB + 64 KiB for documents (and the 200 MB-class cap for telemetry);
- a 413 before the handler runs when `Content-Length` is present;
- no file under `data/tmp` larger than the cap, both during and after.

`test_chunked_upload_without_length_capped` does the same with no `Content-Length`. `test_upload_refused_when_disk_below_1gb` uses a fake `disk_usage`.

---

## 7. Evaluation harness tests (`tests/eval`)
| Test | Asserts | Owner / first passes at |
|---|---|---|
| `test_dev_holdout_machines_disjoint` | dev ∩ holdout machines = ∅; the split is a pure function of the seed; ≥ 200 holdout quiet machine-days are available | D, M3 |
| `test_dev_suite_never_reads_holdout` † | The audit hook (§1.5) raises on any holdout path open outside `@pytest.mark.holdout` | D, M3 |
| `test_holdout_marker_excluded_from_test_and_check` † | `pytest --collect-only` under `make test` and `make check` selects 0 `holdout` tests | D, M3 |
| `test_injector_seeded_reproducible` | Same seed → byte-identical fault manifest and injected bytes; 7 fault types present | D, M3 |
| `test_false_alarm_eval_day_not_in_calibration_set` | For every evaluated quiet day d, the T\* used was computed from Q \ [d−3, d+4) (the recorded `t_star_inputs` exclude that block) | D, M3 |
| `test_quiet_day_false_alarm_rate_dev` | Dev machines, leave-block-out: Wilson 95% lower bound ≤ 5% (fails only if lower > 5%); point estimate reported | B, M3 |
| `test_quiet_day_false_alarm_rate_holdout` (`holdout`) | The same on ≥ 200 holdout machine-days, run once at h31 | D, M6 |
| `test_wilson_ci_known_values` | (0/200) → [0, 0.0188]; (10/200) → [0.0274, 0.0899]; (5/100) → [0.0215, 0.1118] (±1e-4; standard Wilson, z = 1.95996) | D, M3 (h14) |
| `test_ece_known_fixture` † | A hand-built 10-bin fixture gives the exact ECE; empty bins are excluded and their counts reported | D, M5 |
| `test_brier_known_values` † | Brier of hand fixtures (e.g. p = [1,0,0.5], y = [1,0,1] → 0.08333) | D, M5 |
| `test_bootstrap_ci_seeded_and_covers_point` † | 1,000 resamples with a fixed seed; reproducible; lower ≤ point ≤ upper; per-bin counts in the report | D, M5 |
| `test_baseline_output_generated` | TF-IDF + averaging/LWW and no-gate baselines produce outputs on the same seeds; the answer text is stored and never a literal | D, M5 |
| `test_eval_report_has_pushed_config_commit` | `config_hash`, `engine_sha` and `lockfile_hash` are each contained in a remote branch (`git branch -r --contains`) and printed | D, M6 |
| `test_holdout_requires_clean_tree` † | `make eval-holdout` exits non-zero on a dirty tree or unpushed hashes | D, M5 (dry run on dev) |
| `test_report_superseded_on_engine_change` † | When `engine_sha` at HEAD ≠ the report's, the report renders "superseded" | D, M6 |
| `test_eval_report_required_fields` † | P/R/F1 per fault, entity acc@1/@3, per-bin accuracy, ECE and Brier with CIs, bin counts, baselines, and the share of external faults or the U-2 disclosure | D, M6 |
| `test_label_kit_roundtrip` † | Export → YAML → import keeps every PRD §12.1 field; the labeller ID is recorded | D, M5 |

**Holdout protocol (one shot).**
1. At h30, tag `mvp-freeze` and push.
2. At h31, D runs `make eval-holdout` with B watching.
3. The output is archived together with the hashes.

A second run is allowed only after a Sev-1 fix, and the report then says "second look, disclosed".

---

## 8. Quality gates and CI

### 8.1 Milestone gates (MVP)
| Gate | Pass criteria (all required) | Signs off |
|---|---|---|
| **M0** (h2.5) | `make smoke` green in the image; `smoke-native` green on 4 laptops; peak VM recorded; `test_lockfiles_in_sync`, `test_dockerignore_excludes_secrets`, `test_groq_disabled_by_default_no_egress`, `test_smoke_rejects_network_fs_for_db`, `test_worker_does_not_import_api`, `test_compose_ports_loopback_only`, `test_check_no_mean_flags_pandas_paths` † green; gitleaks hook installed; CSP spike hydrates with 0 violations; `h0_report.json` decision in `case.yaml` | A, C, D |
| **M1** (h8 / fakes h8.5) | `contracts-check` green; `schema.d.ts` committed; B-01 named tests + `prop_canonical_deterministic`, `prop_ids_content_addressed` † green; port contract tests [fake] green; `test_trigger_aborts_update`, `test_no_update_paths_status_derived`, `test_failed_build_same_key_can_retry` green; the h6 pypdfium2 checkpoint is recorded | B, A, D |
| **M2** (h10) | Skeleton e2e smoke: the C-17 vs S-88 card in red "They disagree", with the version badge, and numbers from the engine (`e2e_skeleton_card` †, not timed) | All |
| **M3** (h24) | Every M3 named test in §D.3 green; floor properties #1–4 green at h20; `test_conformal_oracle` green **before** the first bless; goldens 0, 1a, 1b, 3, 4, 5, 5b + held 2, 6 blessed and green incl. `golden-randseed`; `test_all_pointers_re_resolve` 100%; `test_build_demo_all_under_60s_image` green (image + native); 0 open Sev-1/Sev-2 on floor modules; floor branch coverage ≥ 95% | A + B (D for goldens) |
| **M4** (h28) | All M4 named tests green; 5 binding e2e specs + † e2e (story, timeline, table, image, sensor, two-clicks, labels, no-CSP-violations) green on the image; all of §5.1 green on the image and native; NFR-10/11 checked | C, D, A |
| **M5** (h30, freeze) | `make check` + `make e2e` green on `main`; hostile corpus 13/13; sentinel and doc-text tests green; `test_network_off_build_succeeds`, `test_parallel_eval_runs_one_proceeds` green; `make audit` run with **no unwaived critical/high** (waivers written in the freeze notes); eval dev run produced; tag `mvp-freeze` with 3 hashes pushed | D, A |
| **M6** (h36) | Holdout run once (h31), report complete; `test_image_nonroot_readonly`, `test_image_has_no_secrets` †, `test_image_digest_equal_two_laptops` †, `test_native_replay_verify_equals_image` † green; perf report on both platforms; anchors pushed (`test_anchor_pushed_to_remote` †); rehearsal against §10 done | D, all |

### 8.2 Release gates
**MVP demo go/no-go (h33, at rehearsal). GO needs all of the following:**
1. M5 and M6 gates are green.
2. Goldens 0–6 are green, and the slides match `expected.json`.
3. The holdout false-alarm Wilson lower bound is ≤ 5%. If it is above 5%, the headline claim is removed from the slides and that removal is disclosed. This rule alone does not force NO-GO.
4. 0 open Sev-1 defects; any open Sev-2 has a workaround written into the talk track.
5. The demo runs with the network off, on both laptops.
6. The backup video is recorded.

**NO-GO:** any Sev-1 open, a Demo 0 golden failing, or the image failing to start on both laptops. In that case the presenters fall back to the native replay laptop, and then to the video.

**Pilot phases:**
| Phase | GO criteria |
|---|---|
| **P1 exit** | All P1 named tests green; the full suite passes under `--network none` with all AI modes off; Schemathesis has run with 0 server errors and 0 schema violations; `fuzz_mutated_pdf_smoke` has 0 API crashes (1,000 mutants); holdout re-run with ECE before and after calibration (`test_ece_after_calibration_holdout` †); CI (P1-11) is enforcing check, e2e, perf, audit, gitleaks and image-scan; 0 critical/high CVEs without a waiver |
| **P2 exit** | The suite is green on `[pg, minio]` parametrisations; `test_migrated_chain_verifies`, `test_upgrade_n_minus_1_chain_verifies`, `test_app_role_cannot_disable_trigger_or_truncate`, `test_locked_object_delete_denied`, `test_bucket_lock_mode_matches_policy`, `test_20_parallel_decisions_one_wins[pg]`, the OIDC tests, `test_restore_drill_db_blob_consistent` (inside the RTO), `test_integrity_job_alerts_on_tamper` and `test_egress_denied_except_allowlist` are green; `replay-verify` passes on the migrated chain; the k6 thresholds in §5.3 pass; the ASVS L2-subset pen test has 0 high findings |
| **P3 exit** | 40 machines registered; the readiness report is green or each item is accepted in writing; every envelope has n ≥ 19 or is labelled pooled; the plant-holdout false-alarm Wilson lower bound is ≤ 5% (point estimate reported); labelled precision is ≥ 0.90 and recall ≥ 0.85 on the labeller set (κ ≥ 0.7 on the 50 double-labelled items); ADR-17 goldens are green, or check 4 stays failing for sensor vs. authored (`test_sensor_known_unit_check4_fails_until_adr17` †) |
| **P4 GO (week 12)** | The 7 criteria in plan §E P4, each with an automated measure: (1) precision ≥ 0.85 on N ≥ 100 adjudicated conflicts, with the Wilson lower bound ≥ 0.75; (2) `scan_gaps_read_as_normal` † over every version = 0; (3) the false-alarm lower bound and point estimate are both ≤ 5% on ≥ 400 machine-days; (4) ECE ≤ 0.05 with CI; (5) the median reviewer time from `review_events` is ≤ 2 h/week; (6) 0 Sev-1 integrity incidents (nightly `trace_integrity_ok` = 1); (7) the sponsor signs off on 3 cases. Any miss means NO-GO, or an extension decided by the sponsor |

### 8.3 Pipeline stages
The MVP has no hosted CI. "PR" therefore means that the reviewer runs `make check` locally before merging, and the result is pasted into the PR. From P1-11 the same stages run in CI.

| Stage | Contents | Time budget |
|---|---|---|
| **pre-commit** | ruff, eslint, `nomean`, `contracts-check`, `test_lockfiles_in_sync`, gitleaks, `test-fast` (unit + ports[fake] + golden + properties@precommit), `test_seed_sha256sums_match` † | ≤ 90 s |
| **PR** | `make check` (lint, mypy/tsc strict, import-linter, nomean, contracts, lockfiles, `make test` with `-n auto`, `golden-randseed`) + `make e2e` when `frontend/` or API routes change | ≤ 10 min |
| **nightly** | properties@nightly; `check-perf` (image); `replay-verify` (image + a native Windows runner from P1); hostile + `fuzz_mutated_pdf_smoke` (P1); Schemathesis (P1); `make audit`; trivy; P2+: `trace verify --all`, the k6 smoke at 10 VUs | ≤ 60 min |
| **release** | Everything above + image builds on 2 hosts with the same digest + `test_image_nonroot_readonly` + `test_network_off_build_succeeds` + perf on both platforms + cosign sign/verify (P1-11/P2-09) + changelog of golden diffs since the last release | — |

**Holdout is never part of any stage.** It runs only through `make eval-holdout`.

---

## 9. Defects, flakiness, test data

### 9.1 Severity
| Sev | Definition (any of) | Response |
|---|---|---|
| **Sev-1** | A wrong outcome on a pinned demo; any "agree" with ∀ coverage < 100% or a gap read as normal; an averaged value; a held claim paired; integrity green on tampered data, or red on clean data; secret or document text leaked; holdout contamination; cross-case data visible; parser crash that kills the API | Stop the line. Fix before anything else; the buffer owner reassigns people. The test that catches it must exist before the fix merges |
| **Sev-2** | A floor test or property failing outside the demos; a NFR-7 budget missed on the image; replay mismatch; a security floor control failing (S1–S11); e2e red under the CSP | Fix within the milestone; it blocks the milestone gate |
| **Sev-3** | A native-only perf miss; a UI defect with a workaround; a non-floor flaky test | Fix before the release gate, or waive in writing |
| **Sev-4** | Cosmetic, docs | Backlog |

**Triage.**
- New defects are triaged at each standup (h2, h6, h10, h14, h20, h24, h28, h32) by the Tester with the owner of the area.
- The severity is recorded in the issue together with the failing test name.
- A defect that has no failing test is not "fixed" until a test reproduces it.
- In the pilot, triage is weekly. A Sev-1 integrity incident pages people through the P2-08 alert.

### 9.2 Flaky-test policy
- **Floor tests can never be quarantined.** That covers all of §4 #1–5, #9, the goldens, the hostile corpus, authz, the sentinel and the 409 races. A flake in one of them is treated as a real defect (Sev-2).
- **Other tests** may be marked `@pytest.mark.quarantine(issue=…, until=…)`:
  - for at most 12 h in the MVP and 5 working days in the pilot;
  - quarantined tests still run and report, but do not gate;
  - an expired quarantine fails the build.
- **Timing tests:**
  - Playwright uses the median of 5 runs and `retries: 0`.
  - API perf uses 2 warm-ups and "2 consecutive misses".
  - No `sleep`-based waits are allowed. Tests wait on events, `expect.poll` or build status.
- **Stable inputs.** Hypothesis is derandomised in pre-commit, and every failing seed is recorded and promoted to `@example`. xdist ordering issues are caught by running `-p randomly` nightly (P1).

### 9.3 Test data management
- **No real PII.**
  - The machines, errors and telemetry come from the public Microsoft dataset.
  - All people are synthetic. The badge names are `A. Reviewer`, `B. Senior`, `Judge (demo)` and similar.
  - The serials are synthetic (`SN-00xx`).
  - Every authored artefact carries the "written for the demo" or "synthetic" badge, and "planted for the demo" where that applies.
  - `test_seed_contains_no_real_pii` † checks names against an allowlist and checks images for EXIF GPS.
- **Credentials.**
  - Generated per environment and kept only in `seed/credentials.local.txt` (git- and dockerignored).
  - The sentinel key is a fake `gsk_TESTSENTINEL…` and never a real key.
  - A real Groq key is never used in tests except in `record`-marked runs, on a developer machine, with consent. Recorded responses are reviewed for PII before they are committed.
- **Pilot.**
  - Plant data never enters the repo.
  - Test fixtures derived from plant data are anonymised: names replaced, serials re-keyed.
  - Staging holds a copy only under the DPO retention decision (P2-03).
- **Holdout files** are written once by D-06 and are read-only for everyone except the holdout run.

---

## 10. Pre-demo checklist (test-oriented)
- [ ] `make check`, `make e2e` and `make golden-randseed` are green at the exact demo commit, and that commit is tagged and pushed.
- [ ] Goldens 0, 1a, 1b, 2, 3, 4, 5, 5b and 6 are green. The slide numbers were diffed against `expected.json` (h32), and Demo 0's h0 choice is shown with a badge if it was planted.
- [ ] Every demo machine has n ≥ 19 quiet days, or carries the "model-level pool" label in the Envelope view.
- [ ] The holdout report exists, shows the pushed config, engine and lock hashes, and is not "superseded".
- [ ] The perf report shows build < 60 s, proof < 1 s and decision → card < 2 s, on the image **and** on native on both demo laptops.
- [ ] Playwright passes against the image with the enforcing CSP header, with 0 CSP violations.
- [ ] The hostile corpus passes 13/13, and the sentinel and doc-text log tests are green.
- [ ] `test_image_nonroot_readonly`, `test_image_has_no_secrets` † and `test_network_off_build_succeeds` are green. Wi-Fi is off during the run-through.
- [ ] `test_image_digest_equal_two_laptops` † and `test_native_replay_verify_equals_image` † are green.
- [ ] `anchors/demo_roots.txt` is pushed (`test_anchor_pushed_to_remote` †). The UI root equals the anchor, and the integrity badge is green.
- [ ] Byte-flip rehearsal: copy the case, flip one byte, see "evidence changed", then discard the copy. The clean case is still green.
- [ ] The judge card is printed and its login works. "Signed in as" is visible. Personas are switched by logging out. A decision by `viewer1` shows 403.
- [ ] The decision rehearsal on Demo 2 creates v+1 in under 2 s, and the review queue shows the decision with its name and reason.
- [ ] `compose.demo.yml` binds 127.0.0.1 only (`test_compose_ports_loopback_only`), and no `.env` with a real key is on the demo laptops.
- [ ] The backup video plays offline, and the native replay fallback has been rehearsed once.

---

## 11. Unmapped or partially mapped IDs
| ID | Status | Reason |
|---|---|---|
| T-35 tenant isolation | **No test** | Accepted risk, P5. The MVP's case scoping is covered by `test_cross_case_claim_404` and `test_authz_matrix` † |
| NFR-8 "~1M concurrent readers" | **Not tested** | A P5 CDN claim. The pilot tests only p95 < 300 ms at 50–100 users and the 2-minute build |
| NFR-9 per-customer separation and keys | **Not tested** | P5. The MVP and pilot test the PII-minimisation and no-PII parts only |
| T-36 erasure | Partial | The P2 policy test and the P3 runbook drill exist; crypto-shredding is P5 |
| `manifest_hash` in goldens | Open issue | The golden-mode convention in §3.1 needs B/D confirmation before h16 |
| Hostile corpus "original 7" | Assumption | The list in §6.1 needs A's confirmation |
