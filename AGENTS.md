# AGENTS.md — TRACE

> Project rules for **any AI coding agent**: Google Antigravity, Claude Code, Cursor, Copilot, Codex and others.
> This file mirrors `CLAUDE.md`. **Keep the two in sync.** A rule change goes into both files in the same commit.
> If your tool reads a different rules file, copy this content there or point it here.

## Agent operating rules (read first)
1. **Work one milestone at a time** (M0 → M6 in `docs/IMPLEMENTATION_PLAN.md`). Stop and report after each one.
2. **Nothing is done until `make check` is green.** Never weaken, skip, delete or mark `xfail` a test, lint rule, import contract or golden just to make it pass. Fix the code, or stop and ask.
3. **Ask a human before running any terminal command that:**
   - installs or upgrades packages;
   - pushes, rewrites git history or force-resets;
   - deletes files or databases;
   - reads, prints or edits `.env`;
   - runs `make eval-holdout` or `make anchor`;
   - makes a network call.
4. **Do not let browser or automation features** sign in, submit forms, or reach external sites for this project unless a human asks.
5. **Use the strongest available model** for the M3 engine, the correctness floor and the determinism work. Faster models are fine for scaffolding and UI.
6. **When docs conflict, say so.** Do not silently choose one (the precedence order is below).

TRACE (Traceable Reasoning Across Cross-modal Evidence) turns text, PDFs, photos, tables and sensor time series into one inspectable state per case.
- Every fact is a `ClaimRecord` with an exact evidence pointer.
- Conflicts are flagged only when they are genuinely comparable, and are **never averaged**.
- Hackathon: TECHgium 10th edition, PID TG0906436.

## Source of truth (read before non-trivial work)
| Doc | Use it for |
|---|---|
| `docs/TRACE_PRD.md` | What to build (FR/NFR, schemas §9, algorithms §10, demos §11, eval §12, API §13) |
| `docs/system-design/SYSTEM_DESIGN.md` | How it is built (architecture, data model, integrity, API, frontend) |
| `docs/system-design/DECISIONS.md` | Binding ADRs. Do not re-decide them |
| `docs/system-design/HARDENING.md` | Threats T-xx, N-x and controls S1–S11, each with a named test |
| `docs/IMPLEMENTATION_PLAN.md` | Task IDs (A-xx/B-xx/C-xx/D-xx, P1-xx…), milestones, coding strategy, Definition of Done |
| `docs/TEST_PLAN.md` | The acceptance matrix, named tests, quality gates |

When docs disagree, the order is: user instruction > IMPLEMENTATION_PLAN §0 > DECISIONS > SYSTEM_DESIGN > PRD. Report the conflict; don't silently pick one.

## Product promises (inviolable; a change that breaks one is a bug)
1. **Never average conflicting values.** Both sides are stored and shown. Duplicate timestamps with different values become `GapClaim(conflicting_readings)`. `tools/check_no_mean.py` must stay green.
2. **LLMs propose, rules decide.** No model output sets an outcome, entity or confidence. Every LLM proposal passes the 5-check verifier (exact quote, unique ≥ 12 characters, value and unit re-derived by the rules, entity from the resolver, class mismatch → review).
3. **Every fact has an address.** An extracted claim needs an `EvidencePointer`. An inferred claim needs `derived_from` + `rule_id`.
4. **No data ≠ normal.** A ∀ claim ("ran normally") can only *agree* with 100% coverage. Gaps, flatlines and partial coverage give "We can't tell".
5. **Units are never guessed.** MS telemetry is `sensor_native` and never converted. A physical unit vs. telemetry gives "can't be compared".
6. **Append-only evidence.** No UPDATE or DELETE on evidence tables (triggers enforce it). Status is *derived* from `review_events`. Claims carry no version (use `version_claims`).
7. **Time:** half-open `[start, end)`, stored in fixed-width UTC `YYYY-MM-DDTHH:MM:SSZ`, with the case `plant_tz` for days. No document date → `granularity=unknown`. File mtime is never used.
8. **Demo numbers are computed, never typed.** No literals such as 64, 34, 47, 0.71, 0.94, 0.62 or 0.22 in engine code. Goldens pin *computed* values.
9. **Identity comes only from the session.** A `reviewer` field in a request returns 422. Decisions store `user_id`, role, `base_version` and `shown_evidence_hash`.

## Architecture rules
- **`trace_core` is pure.**
  - No I/O, no `sqlite3`, `pypdfium2`, `pytesseract`, `PIL`, `pyarrow.dataset`/`parquet`, `openai`, `httpx`, `requests`, `socket`, `subprocess`.
  - No `datetime.now()`, `time.time()`, `os.environ` or `open()`.
  - Time comes from the `Clock` port. import-linter (`.importlinter`) and ruff `TID251` enforce this.
- **Layers:** `trace_api` → `trace_worker` → `trace_adapters` → `trace_core`. In addition, `trace_worker` must not import `trace_api`.
- **The API never decodes untrusted files.** `trace_api` must not import pypdfium2, pytesseract or PIL. Rendering and OCR happen **only in the build child** (`trace_worker.build_runner`), a killable spawned process with an allowlisted env.
- **Ports are `typing.Protocol`.** Every adapter passes the shared contract tests in `tests/unit/ports/`.
- **Determinism:**
  - claim IDs are content-addressed (`ids.py`), and records are hashed through `canonical.py` (JCS, 6-dp Decimal);
  - every reader output goes into `extraction_cache`, and **a replay miss is an error**;
  - sorts are explicit, and quantiles use `method="linear"`.
- **API:**
  - every route is case-scoped via `resolve_case_and_authorize`;
  - errors are RFC 9457 problem+json, with stable `type`s;
  - versioned reads are `private, immutable` with ETag = `manifest_hash`; `latest` and writes are `no-store`;
  - authenticated responses are never `public`.
- **Decisions use compute-then-commit.** Compute v+1 outside the lock, then a short `BEGIN IMMEDIATE` re-check and insert. A 409 is returned only for `already-decided`, `evidence-changed` or `build-in-progress`.
- **Frontend:**
  - Astro `output:'static'`, served by FastAPI on the same origin;
  - one `client:only="react"` island per page;
  - TanStack Query keys **always include the version**;
  - `dangerouslySetInnerHTML` is banned, and ECharts string formatters must be escaped;
  - the strict CSP header comes from `dist/csp-hashes.json`.
- **Contracts are frozen after h8** (tag `contracts-v1`). Any schema or API change needs a Contract Change Request (B approves), then `make contracts`. `make contracts-check` must pass.

## Stack and commands
- **Backend:** Python 3.11, FastAPI, Pydantic v2, uv. **Frontend:** Astro, Tailwind v4, React 18, TanStack Query, ECharts, npm. **PDF:** pypdfium2 (never PyMuPDF). **OCR:** Tesseract 5 (pinned in the image). **Storage:** SQLite WAL (MVP), Postgres 16 + MinIO (pilot).
- **Common commands:**
  - `make setup`
  - `make smoke` (image) / `make smoke-native` (Windows)
  - `make check` (lint, type, imports, nomean, contracts-check, lockfile sync, tests, golden-randseed)
  - `make test-fast`, `make golden`, `make props`, `make hostile`, `make authz`, `make check-perf`, `make e2e`
  - `make demo`, `make replay-verify`
  - `make eval-dev`
  - `make eval-holdout`: **only at the h31 holdout run, clean tree, hashes pushed**
  - `make run-docker` / `make run-native` (both bind 127.0.0.1)
- **Windows:**
  - clone inside the WSL2 filesystem for Docker, and keep `data/` as a named volume;
  - native runs use **replay** mode against `seed/cache/`;
  - `make record-cache` and `make seed-gen` run only inside the image.
- Never edit `uv.lock` or `package-lock.json` by hand. Use `npm ci --ignore-scripts`.

## Coding conventions
- `mypy --strict` on core, api and worker; TypeScript `strict` + `noUncheckedIndexedAccess`.
- Pydantic models are `frozen=True, extra="forbid"`. Use `assert_never` on enum matches. **Fail closed**: unknown becomes can't-compare or can't-tell.
- Name tests exactly as in IMPLEMENTATION_PLAN §D.3, TEST_PLAN and HARDENING. Every invariant gets a Hypothesis property.
- Every behaviour change ships with tests. Hot paths need an entry in `tests/perf/`.
- **Goldens:** `make golden-bless CONFIRM=1` only when the conformal oracle test is green. The diff must be explained in the PR.
- Keep PRs small (under about 300 lines) and branches short-lived (under 4 h during the hackathon).

## Security conditions
- **Secrets:**
  - `GROQ_API_KEY` (and any other secret) lives only in `.env`, which is git- and docker-ignored. `.env.example` holds placeholders;
  - never print, log, commit or return secrets;
  - never read `.env` contents into chat output;
  - gitleaks runs in pre-commit.
- **Network:** P0/MVP code makes **zero network calls**. Groq is P1, opt-in (`TRACE_LLM_MODE` and `TRACE_VLM_MODE` default to `off`, so the module is never imported), with `TRACE_LLM_EGRESS_ACK`, a per-case `allow_external_ai` flag, a redaction hook, a budget, and record/replay caching. Model IDs come from config, never hard-coded.
- **Logs:** never log document text, quotes, OCR text, prompts, completions, cookies or passwords. The structlog scrubber must stay on.
- **Uploads:** streaming caps (25 MB documents / 200 MB telemetry) in ASGI middleware before the body is read; magic-byte allowlist {PDF, PNG, JPEG, CSV, TXT, MD}; no SVG, TIFF or XLSX in the MVP; hash-only storage paths; the `ingestor` role.
- **Auth:** argon2id, opaque hashed sessions, `SameSite=Strict`, CSRF header + JSON on every write (login included), Origin check, loopback binding (LAN needs TLS).
- **Container:** non-root, read-only rootfs, tmpfs `/tmp`, `cap_drop ALL`, no-new-privileges, pinned digests.

## Phase discipline
1. **The MVP P0 comes first.** No P1 feature before the h26 gate, and only if the Demos 0–6 goldens are green. Stretch work is flag-gated and off by default.
2. **P1 order:** SSE → Ed25519 (off-box key) → Groq VLM second reader → recalibration → load bins → Groq LLM + verifier → XLSX.
3. **Pilot phases P1–P4** follow IMPLEMENTATION_PLAN §E. The pilot is single tenant; SaaS (P5) is an outline only.
4. **The holdout eval runs once.** Never run `holdout`-marked tests outside `make eval-holdout`, and never tune on holdout seeds.

## Definition of Done (task)
- A non-author has reviewed the change.
- `make check` is green.
- The named tests exist and pass.
- There are no demo literals, no secrets or document text in logs, and no network calls.
- There is no contract change without a CCR.
- The UI badges carry text labels (uncalibrated, synthetic, planted).

## Ask the user before you
- change thresholds or config values (`τ_link`, `δ_link`, `τ_review`, α, tolerances, envelope params, ontology quantifiers);
- touch append-only triggers, the hash chain, `canonical.py`, the ID derivation or `canon_version`;
- add, remove or upgrade a dependency, or change a base image digest;
- edit the PRD, ADRs or HARDENING, or re-bless goldens whose values changed;
- enable any network or AI provider call, or send data off the machine;
- run `make eval-holdout`, `make anchor` (it pushes), or any `git push`, history rewrite or destructive DB operation.
