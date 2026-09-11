# SAMANVAY — Build Status

*Audited against the repository, not from memory. Every figure below is reproducible —
see "Check these claims yourself". Last updated 11 September 2026.*
**~5,408 lines Python · ~2,228 lines TypeScript/CSS · ~1,375 lines of tests · 118 tests passing.**

---

## The headline number depends on what you are measuring against

A single percentage would be misleading, so here are the three that matter.

| Denominator | Complete | What it means |
|---|---:|---|
| **Demo / prototype for the finals** | **~95%** | Runs end to end, validated, tested, UI a judge can drive |
| **The problem statement's four stated requirements** | **~95%** | All four met, plus the governance the PS implies |
| **A system that could be piloted on a division** | **~55%** | Connectors, approvals and audit exist; no persistence, no real identity |

**If someone asks one number, say ~95%** — that is the honest answer against what
PS 26027 actually asked for, and it is defensible line by line below.

---

## Against the problem statement

### 1. Integration of maintenance data with corridor and traffic data — **80%**

> *"Integration of maintenance data (defects, overdue maintenance) from TMS, SMMS, and TDMS
> with corridor block and block availability as per the Train Time Table and the goods
> trains forecast from the Control Office."*

**Done** — Unified Task Model keyed by `(section, line, chainage)`; all three departmental
schemas with correct block types (traffic / disconnection / power); working timetable,
goods forecast with per-path probability, mandated corridor windows; historical block and
defect records shaped as the real systems would expose them.

- **Adapter layer built** (`samanvay/ingestion/`). Three-mode degradation — REST →
  read-only DB view → CSV drop — against mock TMS/SMMS/TDMS in genuinely different native
  schemas (differing names, units, date formats and severity scales). Read-only by
  construction: the DB adapter refuses anything but a view. Records that cannot be mapped
  are rejected by name with a reason; degradation is reported, not hidden.
  `scripts/ingest.py` plans end to end from ingested records.

**Not done**
- The sources are mocks written by `export_all()`, not live departmental systems. The
  transport, schema translation and failure handling are real; the data behind them is not.
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

### Implicit: decentralised & manual → coordinated & data-driven — **80%**

**Built** (`samanvay/governance/`). The full route — JE → departmental concurrence →
Sr.DOM traffic clearance → DRM sanction — with authority enforced at every step, exposed
over HTTP (403 for authority, 409 for state). Every transition, **including refused
attempts**, lands in a hash-chained append-only audit log that detects any retroactive
edit and names the first broken link.

**Not done** — identity is a stand-in: roles are supplied by the caller rather than
authenticated. `_actor()` in `scripts/serve.py` is the seam a real deployment binds to
the divisional directory. And there is no approvals UI; the workflow is API-only.

---

## What exists

| Area | Status | Where |
|---|---|---|
| Domain model, topology, timetable | ✅ | `domain.py`, `network.py` |
| **Ingestion adapters (3-mode)** | ✅ | `ingestion/sources.py`, `ingestion/adapters.py` |
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
| **Approval workflow + audit trail** | ✅ | `governance/workflow.py`, `governance/audit.py` |
| **Test suite (118 tests)** | ✅ | `tests/`, `scripts/mutation_check.py` |
| Time–distance chart, month view | ✅ | `web/app/components/` |
| What-if simulator | ✅ | `web/app/components/WhatIfPanel.tsx`, `lib/whatif.ts` |
| **Persistence** | ❌ | — |
| **Real identity / RBAC binding** | ❌ | roles are caller-supplied |
| **Approvals UI** | ❌ | workflow is API-only |

### On the tests

118 tests, ~80 s. They cover governance (only the DRM sanctions, heads concur only
for their own department, the sanction gate, tamper detection on the audit chain),
ingestion (round-trip fidelity, metres→km conversion,
the inverted SMMS priority scale, degradation, read-only discipline, rejection by name),
solver invariants (line exclusivity, one gang per department
per block, plant positioning, staff caps, night-work rules, horizon bounds), pinning
(honoured exactly or refused by name), payload shape from both producers, model behaviour
including a **ground-truth leakage guard**, and generator calibration.

`scripts/mutation_check.py` re-applies **eleven** defects this project actually shipped
and confirms a test goes red for each — **11/11 caught**. Among them: the clubbing
constraint that made the model INFEASIBLE, the disabled conformal offset, ground truth in
a feature set, the 10× duration calibration error, the two silent ingestion corruptions
that raise no exception (metres read as kilometres, the un-inverted priority scale), an
authority check removed so anyone could sanction, and a chain verifier rigged to always
pass.

A suite that passes proves nothing on its own; it may simply be unable to fail. Writing
this check found exactly that: the plant-positioning test read the same constant it was
validating, so zeroing the constant relaxed the assertion too and the mutation walked
straight through. It now asserts an independent floor.

---

## Backlog, in the order I would do it

### Tier 1 — makes it a system rather than a study

1. **An approvals UI.** The route is enforced and exposed over HTTP, but a Sr.DEN cannot
   use it without curl — so the governance layer is currently describable rather than
   demonstrable. A queue view with concur / withhold / return, and the audit trail beside
   the plan it belongs to. *~1 day, and the highest-value day left.*
2. **Persistence.** PostgreSQL + PostGIS; stop regenerating the estate every run. Also
   removes the fixed `seed=42` limitation — the service always plans the same world. *~1–2 days.*
3. **Bind identity to the divisional directory.** The workflow rules are enforced; *who you
   are* is currently whatever you claim. LDAP or SSO behind `_actor()` closes it, and until
   it does, the authority model is a convention rather than a control. *~1 day.*
4. **Point an adapter at something real.** The transport and translation work; only the
   data behind them is mocked. A single live read-only view or SFTP drop from an actual
   departmental system would close the last of requirement 1. *~1 day, mostly access.*

### Tier 2 — depth

5. Rolling nightly re-solve against realised outcomes, closing the learning loop
6. Nest the weekly plan inside the monthly allocation instead of solving them independently
7. Solver tuning: shrink the gap at short time limits; ALNS fallback for division scale
8. Multi-division; resource pooling across divisional boundaries

### Tier 3 — pitch scope

9. BDMS write-back; condition-monitoring telemetry; live COA feed

---

## Check these claims yourself

Nothing above should be taken on trust. Every number in this document comes from one of:

```bash
python -m pytest                    # 118 tests, ~80 s
python scripts/mutation_check.py    # 11/11 — proves the tests can fail
python scripts/validate.py          # held-out model performance, 5-fold
python scripts/run_pipeline.py --days 7 --tasks 200 --time-limit 90 --monthly --validate
python scripts/ingest.py            # native schemas -> UTM -> plan
python scripts/serve.py             # then POST the approval route
```

The pipeline writes `out/plan.json`; the weekly, monthly and validation figures quoted
here are read straight out of it. If a number here disagrees with a fresh run, the run is
right and this file is stale.

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

The hard part is built, validated and tested: the data model, adapters over three native
schemas, four models that beat a baseline on held-out data, a solver that finds
cross-departmental clubbing across two horizons, an approval route that refuses anyone
reaching past their authority, and a UI a planner can argue with.

What remains is narrower than it was and mostly unglamorous: storage, a real identity
binding, an approvals screen, and pointing the connectors — which exist and are tested —
at something other than a mock.

**The honest framing for a judge.** Every mechanism the problem statement asks for exists
and is tested. Three of them are wired to stand-ins rather than the real thing: the source
data is generated, the identities are asserted, and the estate lives in memory. Those are
deployment work, not research risk — but they are the difference between a system that
demonstrates and a system that runs.

For a hackathon prototype this is comfortably past where it needs to be. For a divisional
pilot it is roughly halfway.
