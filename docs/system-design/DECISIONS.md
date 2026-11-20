# TRACE — Architecture Decision Records

**How these were decided:**
- Three agents with fixed personas argued every decision over two rounds:
  - **Architect:** production-grade purist;
  - **Pragmatist:** 36-hour, 4-person delivery;
  - **Red Team:** security, correctness and skeptical-judge view.
- A fresh, independent **Judge** then read everything and issued binding verdicts.
- The Judge was told not to take the majority, and to check agreements as well as disputes.
- **Status of every ADR: Accepted.** Nothing was left unresolved.

The full reasoning is in [`DEBATE_LOG.md`](DEBATE_LOG.md) and [`debate/`](debate/).

**Two confirmations are needed from the team. Neither blocks the build:**
| ID | Question | If yes | If no |
|---|---|---|---|
| **U-1** ✅ decided | Will the TRACE repo be published under AGPL-compatible terms? | — | **Decided by the user: use pypdfium2 from day 1** (about +3 h; permissive licence) |
| **U-3** ✅ decided | Which LLM/VLM provider for P1 and the pilot? | — | **Groq** (OpenAI-compatible) behind `LlmProposer`. Key in `.env` (`GROQ_API_KEY`), opt-in, cached, redaction hook, no network in P0 |
| **U-2** | Is a labeller who did not build TRACE available? | They author ≥ 30% of faults and label the eval set | Person D (who wrote no rules) labels, and this is disclosed in the report |

---

## ADR-01 Overall shape: hexagonal modular monolith
| | |
|---|---|
| **Debate** | All three agents converged in R1. Nobody argued for services. |
| **Decision** | One repo and one deployable. `trace_core` is pure: no FastAPI, no sqlite3, no filesystem, no `datetime.now()`. Its entry point is `build_case(manifest, config_bundle, decisions, clock) -> CaseVersion`. Ports are `typing.Protocol`: `ClaimStore, BlobStore, PdfReader, OcrReader, ExtractionCache, Clock, LlmProposer`. `import-linter` blocks core → adapters/api imports. |
| **Why** | (1) Determinism (NFR-4) is only testable if the core is a pure function. (2) Stage functions become Temporal activities later, so the claim that the "engine runs unchanged in workers" is literally true. (3) Four people can code in parallel against Pydantic contracts frozen at h8. (4) No P0 requirement needs a network boundary. |
| **P0 / P1 / P2** | Whole shape / — / stages as separate worker pools |
| **Residual risk** | I/O leaks into the core through a helper. **Mitigation:** import-linter in pre-commit. |
| **Would change if** | One stage needs another runtime (for example a GPU VLM). Then that adapter alone becomes HTTP. |

## ADR-02 Pipeline execution: killable child process + persisted build row
| | |
|---|---|
| **Debate** | Architect R1: Postgres job queue (Procrastinate). Pragmatist R1: FastAPI `BackgroundTasks`. Both moved to a `ProcessPoolExecutor` in R2. Red Team: a job row plus heartbeat and stale sweep. |
| **Decision** | `POST …/build` returns 202 with a build ID. One `multiprocessing.get_context("spawn").Process` runs per build, with a 180 s wall timeout → `terminate()`, `RLIMIT_AS` of 2 GiB, and `pytesseract(timeout=20)`. The `builds` row holds status, a heartbeat every 5 s and per-stage ms. A partial unique index allows one build per case. A startup sweep turns heartbeats older than 60 s into `failed_stale`. `build_key` makes builds idempotent. **A decision re-run is synchronous** over cached claims, inside `BEGIN IMMEDIATE`. |
| **Why the others lost** | `BackgroundTasks` cannot be killed and blocks the loop. `ProcessPoolExecutor` cannot kill a hung worker without breaking the pool: *"a timeout you cannot enforce is not a sandbox"*. A broker is not needed by any P0 requirement. |
| **P0 / P1 / P2** | All / SSE "build done" / Temporal |
| **Residual risk** | About 1–2 s of spawn overhead; no RLIMIT on Windows. **Mitigation:** the demo runs in the Linux container. |
| **Would change if** | Builds exceed 60 s or eval needs parallel builds. Then use N children under a semaphore, still with no broker. |

## ADR-03 Storage: one SQLite file with append-only triggers
| | |
|---|---|
| **Debate** | Architect R1: Postgres 16 with `tstzrange` and REVOKE, conceded in R2. Pragmatist and Red Team: SQLite with triggers. The PRD's "SQLite per case" was rejected by everyone. |
| **Decision** | `data/trace.db` in WAL mode, stdlib `sqlite3`, no ORM. Evidence tables have `BEFORE UPDATE` and `BEFORE DELETE` triggers that abort. A `version_claims` table replaces `"version"` inside claims. **Status is derived from `review_events`, never stored mutably** (a bug the Judge found that no debater had). Intervals are half-open UTC fixed-width strings. Telemetry is split into Parquet per machine as a derived source, and hourly readings are not claims. Snapshot JSON is hashed and the hash stored on `versions`. |
| **Why** | No install risk. A live UPDATE that aborts is visible enforcement. It removes the version-field contradiction. |
| **P0 / P1 / P2** | All / — / Postgres with the same triggers, REVOKE and RLS |
| **Residual risk** | `database is locked` errors. **Mitigation:** `busy_timeout`, short transactions, one build per case. |
| **Would change if** | There are more than 2 concurrent writers per case, or multiple hosts. Then move to Postgres. |

## ADR-04 Integrity: per-pointer hashes, a chained manifest, a pushed remote anchor
| | |
|---|---|
| **Debate** | Architect R1: Merkle tree plus Ed25519 in P0. Pragmatist: a hash chain only. Red Team: a key in `.env` on the same box proves nothing. All conceded the Merkle tree. The Judge **tightened** the agreed "commit the anchor to git": it must be **pushed**, because a local commit can be rewritten. |
| **Decision** | SHA-256 per source, per pointer (quote, page text, crop, CSV line, Arrow window), and per record (`JCS(body − wall-clock)`, RFC 8785). `manifest_hash` is chained to its parent and covers the config, engine SHA, lockfile, sources and snapshot. `GET …/integrity` returns a green or red badge. Demo roots are appended to `anchors/demo_roots.txt` and **pushed** before the demo. **Ed25519 is P1, only with the private key off the serving box.** |
| **Why the others lost** | Merkle inclusion proofs serve no persona. Signing without key custody is theatre. |
| **P0 / P1 / P2** | Hashes, chain, snapshot hash, pushed anchor / Ed25519 off-box / S3 Object Lock and a transparency log |
| **Residual risk** | Root access on the laptop can rewrite everything. **Mitigation:** compare against the remote anchor, and state the threat model honestly. |
| **Would change if** | An offline auditor needs a single-claim proof. Then add a Merkle tree. |

## ADR-05 Determinism and versioning
| | |
|---|---|
| **Debate** | Converged. Architect's weak spot W3 (decisions tied to claim IDs that change on rebuild) was adopted. |
| **Decision** | Claim IDs are content-addressed; display labels such as C-17 live in a separate `label` column. No wall clock inside hashes. `config_hash` covers the whole config bundle. dateparser runs with `RELATIVE_BASE = observed_time`. **Tesseract, VLM and LLM outputs are cached, and a cache miss during replay is an error.** Floats use a fixed 6 dp, sorting is explicit, `PYTHONHASHSEED=0`. A **Verify replay** button rebuilds and compares `manifest_hash`. Decisions are keyed to a stable mention key `(source_sha256, locator)`. |
| **Honesty clause** | Replay from artifacts is byte-identical on any machine. Fresh OCR is reproducible inside the pinned image. |
| **P0 / P1 / P2** | All / cross-machine CI job / — |

## ADR-06 Extraction stack
| | |
|---|---|
| **Debate** | PDF library: PyMuPDF (Architect, Pragmatist) vs. pdfplumber (Red Team R1, conceded). PDF viewer: pdf.js (Architect R1) vs. server-rendered PNG (Pragmatist; the Red Team agreed for security). OCR: everyone chose Tesseract. LLM quote check: Red Team R1 wanted 4 gates and simplified in R2; the Judge **restored** value and unit re-derivation. |
| **Decision** | PyMuPDF behind `PdfReader`, with PNG render at 150 dpi and offsets that index the **hashed page-text artifact**. A **hidden-text guard** holds spans under 4 pt, outside the CropBox, or with crop pixel std-dev < 8. Tesseract 5 is pinned. The re-read is labelled a *consistency check*. Each gauge has a plausibility range. EXIF is transposed and stripped. CSV only in P0. The LLM (P1) has no tools, temperature 0, an offline cache, and a verifier: exact NFC match, a unique quote of ≥ 12 characters, value and unit re-derived by rules, entity only from the resolver. |
| **Why the others lost** | pdfplumber needs a second renderer and is 5–10× slower. pdf.js puts PDF JavaScript in the browser and was the biggest frontend time sink. EasyOCR pulls about 2 GB of torch and is nondeterministic on GPU. "Value inside the quote" still accepts 8.9 when the quote contains both 6.9 and 8.9. |
| **P0 / P1 / P2** | As described / LLM + verifier (Groq), VLM second reader (Groq vision), XLSX / — |
| **Amendment (user decision U-1)** | **pypdfium2 replaces PyMuPDF from day 1.** It provides text-page offsets, per-char boxes, font size through the raw PDFium API, and PNG rendering. The pixel-based hidden-text guard is unchanged because it works on the rendered PNG. |

## ADR-07 Entity resolution, timeline and review placement
| | |
|---|---|
| **Decision** | rapidfuzz WRatio, aliases, context features and a named `digit_transposition` feature. **Auto-link needs a score ≥ 0.85, a margin ≥ 0.15 *and* at least one agreeing non-string feature. A serial conflict is a veto.** Weights are tuned on dev seeds only; whatever the holdout gives for "Press 21" goes on the slide. Each case declares `plant_tz` (demo: Asia/Kolkata). Days are local `[D, D+1)`. No document date → `granularity=unknown`, and file mtime is never used. Review sits **between normalise and gate**, and held items never form pairs. "Mark explained" never changes an outcome. |
| **Why** | Closes over-merge (T-10), day-boundary errors (T-11) and guessed time (T-12). The reason strings *are* the content of Demo 2. |
| **P0 / P1 / P2** | All / shift-level envelopes / ML matcher (proposes candidates only) |

## ADR-08 Frontend: static Astro + React islands, same origin
| | |
|---|---|
| **Debate** | Architect R1: Astro SSR with the Node adapter, pdf.js, TanStack Table and nanostores. All conceded to static output in R2. |
| **Decision** | `output:'static'`, Tailwind, **one `client:only="react"` island per page**. FastAPI serves `dist/` from the same origin. TanStack Query with the **version in every key**. A single `RegionViewer` draws a PNG with a bbox overlay. ECharts for the sensor chart and the timeline. `react/no-danger` is banned. Strict CSP with build-time hashes. **SSE for live updates (P1); WebSocket is rejected.** |
| **Why the others lost** | SSR adds a second runtime, a second auth surface and cookie forwarding. Text selection is not a requirement, so pdf.js is not needed. A cross-island store solves a problem the design doesn't have. |
| **Residual risk** | The CSP breaks hydration. **Mitigation:** a Report-Only check at h30, and Playwright under the enforcing CSP. |

## ADR-09 API: case-scoped REST, precise 409s, private immutable caching
| | |
|---|---|
| **Debate** | Architect: `public, immutable` caching, Idempotency-Key, cursor paging. Red Team: `public` on authenticated content leaks across users; IDOR in the PRD's `/claims/{id}`. The Judge **tightened** the agreed "409 on stale `base_version`" (it would block unrelated decisions). |
| **Decision** | Every route is case-scoped through one `resolve_case_and_authorize` dependency. Errors are RFC 9457. Offset paging over frozen versions. Versioned JSON is `private, max-age=31536000, immutable`, `ETag = manifest_hash`, `Vary: Cookie`; `latest` and writes are `no-store`. The decision body is `{choice, reason≥15, base_version, shown_evidence_hash}` with `extra="forbid"`, **so a `reviewer` field returns 422**. **409 only when already decided or evidence changed.** Supersede is senior-only. |
| **P0 / P1 / P2** | All / Schemathesis / tenant in the path |

## ADR-10 Authentication: per-user argon2id + opaque server sessions
| | |
|---|---|
| **Debate** | Pragmatist R1: pick-a-name, conceded. Red Team R2: per-role PIN + localhost only. Architect: seeded users + argon2. |
| **Decision** | Seeded per-user accounts with argon2id. An opaque `token_urlsafe(32)` session, rotated at login, 8 h idle expiry. Cookie: `HttpOnly; SameSite=Strict`. Writes need the CSRF header and a JSON content type. Lockout after 5 failures in 5 minutes. Bound to `127.0.0.1` by default; LAN requires TLS. Roles: viewer, reviewer, senior_reviewer, ingestor, evaluator. **Identity comes only from the session.** |
| **Why the PIN lost** | A shared PIN breaks *individual* attribution (US-3) just as pick-a-name does, and it saves only about 30 lines. Localhost is kept **as well as** passwords. JWT was rejected by all. |
| **Would change if** | The host provides SSO. Then use OIDC. |

## ADR-11 Observability
| | |
|---|---|
| **Decision** | `structlog` JSON logs with request, case, build, version, config and stage IDs. **No document text in logs.** Per-stage ms and counters on the build row, shown in the expert view. Stage names equal future OTel span names. |
| **Why** | Judges see the expert view; nobody opens Jaeger. The audit trail is the data plus the chain, not the logs. |
| **P0 / P1 / P2** | As described / OTel, `/metrics` / alerting, runbooks |

## ADR-12 Testing
| | |
|---|---|
| **Decision** | Goldens for Demos 0–6 pin **computed** values and `manifest_hash`. Hypothesis properties: symmetry, totality, never-average, unit round-trip, unknown units never convert, overlap commutativity, **gap monotonicity**, chain detection. A 7-file hostile corpus. A minimal authz test (403/404). Five Playwright scripts under the enforcing CSP. `tsc` on generated types as the contract test. **Eval hygiene:** disjoint dev/holdout seeds, the config hash pushed before the holdout run, ≥ 30% external faults, a Wilson CI on the false-alarm rate, ECE and Brier with bootstrap CIs. |
| **P0 / P1 / P2** | All / Schemathesis, full authz matrix, PDF fuzzing / — |

## ADR-13 Deployment and scale path
| | |
|---|---|
| **Debate** | All three agreed that PRD §15 overclaims. The Judge concurred. |
| **Decision** | **Hackathon:** one multi-stage Linux image (Node build → `python:3.11-slim`@digest + Tesseract), non-root, read-only rootfs, one volume, no outbound network, lockfiles, a `uv run` native fallback, two laptops, a backup video, `make demo`. **Scale:** an authorised edge cache keyed by (tenant, case, version); stateless reads with Redis; Postgres with triggers, RLS and replicas; S3 Object Lock; Temporal when paid model calls need retries; an outbox with LISTEN/NOTIFY for snapshots and SSE. **Kafka, Citus and TimescaleDB are "planned only if"** they reach their triggers. |
| **Why** | A million readers is a cache problem, and frozen versions are perfectly cacheable. Every write-side box must earn its place. |

## ADR-14 Correctness floor: conformal "normal" and gate statistics
| | |
|---|---|
| **Debate** | The Red Team found that the PRD rule (every hourly value in p5–p95) false-alarms on almost every quiet day (T-01). It also found statistic mismatch (T-02), "agree" with partial data (T-03), envelope poisoning (T-04) and invented units (T-05). Architect R2 proposed robust z with an empirical p95. **The Judge replaced that with a split-conformal threshold** and overruled the agreed "before-only" training for the demo, because it would leave too few quiet days (about 14). |
| **Decision** | Quiet days need log coverage, 24/24 telemetry, ±3 days clear of events and must be outside the case window. Robust med/MAD per channel. `T_d` = the daily max of \|z\| across channels in scope. **`T* = T_(⌈0.95(n+1)⌉)`, which bounds quiet-day false alarms at ≤ 5%.** n < 19 → pooled across the model. ∀/∃ quantifiers; **∀-agree needs 100% coverage**. S-88 is day-level, with child S-88.1 for the hourly peak. Telemetry units are `sensor_native`. Duplicate timestamps become `GapClaim(conflicting_readings)`. Confidence: C-17 = **0.83** computed; demo numbers are computed, never typed. |
| **Residual risk** | Seasonality breaks exchangeability, or the real M-21 on 14 Mar doesn't exceed T\*. **Mitigation:** a holdout false-alarm rate with a Wilson CI, and the h0 reality check (pick the real day, or plant it and label it). |
| **Would change if** | The holdout false-alarm rate is well above α. Then use a de-seasonalised rolling baseline. |

## ADR-15 Security floor (about 8.5 h, P0)
| ID | Control |
|---|---|
| S1 | Per-user argon2id sessions; identity only from the session; 422 on a `reviewer` field; bound to 127.0.0.1 |
| S2 | `SameSite=Strict`, CSRF header, JSON-only writes |
| S3 | Precise 409s; supersede is senior-only |
| S4 | Killable build process, heartbeat sweep, one build per case |
| S5 | Triggers, chain, snapshot hash, pushed anchor |
| S6 | **Uploads on, `ingestor` role only.** Streaming caps (25 MB documents / 200 MB telemetry); magic-byte allowlist {PDF, PNG, JPEG, CSV, TXT, MD}; no SVG, TIFF or XLSX; `MAX_IMAGE_PIXELS` 40 M as an error; a 50-page PDF cap; hash-only paths; free-disk check |
| S7 | Originals served as `attachment` with `nosniff` and `CSP: sandbox`; display images derived and EXIF-stripped |
| S8 | `react/no-danger`, strict CSP |
| S9 | Central `resolve_case_and_authorize` |
| S10 | No document text in logs; no network calls in P0 |
| S11 | Non-root, read-only-rootfs container |

**Why uploads stay on:** a judge *will* say "upload my file". Disabling the endpoint hides the feature instead of securing it, and hardening it costs about 1.5 h.
