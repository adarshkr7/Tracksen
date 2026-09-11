# SAMANVAY — Build Status

*Audited against the repository, not from memory. Last updated 11 September 2026.*
**~3,946 lines Python · ~2,228 lines TypeScript/CSS · ~830 lines of tests · 70 tests passing.**

---

## The headline number depends on what you are measuring against

A single percentage would be misleading, so here are the three that matter.

| Denominator | Complete | What it means |
|---|---:|---|
| **Demo / prototype for the finals** | **~95%** | Runs end to end, validated, tested, UI a judge can drive |
| **The problem statement's four stated requirements** | **~80%** | Three met in full, integration partly |
| **A system that could be piloted on a division** | **~30%** | No real connectors, no persistence, no auth, no audit trail |

**If someone asks one number, say ~80%** — that is the honest answer against what
PS 26027 actually asked for, and it is defensible line by line below.

---

## Against the problem statement

### 1. Integration of maintenance data with corridor and traffic data — **40%**

> *"Integration of maintenance data (defects, overdue maintenance) from TMS, SMMS, and TDMS
> with corridor block and block availability as per the Train Time Table and the goods
> trains forecast from the Control Office."*

**Done** — Unified Task Model keyed by `(section, line, chainage)`; all three departmental
schemas with correct block types (traffic / disconnection / power); working timetable,
goods forecast with per-path probability, mandated corridor windows; historical block and
defect records shaped as the real systems would expose them.

**Not done** — **this is the remaining gap.**
- **No adapters.** `services/ingestion/` was in the plan and does not exist. Every feed is
  synthetic. The three-mode degradation (REST → read-only DB view → SFTP CSV) is a design,
  not code.
- No persistence — no PostgreSQL, no PostGIS, no TimescaleDB. In-memory, regenerated per run.
- No BDMS write-back.

### 2. AI/ML to prioritise and schedule — **95%**

**Done**
- Criticality = P(fail within H) × Urgency(Cox expectation) × Consequence
- **Held-out validated** (5-fold): classifier AUC **0.826 ± 0.017**
  against 0.665 majority-class; Cox concordance
  **0.765 ± 0.035**
- Duration P50/P90, **conformalised** — held-out coverage **0.924** against a 0.90 target
- Cancellation risk at **0.663** against a **0.662** oracle ceiling
- Goods path-demand forecast → hourly traffic cost surface
- SHAP attribution on every task, surfaced in the UI

**Not done** — no MLflow / model registry / drift monitoring.

### 3. Optimise block scheduling, coordinate departments — **85%**

**Done** — CP-SAT with interval variables and `NoOverlap` per section and line; clubbing via
one constraint (≤1 task per department per block) plus an objective bonus; plant positioning,
staff caps, night-work rules, corridor policy, statutory deadlines; FCFS baseline under
identical physical constraints; pinned placements and re-solve.

Measured: risk retired per block-hour **15.13→28.12 (+86%)**,
blocks **−22%**, corridor adherence **20%→61%**,
high-criticality failures **24→20**.

**Not done**
- Optimality gap is time-dependent: **25.1% at 20 s, 7.4% at 90 s**. Not tuned; no ALNS fallback.
- Rolling nightly re-solve against realised outcomes does not exist.
- No sensitivity analysis across weight settings.

### 4. Weekly *and* monthly horizons — **85%**

**Done** — weekly at 15-minute granularity; monthly at corridor-slot granularity
(93/420 slots allocated over 30 days, backlog
187 → 93). Work too long for a corridor
(81 tasks) is surfaced as an extended-block demand list rather than
silently dropped.

**Not done** — the two horizons are solved independently. A proper rolling scheme would nest
the week inside the month's allocation and re-solve nightly.

### Implicit: decentralised & manual → coordinated & data-driven — **25%**

The analysis layer is there; the *process* layer is not. No approval workflow
(JE → Sr.DEN/DSTE/Sr.DEE → Sr.DOM → DRM), no role-based access, no audit trail, no user
accounts. The system currently advises one anonymous operator.

---

## What exists

| Area | Status | Where |
|---|---|---|
| Domain model, topology, timetable | ✅ | `domain.py`, `network.py` |
| Synthetic TMS/SMMS/TDMS feeds | ✅ | `generator.py` |
| Traffic cost surface | ✅ | `models/traffic.py` |
| Criticality + Cox + SHAP | ✅ | `models/criticality.py` |
| Duration P50/P90 (conformalised) | ✅ | `models/duration.py` |
| Cancellation risk | ✅ | `models/cancellation.py` |
| CP-SAT scheduler, weekly + monthly | ✅ | `optimizer/cpsat.py` |
| FCFS baseline | ✅ | `optimizer/baseline.py` |
| KPI evaluation | ✅ | `evaluate.py` |
| Session, pinning, re-solve | ✅ | `session.py`, `scripts/serve.py` |
| Held-out validation | ✅ | `validation.py`, `scripts/validate.py` |
| **Test suite (70 tests)** | ✅ | `tests/`, `scripts/mutation_check.py` |
| Time–distance chart, month view | ✅ | `web/app/components/` |
| What-if simulator | ✅ | `web/app/components/WhatIfPanel.tsx`, `lib/whatif.ts` |
| **Ingestion adapters** | ❌ | — |
| **Persistence** | ❌ | — |
| **Approval workflow / RBAC / audit** | ❌ | — |

### On the tests

70 tests, ~80 s. They cover solver invariants (line exclusivity, one gang per department
per block, plant positioning, staff caps, night-work rules, horizon bounds), pinning
(honoured exactly or refused by name), payload shape from both producers, model behaviour
including a **ground-truth leakage guard**, and generator calibration.

`scripts/mutation_check.py` re-applies five defects this project actually shipped and
confirms a test goes red for each — **5/5 caught**. Writing it found a sixth problem: the
plant-positioning test read the same constant it was validating, so zeroing the constant
relaxed the test too and the mutation walked straight through. It now asserts an
independent floor.

---

## Backlog, in the order I would do it

### Tier 1 — makes it a system rather than a study

1. **Ingestion adapters** with three-mode degradation against a mock TMS/SMMS/TDMS. Even one
   real adapter against a CSV drop converts "we designed for integration" into "we
   integrated". This is the single biggest remaining gap against the PS. *~1–2 days.*
2. **Persistence.** PostgreSQL + PostGIS; stop regenerating the estate every run. Also
   removes the fixed `seed=42` limitation — the service always plans the same world. *~1–2 days.*
3. **Approval workflow + audit trail.** Plan → departmental concurrence → sanction, with an
   immutable record of what was recommended, what changed and by whom. This is what makes
   the human-in-the-loop claim real rather than rhetorical. *~2 days.*

### Tier 2 — depth

4. Rolling nightly re-solve against realised outcomes, closing the learning loop
5. Nest the weekly plan inside the monthly allocation instead of solving them independently
6. Solver tuning: shrink the gap at short time limits; ALNS fallback for division scale
7. RBAC against IR LDAP; multi-division; resource pooling

### Tier 3 — pitch scope

8. BDMS write-back; condition-monitoring telemetry; live COA feed

---

## Disclose these before someone finds them

- **No live railway data.** Everything synthetic, modelled on published intervals.
- **Optimality gap depends on solver time** (25% at 20 s, 7% at 90 s) — figures are a floor.
- **Overdue task-days get ~2% worse**, because criticality outranks age. A tunable trade-off.
- **Cancellation risk is near the information ceiling** — a weak prior, not a prediction.
- **Consequence weighting barely discriminates** (0.87–0.98) on a single trunk corridor.
- **What-if deferral risk uses an exponential-hazard approximation** of the Cox model.
- **Fixed seed** — the service always plans the same 7-day,
  200-task world.

---

## Bottom line

The hard part is built, validated and tested: the data model, four models that beat a
baseline on held-out data, a solver that finds cross-departmental clubbing over two
horizons, and a UI a planner can argue with. What remains is mostly the unglamorous half —
real connectors, storage, workflow.

For a hackathon prototype this is comfortably past where it needs to be. For a divisional
pilot it is roughly a third of the way.
