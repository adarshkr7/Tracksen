# SAMANVAY — Build Status

*Audited 11 September 2026 against the repository, not from memory.*
Code in place: **~3,270 lines Python, ~1,910 lines TypeScript/CSS. Zero tests.**

---

## The headline number depends on what you are measuring against

A single percentage would be misleading, so here are the three that matter.

| Denominator | Complete | What it means |
|---|---:|---|
| **Demo / prototype for the finals** | **~85%** | Runs end to end, produces measured results, has a UI a judge can drive |
| **The problem statement's four stated requirements** | **~65%** | Two fully met, one partly, one barely started |
| **A system that could be piloted on a division** | **~20%** | No real integration, no persistence, no auth, no audit, no tests |

**If someone asks one number, say ~65%** — that is the honest answer against what
PS 26027 actually asked for, and it is the number you can defend line by line below.

---

## Against the problem statement

The PS lists four things the solution "should include". Scored individually:

### 1. Integration of maintenance data with corridor and traffic data — **40%**

> *"Integration of maintenance data (defects, overdue maintenance) from TMS, SMMS, and TDMS
> with corridor block and block availability as per the Train Time Table and the goods
> trains forecast from the Control Office."*

**Done**
- Unified Task Model keyed by `(section, line, chainage)` — the normalisation target
- Departmental schemas modelled for all three systems with correct block types
  (traffic / disconnection / power)
- Working timetable, goods forecast with per-path probability, mandated corridor windows
- Historical block and defect records in the shape the real systems would expose

**Not done**
- **No actual adapters.** `services/ingestion/` was in the plan and does not exist. Every
  feed is synthetic. The three-mode degradation (REST → read-only DB view → SFTP CSV) is
  a design, not code.
- No persistence at all — no PostgreSQL, no PostGIS, no TimescaleDB. Everything is
  in-memory and regenerated per run.
- No BDMS write-back.

### 2. AI/ML to prioritise and schedule — **90%**

> *"Uses AI/ML algorithms to prioritize and schedule maintenance tasks based on
> criticality, urgency, and impact on asset availability."*

**Done** — this is the strongest part of the build.
- Criticality = P(fail within H) × Urgency(Cox expectation) × Consequence
- LightGBM classifier with documented censoring handling; Cox PH concordance ~0.77
- Ranking validated against simulator ground truth: Spearman ρ ≈ 0.61
- Quantile duration model: P50 reported, P90 reserved (demanded figure holds 12%, P90 92%)
- Goods path-demand forecast → hourly traffic cost surface
- Cancellation-risk classifier
- SHAP attribution on every task, surfaced in the UI

**Not done**
- **Held-out validation.** All diagnostics are in-sample. This is the single most
  quotable weakness and the first thing to fix.
- No MLflow / model registry / drift monitoring.

### 3. Optimise block scheduling, coordinate departments — **85%**

> *"Optimize block scheduling to maximize asset uptime by minimizing downtime and
> efficiently coordinating multi-department activities."*

**Done**
- OR-Tools CP-SAT with interval variables, `NoOverlap` per section and line
- Clubbing via one constraint (≤1 task per department per block) + objective bonus
- Plant positioning, staff caps, night-work rules, corridor policy, statutory deadlines
- FCFS baseline reproducing current practice under identical physical constraints
- Pinned placements — re-solve holding a planner's moves fixed
- Measured: risk retired per block-hour **+47%**, blocks **−24%**, corridor **22%→53%**

**Not done**
- Solver stops at a **~17% optimality gap** in 45s; not tuned, no ALNS fallback
- Rolling nightly re-solve against realised outcomes — the feedback loop is described
  in the paper and does not exist
- No sensitivity analysis across weight settings

### 4. Weekly *and* monthly horizons — **35%**

> *"Provides block plans over multiple time horizons—weekly and monthly—to support both
> short-term and long-term maintenance."*

**This is the biggest gap against the PS.** The weekly plan at 15-minute granularity is
built and working. The monthly plan at corridor-slot granularity **does not exist** —
a single comment in `models/traffic.py` mentions it and nothing implements it. The
architecture accommodates it (the solver is horizon-parameterised), but no one has run
it, and there is no monthly view in the UI.

### Implicit requirement: decentralised & manual → coordinated & data-driven — **25%**

The analysis layer is there; the *process* layer is not. No approval workflow
(JE → Sr.DEN/DSTE/Sr.DEE → Sr.DOM → DRM), no role-based access, no audit trail, no
user accounts. The system currently advises one anonymous operator.

---

## What exists, by file

| Area | Status | Files |
|---|---|---|
| Domain model | ✅ | `domain.py` (353) |
| Topology, timetable, corridor | ✅ | `network.py` (236) |
| Synthetic feeds | ✅ | `generator.py` (457) |
| Traffic cost surface | ✅ | `models/traffic.py` (134) |
| Criticality + SHAP | ✅ | `models/criticality.py` (324) |
| Duration P50/P90 | ✅ | `models/duration.py` (147) |
| Cancellation risk | ✅ | `models/cancellation.py` (119) |
| CP-SAT scheduler | ✅ | `optimizer/cpsat.py` (493) |
| FCFS baseline | ✅ | `optimizer/baseline.py` (119) |
| KPI evaluation | ✅ | `evaluate.py` (194) |
| Session + pinning | ✅ | `session.py` (239) |
| Payload builder | ✅ | `serialize.py` (128) |
| Pipeline CLI | ✅ | `scripts/run_pipeline.py` (204) |
| Re-solve API | ✅ | `scripts/serve.py` (119) |
| Time–distance chart | ✅ | `web/.../TimeDistanceChart.tsx` (357) |
| What-if simulator | ✅ | `web/.../WhatIfPanel.tsx` (286), `lib/whatif.ts` (284) |
| Priority queue | ✅ | `web/.../TaskQueue.tsx` (141) |
| KPI strip | ✅ | `web/.../KpiStrip.tsx` (104) |
| **Monthly horizon** | ❌ | — |
| **Ingestion adapters** | ❌ | — |
| **Persistence** | ❌ | — |
| **Approval workflow / RBAC / audit** | ❌ | — |
| **Tests** | ❌ | — |
| **Held-out validation** | ❌ | — |

---

## Backlog, in the order I would do it

### Tier 1 — before anyone quotes a number at you

1. **Held-out validation** for all four models. Train/test split with fixed seed, report
   out-of-sample AUC, P90 coverage and Spearman ρ. Every diagnostic on the page today is
   in-sample and a judge who asks will find it in thirty seconds. *~half a day.*
2. **Monthly horizon.** 30-day plan at corridor-slot granularity, plus a section × day
   load view in the UI. This is an explicit PS requirement currently unmet. *~1 day.*
3. **A test suite.** At minimum: the optimiser never emits overlapping blocks on one
   section/line; pins are always honoured or refused; baseline and optimised see
   identical constraints; the payload shape is stable. Zero tests today, on a codebase
   where I have already found three real bugs by hand. *~1 day.*

### Tier 2 — makes it a system rather than a study

4. **Ingestion adapters** with the three-mode degradation, against a mock TMS/SMMS/TDMS.
   Even one real adapter against a CSV drop converts "we designed for integration" into
   "we integrated". *~1–2 days.*
5. **Persistence.** PostgreSQL + PostGIS; stop regenerating the estate every run. Also
   removes the fixed `seed=42` limitation — the service currently always plans the same
   world. *~1–2 days.*
6. **Approval workflow + audit trail.** Plan → departmental concurrence → sanction, with
   an immutable record of what was recommended, what was changed and by whom. This is
   what makes the human-in-the-loop claim real rather than rhetorical. *~2 days.*

### Tier 3 — scope for the pitch, not the prototype

7. Rolling nightly re-solve against realised outcomes, closing the learning loop
8. Solver tuning: shrink the 17% gap; ALNS fallback for division-scale instances
9. RBAC against IR LDAP; multi-division; resource pooling across divisions
10. BDMS write-back; condition-monitoring telemetry; live COA feed

---

## Known weaknesses to disclose before someone finds them

These are all documented in the README and most are visible in the UI. Saying them
first reads as rigour; being caught on them does not.

- **No live railway data.** Everything is synthetic, modelled on published intervals.
- **In-sample diagnostics only.**
- **~17% optimality gap** — reported figures are a floor.
- **Overdue task-days get 6–7% worse**, because criticality outranks age. A tunable
  trade-off, not a defect.
- **Consequence weighting barely discriminates** (0.87–0.98) on a single trunk corridor.
- **The what-if deferral risk uses an exponential-hazard approximation** of the Cox
  model, not a re-derivation.
- **Fixed seed** — the service always plans the same 7-day, 200-task world.

---

## Bottom line

What is built is the hard part and it works: the data model, four models that measurably
beat a baseline, a solver that finds cross-departmental clubbing, and a UI that lets a
planner argue with it. What is missing is mostly the unglamorous half — real connectors,
storage, workflow, tests — plus one genuine PS requirement (the monthly horizon).

For a hackathon prototype this is comfortably ahead of where it needs to be. For a
divisional pilot it is roughly a fifth of the way.
