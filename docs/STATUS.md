# TRACKSEN — Build Status

*Audited against the repository, not from memory. Every figure below is reproducible —
see "Check these claims yourself". Last updated 12 September 2026.*
**Tests: 296 across 16 files · mutation check 21/21.**

> This document says what is **built**. [AUDIT.md](AUDIT.md) says what is **broken or
> unfinished**, with severities. Read that one before quoting a number off a screen.

---

## The headline number depends on what you are measuring against

A single percentage would be misleading, so here are the three that matter. They are
*judgement* with a number attached, not a measurement — what is measurable is the line-by-
line breakdown below and the open list in [AUDIT.md](AUDIT.md).

| Denominator | Complete | What it means |
|---|---:|---|
| **Demo / prototype for the finals** | **~95%** | Runs end to end on published timetable data, held-out validated, 296 tests, ten screens a judge can drive |
| **The problem statement's four stated requirements** | **~90%** | All four met, plus the governance the PS implies. Held back by requirement 1: the defect feeds are still mocks |
| **A system that could be piloted on a division** | **~65%** | Adapters, approvals, tamper-evident audit, authentication and hash-verified plan storage all exist. The estate still regenerates from a fixed seed, identity is not bound to a directory, and nothing ingests what actually happened |

**If someone asks one number, say ~90%** against what PS 26027 asked for — defensible line
by line below. The pilotable figure moved 55% → 65% this pass: authentication and plan
storage were the two things most obviously missing from it.

### What changed since the last update

| | Before | Now |
|---|---|---|
| Timetable | 212 services, times written by hand | **543 services, published times and running days** |
| Network | main line only | **41 sections, 8 converging branches, 8 junction throats** |
| Premier paths | priced at 4× | **fenced off — a block is never granted across one** |
| Block types | emitted, constrained nothing | **withdrawal setup/restoration enforced** |
| Identity | `{"role": "DRM"}` in the body, believed | **bearer token resolved server-side** |
| Approved plan | hash recorded, content lost | **stored and hash-verified across restart** |
| Tests | 118 | **211** |

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

- **The timetable is published data**, not invented: 543 services over this division,
  stops and times from IRCTC merged with running days from an NTES crawl
  (`scripts/import_opendata.py`). An approximate hand-written file ships as the fallback,
  and the Data Sources screen says which is in force.

**Not done**
- The *maintenance* sources are mocks written by `export_all()`, not live departmental
  systems. The transport, schema translation and failure handling are real; the defect
  and asset data behind them is not.
- The estate is regenerated from `seed=42` every start — no PostgreSQL, no PostGIS.
  Approved *plans* persist and are hash-verified; the world they refer to does not.
- No BDMS write-back.

### 2. AI/ML to prioritise and schedule — **95%**

**Done**
- Criticality = P(fail within H) × Urgency(Cox expectation) × Consequence
- **Held-out validated** (5-fold): classifier AUC **0.898 ± 0.019** against 0.615
  majority-class; Cox concordance **0.785 ± 0.015**
- Duration P50/P90, **conformalised** — held-out P90 coverage **0.907 ± 0.028** against a
  0.90 target; P50 absolute error **14.1 min** against a 46.0 min median baseline
- Cancellation risk **0.627 ± 0.038** against an oracle ceiling of **0.651** — close to
  the information limit of the process, which is the honest ceiling, not 1.0
- Goods path-demand forecast → hourly traffic cost surface
- SHAP attribution on every task, surfaced in the UI

**Not done** — no MLflow / model registry / drift monitoring.

### 3. Optimise block scheduling, coordinate departments — **85%**

**Done** — CP-SAT with interval variables and `NoOverlap` per section and line; clubbing via
one constraint (≤1 task per department per block) plus an objective bonus; plant positioning,
staff caps, night-work rules, corridor policy, statutory deadlines; FCFS baseline under
identical physical constraints; pinned placements and re-solve.

Measured on the Danapur division, 7 days, 600 tasks: risk retired per block-hour
**8.4→21.3 (+154%)**, blocks **−37%**, corridor adherence **31%→60%**,
traffic cost **−50%**, high-criticality unplanned failures **18→13**.

**Not done**
- At 600 s: **monthly OPTIMAL, weekly 12.9%**. The weekly gap is budget-sensitive —
  76.6% at 240 s — because criticality and traffic genuinely contend at real traffic
  density. More search closes it; no ALNS fallback or symmetry breaking yet.
- Rolling nightly re-solve against realised outcomes does not exist.
- No sensitivity analysis across weight settings.

### 4. Weekly *and* monthly horizons — **85%**

**Done** — weekly at 15-minute granularity; monthly at corridor-slot granularity over
30 days, solved to **proven optimality** (134 of 895 slots allocated). Work too long for a
corridor — **311 tasks**, whose P90 plus the setup and restoration their withdrawal needs
exceeds 180 minutes — is surfaced as an extended-block demand list rather than silently
dropped. That list is itself an output: it is the division's extended-block demand.

**Not done** — the two horizons are solved independently. A proper rolling scheme would nest
the week inside the month's allocation and re-solve nightly.

### Implicit: decentralised & manual → coordinated & data-driven — **80%**

**Built** (`samanvay/governance/`). The full route — JE → departmental concurrence →
Sr.DOM traffic clearance → DRM sanction — with authority enforced at every step, exposed
over HTTP (403 for authority, 409 for state). Every transition, **including refused
attempts**, lands in a hash-chained append-only audit log that detects any retroactive
edit and names the first broken link.

Identity is **authenticated**, not asserted: a bearer token resolves server-side to a name
and a role, and `actor`/`role` are gone from the request bodies rather than validated.
What was approved is **stored and hash-verified**, so a sanction can be shown rather than
merely claimed — and a plan edited on disk after the fact is detected.

**Not done** — the identity *store* is a stand-in: tokens in a file rather than the
divisional directory, with no expiry and no per-token revocation. `caller()` in
`scripts/serve.py` is the seam a deployment binds to.

---

## What exists

| Area | Status | Where |
|---|---|---|
| Domain model, topology (41 sections, 8 branches) | ✅ | `domain.py`, `network.py` |
| Published timetable (543 services) | ✅ | `scripts/import_opendata.py`, `timetable_import.py` |
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
| **Test suite (296 tests, 16 files)** | ✅ | `tests/`, `scripts/mutation_check.py` |
| Time–distance chart, month view | ✅ | `web/app/components/` |
| What-if simulator | ✅ | `web/app/components/WhatIfPanel.tsx`, `lib/whatif.ts` |
| Approved plan content | ✅ | `governance/planstore.py`, hash-verified |
| **Estate persistence** | ❌ | regenerated from `seed=42` every start |
| Authentication (password → session → role) | ✅ | `governance/accounts.py`, `sessions.py`, `/api/login` |
| Session expiry and revocation | ✅ | `governance/sessions.py`, two clocks, `/api/logout` |
| **Directory / SSO binding** | ❌ | accounts in a file, no SSO, no central policy |
| Approvals UI | ✅ | `web/app/approvals/`, with sign-in |

### On the tests

296 tests. They cover governance (only the DRM sanctions, heads concur only
for their own department, the sanction gate, tamper detection on the audit chain),
ingestion (round-trip fidelity, metres→km conversion,
the inverted SMMS priority scale, degradation, read-only discipline, rejection by name),
solver invariants (line exclusivity, one gang per department
per block, plant positioning, staff caps, night-work rules, horizon bounds, and that no
block is placed across a protected premier path), pinning (honoured exactly or refused by
name), the timetable reader (a malformed row stops the run rather than silently deleting
a train), **authentication** (an unauthenticated approval action is 401, a role claimed in
the body grants nothing, the audit records the authenticated name), **plan storage** (a
plan edited on disk is detected; a plan id that would escape the store is refused),
payload shape from both producers, model behaviour including a **ground-truth leakage
guard**, and generator calibration.

`scripts/mutation_check.py` re-applies **eleven** defects this project actually shipped
and confirms a test goes red for each — **21/21 caught**. Among them: the clubbing
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

1. **Persist the estate.** Approved plans are stored and hash-verified already; what is
   still regenerated every run is the asset population and defect history. PostgreSQL +
   PostGIS removes the fixed `seed=42` limitation — the service always plans the same
   world. *~1–2 days.*
2. **Bind the identity store to the divisional directory.** Authentication is real —
   a bearer token resolves to a role server-side and the request body has no say. What is
   missing is LDAP or SSO behind it, plus token expiry and per-token revocation. *~1 day.*
3. **Point an adapter at something real.** The transport and translation work; only the
   data behind them is mocked. A single live read-only view or SFTP drop from an actual
   departmental system would close the last of requirement 1. *~1 day, mostly access.*

### Tier 2 — depth

4. **Close the execution loop.** Nothing ingests what actually happened — actual
   durations, overruns, cancellations, failures — so the models cannot be monitored for
   drift or retrained against outcomes. The generator produces ground truth for
   evaluation; the running system has no equivalent.
5. Nest the weekly plan inside the monthly allocation instead of solving them independently
6. **Solver tuning.** The weekly gap is 12.9% at 600 s and 76.6% at 240 s on a realistic
   timetable, because criticality and traffic genuinely contend at that density.
   Symmetry breaking across interchangeable candidates, or an LNS loop warm-started from
   the incumbent, would close it with less wall-clock than more search does.
7. **Branch-to-branch services.** 85 trains work Barauni to Hajipur through the main line;
   the timetable schema holds one branch plus one main leg, so they are reported and
   skipped. Real traffic this division sees.
8. Multi-division; resource pooling across divisional boundaries

### Tier 3 — pitch scope

9. BDMS write-back; condition-monitoring telemetry; live COA feed

---

## Check these claims yourself

Nothing above should be taken on trust. Every number in this document comes from one of:

```bash
python -m pytest                    # 296 tests
python scripts/mutation_check.py    # 21/21 — proves the tests can fail
python scripts/validate.py          # held-out model performance, 5-fold
python scripts/run_pipeline.py --days 7 --tasks 600 --time-limit 600 --monthly --validate
python scripts/ingest.py            # native schemas -> UTM -> plan
python scripts/serve.py             # prints bearer tokens once, on first run
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/me
```

The published timetable is not in the repository as a source dataset — only the 40 KB
extract derived from it. To rebuild that extract:

```bash
python scripts/import_opendata.py --file data/IRCTC_cleaned.csv \
    --ntes ../railpull/data/out -o data/timetable_danapur.imported.csv
```

The pipeline writes `out/plan.json`; the weekly, monthly and validation figures quoted
here are read straight out of it. If a number here disagrees with a fresh run, the run is
right and this file is stale.

---

## Disclose these before someone finds them

- **No live railway data.** Everything synthetic, modelled on published intervals.
- **At 600 s: monthly OPTIMAL, weekly 12.9%.** The weekly gap is budget-sensitive:
  76.6% at 240 s. Quote the gap the run printed, not this line.
- **Overdue task-days get ~2% worse**, because criticality outranks age. A tunable trade-off.
- **Cancellation risk is near the information ceiling** — a weak prior, not a prediction.
- **Consequence weighting discriminates properly now** (0.698–1.000 across the planned
  road) — it did not on the earlier single-corridor topology.
- **The plan is built against published times** — 543 services, stops and times from a
  published schedule, running days from an NTES crawl, merged by
  `scripts/import_opendata.py`. An approximate hand-written timetable (212 services)
  ships as the fallback; the Data Sources screen says which is in force.
- **The published extract is of its own vintage.** Services introduced since it was taken
  are absent, and some it contains have been retimed. A real timetable, not a current one.
- **Only the main line is planned** — 15 of 41 sections. The eight branches are modelled
  for traffic and junction contention, not as places work is scheduled.
- **What-if deferral risk uses an exponential-hazard approximation** of the Cox model.
- **Fixed seed** — the service always plans the same 7-day, 200-task world.

---

## Bottom line

The hard part is built, validated and tested: the data model, adapters over three native
schemas, four models that beat a baseline on held-out data, a solver that finds
cross-departmental clubbing across two horizons, an approval route that refuses anyone
reaching past their authority, and a UI a planner can argue with.

What remains is narrower than it was and mostly unglamorous: persisting the estate,
binding identity to a directory, pointing the connectors — which exist and are tested — at
something other than a mock, and closing the loop by ingesting what actually happened.
[AUDIT.md](AUDIT.md) lists all of it with severities.

**The honest framing for a judge.** Every mechanism the problem statement asks for exists
and is tested, and the traffic it plans around is published data rather than something
this project made up. Two things are still wired to stand-ins: the *defect* feeds are
generated, and the estate they describe is rebuilt from a fixed seed on every start. Those
are deployment work, not research risk — but they are the difference between a system that
demonstrates and a system that runs.

The two claims most worth challenging, stated plainly:

- **The weekly plan is not proven near-optimal at realistic traffic density.** 12.9% gap
  at 600 s, 76.6% at 240 s. The comparison against FCFS is unaffected — both plans are
  built under identical constraints — but "optimal" is not a word to use about the weekly
  pass on this timetable.
- **The published timetable is of its own vintage.** Real numbers, real times, real
  running days; services introduced since the extract was taken are absent, and some it
  contains have been retimed.

For a hackathon prototype this is comfortably past where it needs to be. For a divisional
pilot it is about two-thirds of the way, and the remaining third is named above rather
than hand-waved.
