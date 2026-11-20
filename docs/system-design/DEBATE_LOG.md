# TRACE — Debate Log

A condensed record of how every architecture decision was fought out. The raw round files are in [`debate/`](debate/).

## Format

```
  Round 1 (parallel, independent)      Round 2 (each reads the other two)     Round 3
 ┌───────────────┐                    ┌───────────────┐                     ┌─────────────────┐
 │ ARCHITECT     │── position ──┐  ┌─►│ rebut/concede │──┐                  │ JUDGE (fresh,   │
 │ prod-grade    │              │  │  └───────────────┘  │                  │ independent)    │
 └───────────────┘              │  │  ┌───────────────┐  │   all 6 papers   │ binding verdict │
 ┌───────────────┐              ├──┼─►│ rebut/concede │──┼────────────────► │ per decision;   │
 │ PRAGMATIST    │── position ──┤  │  └───────────────┘  │   + PRD          │ checks consensus│
 │ 36 h, 4 ppl   │              │  │  ┌───────────────┐  │                  │ too, not just   │
 └───────────────┘              │  └─►│ rebut/concede │──┘                  │ disputes        │
 ┌───────────────┐              │     └───────────────┘                     └─────────────────┘
 │ RED TEAM      │── position ──┘
 │ attack+judge  │
 └───────────────┘
```

| File | Content |
|---|---|
| [`debate/r1_architect.md`](debate/r1_architect.md) | R1 Architect: 13 positions + 10 PRD weak spots |
| [`debate/r1_pragmatist.md`](debate/r1_pragmatist.md) | R1 Pragmatist: 13 positions + hour ledger + 10 demo risks |
| [`debate/r1_redteam.md`](debate/r1_redteam.md) | R1 Red Team: 13 positions + 38 STRIDE threats + 10 judge questions |
| [`debate/r2_architect.md`](debate/r2_architect.md) | R2 Architect rebuttal |
| [`debate/r2_pragmatist.md`](debate/r2_pragmatist.md) | R2 Pragmatist rebuttal |
| [`debate/r2_redteam.md`](debate/r2_redteam.md) | R2 Red Team rebuttal + P0 floor |
| [`debate/r3_judge.md`](debate/r3_judge.md) | **Binding verdict:** 15 items, threat register, hour ledger, 29 PRD changes, judge Q&A |

---

## How each decision moved

| # | Decision | Architect R1 → R2 | Pragmatist R1 → R2 | Red Team R1 → R2 | **Judge** |
|---|---|---|---|---|---|
| 1 | Shape | Hexagonal monolith → kept | Monolith + 4 ports → kept | Monolith + sandboxed parser → kept | **Hexagonal monolith, pure core, import-linter.** Agreement verified. |
| 2 | Execution | Postgres queue (Procrastinate) → **conceded**, process pool | BackgroundTasks → **conceded**, process pool | Job row + heartbeat → kept | **Killable spawn child + heartbeat row.** Process pool rejected: it can't kill a hung worker. |
| 3 | Storage | Postgres 16 → **conceded** to SQLite | SQLite + triggers → kept | SQLite (one file) → kept | **One SQLite file, triggers, `version_claims`, derived status** (new bug found by the Judge). |
| 4 | Integrity | Merkle + Ed25519 → **conceded**, chain; Ed25519 to P1 | Chain; Ed25519 at h28 → kept | Chain; "key on same box proves nothing" | **Chain + snapshot hash + *pushed* anchor.** Ed25519 P1, only off-box. |
| 5 | Determinism | Content IDs, cached OCR → kept | Same + injected clock → kept | Same | **Agreed.** Added a cache-miss-is-error rule and an honesty clause. |
| 6 | Extraction | PyMuPDF + pdf.js → **conceded** to PNG | PyMuPDF + PNG → kept | pdfplumber → **conceded**; simplified quote check | **PyMuPDF (AGPL, U-1) + PNG + pixel hidden-text guard.** Value re-derivation **restored**. |
| 7 | Entities/time | Transposition feature, mention key | rapidfuzz top-3 | No auto-link from string alone | **Score + margin + non-string feature + serial veto; `plant_tz`; mtime never used.** |
| 8 | Frontend | Astro SSR, pdf.js, nanostores → **conceded** | Static, one island/page → kept | Static, strict CSP, SSE → kept | **Static Astro, same origin, one `client:only` island per page, SSE P1.** |
| 9 | API | `public, immutable`; cursors; Idempotency-Key → partly conceded | Offset; ETag → kept | `private`; IDOR; 409 → kept | **Case-scoped; `private, immutable` + `Vary: Cookie`; 409 only on already-decided or evidence-changed** (tightened). |
| 10 | Auth | Session cookie + roles → seeded argon2 users | Pick-a-name → **conceded** to argon2 | Session; R2 per-role PIN + localhost | **Per-user argon2id + localhost.** PIN lost because it breaks individual attribution. |
| 11 | Observability | OTel + Prometheus → **conceded** to P1 | structlog + build-row metrics → kept | No document text in logs | **structlog + per-stage metrics in the expert view; OTel P1.** |
| 12 | Testing | Goldens, Hypothesis, Schemathesis, Playwright | pytest, never-average, 1 Playwright | Hostile corpus, eval hygiene | **All of it**, minus Schemathesis (P1). **Wilson CI false-alarm test.** |
| 13 | Deployment | Compose; CDN is the real 1M answer; Citus weakest | One Compose service; Kafka/Citus not earned | Signed images later | **One image; scale components "planned only if" each hits its trigger.** |
| 14 | Correctness floor | (R2) robust z, empirical p95, before-only | (R2) accepted the Red Team's fixes, held-out 5% | **Found T-01 to T-05** | **Split-conformal max-z, T\* = T_(⌈0.95(n+1)⌉); demo trains on all days except the case window** (overruled before-only). |
| 15 | Security floor | — | +2.5 h auth, sandbox | Floor ~8.5 h; "disable uploads in demo" option | **Uploads on, `ingestor`-only, hardened (~1.5 h)**; full S1–S11. |

---

## Where the Judge overruled or tightened the agreement

1. **Envelope threshold.** An empirical p95 of robust z was replaced by a **split-conformal** order statistic. It gives a provable ≤ α false-alarm bound with no Bonferroni guesswork.
2. **Training days.** "Before-only" leaves about 14 quiet days, below n = 19. **All days except the case window ±3 d** is used for retrospective cases; before-only applies in live production.
3. **Execution.** `ProcessPoolExecutor` was replaced by a **killable spawn process**.
4. **409 semantics.** Not on a stale `base_version` alone (that would block unrelated decisions). Only when the item is **already decided** or its **evidence changed**.
5. **Anchor.** A local git commit is not enough; the anchor must be **pushed** to the remote.
6. **Auth.** Per-user passwords beat per-role PINs, because attribution is individual.

## New issues found only in Round 3
- **N-1:** mutable `status` inside immutable records.
- **N-2:** a local anchor is rewritable.
- **N-3:** the conformal threshold is undefined for n < 19.
- **N-4:** the baseline score "0.62" is typed in.
- **C-17 confidence:** computes to 0.83, not 0.71.

## Biggest single finding
The **Red Team's T-01**. The PRD's "every hourly value inside p5–p95" rule makes almost every quiet day a conflict. Left in, the demo would work on Machine 21 on 14 March and fail on the first other day a judge picked. All three agents and the Judge treated the fix as the top priority in P0.
