# SAMANVAY — Build Status

*Audited 11 September 2026 against the repository, not from memory. Monthly horizon added same day.*
Code in place: **~3,270 lines Python, ~1,910 lines TypeScript/CSS. Zero tests.**

---

## The headline number depends on what you are measuring against

A single percentage would be misleading, so here are the three that matter.

| Denominator | Complete | What it means |
|---|---:|---|
| **Demo / prototype for the finals** | **~85%** | Runs end to end, produces measured results, has a UI a judge can drive |
| **The problem statement's four stated requirements** | **~75%** | Three met, one partly (integration) |
| **A system that could be piloted on a division** | **~25%** | No real integration, no persistence, no auth, no audit, no tests |

**If someone asks one number, say ~75%** — that is the honest answer against what
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

### 2. AI/ML to prioritise and schedule — **95%**

> *"Uses AI/ML algorithms to prioritize and schedule maintenance tasks based on
> criticality, urgency, and impact on asset availability."*

**Done** — this is the strongest part of the build.
- Criticality = P(fail within H) × Urgency(Cox expectation) × Consequence
- LightGBM classifier with documented censoring handling; Cox PH concordance ~0.77
- Ranking validated against simulator ground truth: Spearman ρ ≈ 0.61
- Quantile duration model: P50 reported, P90 reserved (demanded figure holds 16%, P90 92%)
- Goods path-demand forecast → hourly traffic cost surface
- Cancellation-risk classifier
- SHAP attribution on every task, surfaced in the UI

- **Held-out validation** - 5-fold CV on every model (`scripts/validate.py`). Caught two
  real defects: P90 coverage was 0.81 out-of-sample (now conformalised to
  0.92), and the cancellation model was overfitting at 0.57 (now logistic
  regression at 0.66, against a 0.66
  oracle ceiling).

**Not done**
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
- Measured: risk retired per block-hour **+84%** (15.49→28.52), blocks **−27%**, corridor **20%→52%**

**Not done**
- Optimality gap is time-dependent: **25.1% at 20 s, 7.4% at 90 s**; not tuned, no ALNS fallback
- Rolling nightly re-solve against realised outcomes — the feedback loop is described
  in the paper and does not exist
- No sensitivity analysis across weight settings

### 4. Weekly *and* monthly horizons — **85%**

> *"Provides block plans over multiple time horizons—weekly and monthly—to support both
> short-term and long-term maintenance."*

**Built.** Weekly at 15-minute granularity; monthly at corridor-slot granularity via
`build_monthly_candidates` + `PlanningSession.solve_monthly`, with a section × day
allocation grid and backlog burn-down in the UI. Work too long for a corridor is
surfaced as an extended-block demand list rather than silently dropped.

Outstanding: the two horizons are solved independently. A proper rolling scheme would
nest the week inside the month's allocation and re-solve nightly.

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
| Monthly horizon | ✅ | `optimizer/cpsat.py`, `session.py`, `web/.../MonthView.tsx` (216) |
| **Ingestion adapters** | ❌ | — |
| **Persistence** | ❌ | — |
| **Approval workflow / RBAC / audit** | ❌ | — |
| **Tests** | ❌ | — |
| Held-out validation | ✅ | `validation.py`, `scripts/validate.py` |

---

## Backlog, in the order I would do it

### Tier 1 — before anyone quotes a number at you

1. **A test suite.** At minimum: the optimiser never emits overlapping blocks on one
   section/line; pins are always honoured or refused; baseline and optimised see
   identical constraints; the payload shape is stable. Zero tests today, on a codebase
   where I have already found four real bugs by hand. *~1 day.*

### Tier 2 — makes it a system rather than a study

3. **Ingestion adapters** with the three-mode degradation, against a mock TMS/SMMS/TDMS.
   Even one real adapter against a CSV drop converts "we designed for integration" into
   "we integrated". *~1–2 days.*
4. **Persistence.** PostgreSQL + PostGIS; stop regenerating the estate every run. Also
   removes the fixed `seed=42` limitation — the service currently always plans the same
   world. *~1–2 days.*
5. **Approval workflow + audit trail.** Plan → departmental concurrence → sanction, with
   an immutable record of what was recommended, what was changed and by whom. This is
   what makes the human-in-the-loop claim real rather than rhetorical. *~2 days.*

### Tier 3 — scope for the pitch, not the prototype

6. Rolling nightly re-solve against realised outcomes, closing the learning loop
7. Solver tuning: shrink the 17% gap; ALNS fallback for division-scale instances
8. RBAC against IR LDAP; multi-division; resource pooling across divisions
9. BDMS write-back; condition-monitoring telemetry; live COA feed

---

## Known weaknesses to disclose before someone finds them

These are all documented in the README and most are visible in the UI. Saying them
first reads as rigour; being caught on them does not.

- **No live railway data.** Everything is synthetic, modelled on published intervals.
- **Cancellation risk is near the information ceiling** - a weak prior, not a prediction.
- **Optimality gap depends on solver time** (25% at 20 s, 7% at 90 s) - figures are a floor.
- **Overdue task-days get ~4% worse**, because criticality outranks age. A tunable
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
