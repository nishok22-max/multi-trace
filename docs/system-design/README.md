# TRACE — System Design Pack

*Every fact has an address. Every conflict stays visible.*

**Stack:**
- **Backend:** Python 3.11, FastAPI, Pydantic v2.
- **Frontend:** Astro (static output), Tailwind CSS, React islands via `@astrojs/react`.

Yes, Astro uses React components directly: each page mounts one `client:only="react"` island.

## Documents
| File | What it is |
|---|---|
| [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) | The architecture: 23 sections with ASCII diagrams |
| [`DECISIONS.md`](DECISIONS.md) | 15 ADRs, each with the debate, verdict, P0/P1/P2, residual risk and "would change if" |
| [`HARDENING.md`](HARDENING.md) | Trust boundaries, STRIDE, correctness floor, security register (44 threats with named tests), PRD weak spots, pre-demo checklist |
| [`DEBATE_LOG.md`](DEBATE_LOG.md) | How each decision moved across the 3 rounds, and where the Judge overruled |
| [`debate/`](debate/) | Raw round files: Architect, Pragmatist, Red Team (R1, R2) and the Judge's binding verdict (R3) |
| [`../TRACE_PRD.md`](../TRACE_PRD.md) | Product requirements (v1.1) |

## One-page picture

```
                    ┌────────────────────────── one Linux container ───────────────────────────┐
  Browser           │  FastAPI ─ serves Astro dist/ (same origin) + /api/v1 (OpenAPI 3.1)      │
  Astro + Tailwind ─┼─► sessions(argon2id) · CSRF · RBAC · upload caps · CSP · problem+json   │
  React islands     │      │ sync decision re-run (<2 s)          │ spawn, killable (180 s)     │
  TanStack Query    │      ▼                                      ▼                             │
  ECharts · PNG     │  ┌──────────────────── trace_core (pure) ─────────────────────────┐       │
  proof overlays    │  │ READ → NORMALISE → [review hold] → COMPARE (6 checks) → SCORE   │       │
                    │  │ → SNAPSHOT (record hashes → chained manifest_hash)              │       │
                    │  └─────────────────────────────────────────────────────────────────┘       │
                    │  SQLite WAL (append-only triggers) · blobs by sha256 · Parquet/machine     │
                    └──────────────────────────────────────────────────────┬────────────────────┘
                                                            manifest roots │ git push
                                                                           ▼ remote anchor
   Promises enforced by design:  never averaged · no data ≠ normal · units never guessed ·
   every fact has an address · LLM proposes, rules decide · same inputs → same bytes
```

## The five decisions that matter most
1. **"Normal" is a split-conformal robust max-z threshold.** It bounds false alarms on quiet days at ≤ 5%. The PRD's p5–p95 hourly rule would flag almost every day.
2. **Telemetry units are `sensor_native`.** The dataset documents none, so TRACE never guesses them.
3. **Append-only and tamper-evident.** SQLite triggers, a hash chain, and the root hash pushed to a remote git repository.
4. **Identity comes only from the session.** Decisions can't be forged, and racing reviewers get exactly one winner.
5. **A million readers is a cache problem.** Frozen versions sit behind an authorised edge cache, and every other scale component must earn its place.

## Confirmations
- **U-1 (decided):** use pypdfium2 (permissive), not PyMuPDF.
- **U-3 (decided):** Groq is the P1 and pilot LLM/VLM provider. The key goes in `.env`, and the core build needs zero network.
- **U-2 (open):** Is an outside labeller available? If not, person D labels, and this is disclosed.
