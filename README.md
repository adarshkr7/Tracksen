# TRACKSEN

**AI-Powered Railway Maintenance Intelligence & Planning** — SIH 2026, PS 26027,
Ministry of Railways.

Three departments plan maintenance blocks independently. Engineering works out of TMS,
Signal & Telecom out of SMMS, Traction Distribution out of TDMS. All three raise demands
into BDMS for the same scarce block sections, and none of them can see the other two
queues. The result is three separate line closures where one would have done, and a
critical defect waiting behind routine work that asked first.

TRACKSEN is a decision-support layer over those existing systems. It does not replace
any of them and it **never grants a block** — it produces a recommended plan, and the
competent authority sanctions.

**Build status:** [STATUS.md](STATUS.md) for what is built against the problem statement.
[AUDIT.md](AUDIT.md) for what is broken or unfinished, which is the more useful document
if you are deciding whether to trust a number on a screen.

TRACKSEN is not an Indian Railways product and is not connected to any live railway
system. The demonstration runs on synthetic operational data over a real network
topology; every screen says so.

---

## Running it

```bash
pip install -r requirements.txt
```

```bash
python scripts/run_pipeline.py --days 7 --tasks 600 --monthly --validate --time-limit 240
```

That generates the estate, fits the models, solves the week, schedules the same tasks
under a first-come-first-served baseline, and prints the comparison. The full plan lands
in `out/plan.json`.

Weights are command-line flags because they are meant to be argued with:

```bash
python scripts/run_pipeline.py --clubbing 40 --traffic 0.12 --corridor 60 --overdue 3
```

| Flag | Objective term | Default |
|---|---|---|
| `--clubbing` | β — bonus per extra department sharing a block | 25 |
| `--traffic` | λ — cost per weighted detention minute | 0.05 |
| `--corridor` | bonus per block inside the mandated corridor | 40 |
| `--overdue` | μ — penalty per task-day past the statutory date | 1.5 |

---

## What it produces

Measured over a 7-day horizon, 600 pending tasks, the **Danapur division** of East
Central Railway, against an FCFS baseline on the identical task population:

| Measure | Baseline | TRACKSEN | |
|---|---:|---:|---|
| **Risk retired per block-hour** | 8.4 | **21.3** | **+154%** |
| Blocks used | 191 | 121 | −37% |
| Block hours consumed | 643.0 | 393.0 | −39% |
| Clubbing ratio (depts per block) | 1.00 | 1.59 | +59% |
| Line closures saved | 0 | 71 | — |
| Traffic cost (wtd detention min) | 155,321 | 77,838 | −50% |
| Corridor adherence | 31% | 60% | +94% |
| Unplanned failures | 71 | 63 | −11% |
| High-criticality unplanned failures | 18 | 13 | −28% |
| Overdue task-days | 3,880 | 4,001 | **+3% worse** |

Solver: monthly **`OPTIMAL`**, weekly `FEASIBLE` at a **12.9% gap**, 600 s each.

**The weekly gap is budget-sensitive, and it is worth knowing why.** At 240 s it is 76.6%
on this timetable. The real road is 2.2x busier than the hand-written one this replaced,
so the objective's traffic term has gone from a tenth of the total to half of it, and
criticality and traffic now genuinely contend where criticality used to dominate. More
time closes it — 600 s reaches 12.9% — so it is a search-effort problem, not a broken
formulation. The gap prints on every run; check it before quoting.

The gain is not in doing more work. It is in doing the *right* work, in *fewer* closures,
at *cheaper* hours.

**The overdue regression is real and is not a bug.** The optimiser ranks by criticality,
not by age, so it will pass over a long-overdue low-consequence job in favour of a newer
defect about to fail under a premier path. Raise `--overdue` to buy that back; it costs
risk-retired-per-block-hour. The trade-off is the planner's to make, which is why it is
a slider and not a constant.

### The monthly horizon

```bash
python scripts/run_pipeline.py --days 7 --tasks 200 --monthly
```

A monthly plan answers a different question, so it uses a different model. Nobody commits
a tamping machine to 11:15 on the 24th four weeks out — they commit it to *a corridor on
the 24th*. The monthly solve therefore drops the fine time grid and allocates the mandated
corridor itself, one slot per section, line and day.

Over 30 days on this division: **201 of 900 corridor slots** allocated, **237 tasks
placed**, backlog burning down **577 → 363**.

**311 tasks cannot fit a corridor at all** — their P90 plus the setup and restoration
their withdrawal needs exceeds 180 minutes. On the real railway these go up as extended or mega blocks
negotiated separately with operations, and the monthly plan names them rather than quietly
leaving them unscheduled. That list is itself an output: it is the division's extended-block
demand for the month.

In the UI, **Week / Month** switches horizons; `?view=month` links straight to it.

---

## How it works

```
samanvay/
  domain.py          Unified Task Model — every task keyed by (section, line, chainage)
  network.py         Danapur division topology (main line + 8 converging branches),
                     coaching timetable read from data/, goods forecast, corridor windows
  generator.py       Synthetic TMS / SMMS / TDMS feeds + historical blocks and defects
  models/
    traffic.py       Traffic cost surface; per-section consequence weighting
    criticality.py   P(fail within H) x Urgency(E[time to failure]) x Consequence
                     LightGBM classifier + Cox PH + SHAP attribution
    duration.py      Quantile GBM — P50 reported, P90 reserved against
    cancellation.py  Will this block, if sanctioned, actually run?
  governance/
    workflow.py      Who may approve what, and in what order
    audit.py         Hash-chained, append-only, tamper-evident trail
  ingestion/
    sources.py       Mock TMS / SMMS / TDMS in their native schemas
    adapters.py      REST -> read-only DB view -> CSV, and normalisation into the UTM
  optimizer/
    cpsat.py         OR-Tools CP-SAT: the scheduling model, with pinned placements
    baseline.py      First-come-first-served — current practice, reproduced
  evaluate.py        KPIs, computed identically for both plans
  session.py         Estate + models built once, solved repeatedly (with pins)
  serialize.py       The one payload builder, shared by plan.json and the API
```

**The chainage key is the load-bearing idea.** Once an S&T fault at km 412 and an OHE
job at km 412.6 are written in the same coordinates, "are these near each other" becomes
arithmetic, and clubbing becomes something a solver can find.

**Clubbing is enforced by one constraint:** at most one task per department per block. A
department fields one gang per block, so a block holding two tasks necessarily holds two
departments — and the bonus then rewards exactly the coordination the problem statement
is about. Work runs in parallel across departments inside the block.

**The objective:**

```
max  Σ Criticality(t)·Completed(t)
   + β·Σ ClubbingBonus(b)  +  corridor·Σ InsideCorridor(b)
   − λ·Σ TrafficCost(b)    −  μ·Σ OverdueBreach(t)
```

subject to line exclusivity (`NoOverlap` per section and line), plant positioning
(network-wide `NoOverlap` per machine with a 90-minute buffer), staff limits per
department per day, night-working restrictions, and corridor capacity.

---

## Held-out validation

```bash
python scripts/validate.py --folds 5
```

Every model is refitted on k-1 folds and scored on the fold it never saw. In-sample
numbers on boosted trees are close to meaningless, and running this found two real
defects that in-sample diagnostics had hidden completely.

| Model | Held-out | Note |
|---|---:|---|
| Criticality classifier AUC | **0.826 +/- 0.017** | against 0.665 majority-class |
| Cox concordance | **0.765 +/- 0.035** | ordering of time-to-failure |
| Duration P90 coverage | **0.924 +/- 0.023** | target 0.90, conformalised |
| Duration P50 MAE | **15.5 min** | vs 48.0 for a median baseline |
| Cancellation AUC | **0.663 +/- 0.057** | oracle ceiling 0.662 |

**What it caught, and what changed as a result.**

*The P90 reservation did not hold.* In-sample coverage read 0.92; held-out it was
**0.81** - roughly one block in five would have over-run the window reserved for it,
quietly falsifying the central duration argument. The P90 is now **conformalised**: a
calibration split the quantile model never fits on supplies an empirical offset
(~10 min here) that restores the guarantee.
Held-out coverage is now 0.924.

*The cancellation model was memorising noise.* In-sample AUC 0.92, held-out **0.57** -
barely better than a coin flip. It is now a **logistic regression**, reaching
0.663 against an oracle scored on the data generator's
own cancellation probabilities of 0.662. The simple model is within 0.002 of
the information ceiling: whether a given block gets cancelled is mostly irreducible, and
no amount of capacity recovers it. Treat that output as a weak prior - by nature, not by
neglect.

One number was never in-sample and is worth saying so: the Spearman check of criticality
against true time-to-failure runs on the *pending* tasks, a different population from the
historical defects the model trains on.

## Ingestion

```bash
python scripts/ingest.py
```

Writes mock TMS / SMMS / TDMS in their **native** formats, pulls them through the adapter
ladder into one Unified Task Model, then scores and schedules the result. Nothing above
the adapter layer knows where the tasks came from — the same models and the same solver
run on ingested records as on generated ones.

The three systems deliberately disagree, because real ones do:

| | Transport | Naming | Units | Dates | Severity |
|---|---|---|---|---|---|
| **TMS** | CSV drop | `UPPER_SNAKE` | km | `DD-MM-YYYY` | `S1..S5`, S5 worst |
| **SMMS** | read-only DB view | `lower_snake` | **metres** | ISO | `P1..P5`, **P1 worst** |
| **TDMS** | REST / JSON | `camelCase` | nested km | ISO-8601 Z | integer 1–5 |

Each source is tried in descending order of fidelity — **REST → read-only DB view → CSV
drop** — and falls back. A design that presumes an API cannot be commissioned; parts of
the estate will give you nothing but a nightly file.

**Two rules the layer is built on.**

*Nothing is ever written to a source system.* The SQLite adapter opens with `mode=ro` and
**refuses to run against anything but a view** — point it at a base table and it raises.
A DBA grants a view, not a table, and the code should make the weaker grant sufficient.

*A record that cannot be mapped is rejected by name, with a reason.* Silently dropping
malformed rows is how a division discovers six months later that its worst defects were
never scheduled because a date format changed. Degradation is reported too — the run log
says which mode each source used and why the better ones were skipped.

**The two failures worth testing for are the ones that don't throw.** SMMS publishes
chainage in metres; read it as kilometres and every signalling job lands a thousand times
further down the road. SMMS priority P1 is the *most* urgent, the reverse of TMS severity;
map both straight onto an integer and the plan attends the least urgent faults first.
Neither raises an exception. Both are covered by tests and by the mutation check.

## Approval workflow and audit trail

TRACKSEN produces the plan. It does not sanction it — and `samanvay/governance/` is where
that stops being a sentence in a README and becomes a rule the code enforces.

The route a block demand actually travels:

```
JE / SSE raises
  -> Sr.DEN / Sr.DSTE / Sr.DEE concur, each for their own department only
      -> Sr.DOM clears the traffic impact
          -> DRM sanctions
```

Four rules, all enforced and all tested:

- **Only the DRM can sanction.** Every other role is refused — over HTTP, a `403`.
- **A department head concurs for their own department and no other.** Sr.DSTE cannot
  sign off Engineering's work; that is someone else's accountability.
- **Sanction requires every department present to have concurred and operations to have
  cleared.** Skipping the order gives a `409` listing exactly what is outstanding.
- **A sanctioned plan cannot be edited.** Changing sanctioned work means superseding it
  with a new plan that travels the route again. Modifying a *draft* silently invalidates
  concurrences already given — they were granted to a different plan, and carrying them
  forward would launder the change through approvals nobody gave for it.

### The trail

Every transition is appended to a **hash-chained** log: each entry carries the SHA-256 of
the one before it. Edit any historical record — change a name, soften a remark, move a
sanction time — and every subsequent hash stops matching. `GET /api/audit/verify` walks
the chain and names the first broken link.

A block plan is a safety document. When something goes wrong on the ground, the question
asked afterwards is what was recommended, what was changed, by whom, and on whose
authority. A log that can be quietly rewritten answers none of it.

**Refused attempts are recorded too.** Someone reaching past their authority leaves a
`DENIED` entry naming what they tried and why it was refused, rather than vanishing
because the code said no.

```bash
POST /api/plans/{id}/submit     JE puts a plan into the route
POST /api/plans/{id}/concur     departmental head, own department only
POST /api/plans/{id}/clear      Sr.DOM, after concurrence
POST /api/plans/{id}/sanction   DRM only, gate fully satisfied
GET  /api/plans/{id}/audit      the trail for one plan, with chain status
GET  /api/audit/verify          has the log been rewritten?
```

Identity is a stand-in: `_actor(name, role)` in `scripts/serve.py` is the seam a real
deployment binds to the divisional directory. The workflow rules are the same either way,
and leaving the seam visible is better than implying an identity system that is not there.

## Tests

```bash
python -m pytest              # 152 tests, ~40 s
python scripts/mutation_check.py
```

Governance (authority, the sanction gate, tamper detection), ingestion behaviour
(round-trip fidelity, unit conversion, severity inversion,
degradation, read-only discipline, rejection by name), solver invariants (line exclusivity, one gang per department per block, plant positioning,
staff caps, night-work rules, horizon bounds), pinning behaviour, payload shape from both
producers, model behaviour including a **ground-truth leakage guard**, and generator
calibration. Physical constraints are asserted against the baseline too — if the baseline
were allowed to break rules the optimiser obeys, the comparison above would be rigged.

`mutation_check.py` re-applies eleven defects this project actually shipped — the INFEASIBLE
clubbing constraint, the disabled conformal offset, ground truth in a feature set, the 10×
duration calibration error, the removed positioning buffer, the metres/kilometres
confusion, the un-inverted priority scale, four governance failures including an
authority check removed and a chain verifier that always passes — and confirms a test
goes red for each. **11/11 caught.** A suite that passes proves nothing on its own; it may simply be
unable to fail.

Writing that check found a sixth problem: the plant-positioning test read the same constant
it was validating, so zeroing the constant relaxed the assertion too and the mutation walked
straight through. It now asserts an independent floor.

## Honest notes

- **There is no live railway data here.** `generator.py` produces synthetic feeds whose
  structure matches the departmental systems and whose distributions are modelled on
  published maintenance intervals. On deployment each generator is replaced by its
  adapter and nothing above that layer changes.
- **Two quantities are simulator ground truth** — `true_duration_min` and
  `true_days_to_failure`. No model and no solver ever sees either. They exist so that
  evaluation can ask the question that matters: did the plan get there before the asset
  failed? Using them as features would be cheating; using them to score is the point.
- **The criticality classifier drops right-censored records.** A defect attended before
  it failed tells us nothing about whether it would have failed within the horizon, so
  those rows are excluded rather than labelled zero. That biases the sample toward
  assets left alone longer, and is documented in `_label_within_horizon`. Cox uses the
  full sample, censoring included — which is why it is there.
- **The optimality gap is time-limit dependent**, and the figures above come from a 240 s
  solve: **weekly 1.1%, monthly 5.8%**. Both were far worse until the model stopped
  offering the solver work it could never place — a task whose P90 plus its withdrawal
  overruns the corridor was being handed over as though it fitted, and its criticality
  inflated the objective's upper bound. The gap prints on every run; check it before
  quoting.
- **Consequence weighting now discriminates** (0.698–1.000 across the planned road).
  On the earlier single-corridor topology it did not (0.87–0.98) because all traffic ran
  through. On a division it separates properly: the Patna throat sections carry the most
  exposure, Kiul–Jhajha the least, which is what a P.Way officer would tell you. The term
  behaves as intended across a division with branch
  lines and mixed route classifications.
- Cancellation risk is near-irreducible on this data (see above). It ranks fragile
  slots against robust ones and must not be read as a per-block prediction.

---

## What the duration model found

The most quotable result is not the scheduler's. Across the pending queue:

- The duration each department **demanded** would have contained the actual work
  **12%** of the time.
- The **P90** reservation contains it **92%** of the time.
- Median difference: **+45 minutes** per block.

Nearly nine blocks in ten, as currently demanded, are written to over-run before anyone
starts work.

---

## Web interface

```bash
cd web
npm install
npm run sync      # copies ../out/plan.json into public/
npm run dev       # http://localhost:3000
```

Next.js 16, React 19, Tailwind 4. The chart is hand-rolled SVG — no charting library,
because nothing off the shelf draws a train graph.

- **Time–distance chart.** Time across, chainage down, stations on the left gutter.
  Train paths are the diagonals, blocks are rectangles, the mandated corridor is the
  shaded band. `Both` overlays UP and DN on half-bands; `TRACKSEN / Baseline` swaps the
  plan underneath the same traffic, which is the comparison worth showing.
- **Unified priority queue.** All three departments in one ranking, each row carrying
  its SHAP attribution and its demanded-vs-P90 duration.
- **What-if simulator.** Drag any block along the time axis, or nudge it by ±15 min,
  ±1 hour, ±1 day. Three things recompute on every move: the traffic cost of the new
  window (priced against the actual paths it intersects), the risk carried forward by
  deferring, and whether the move breaks a hard constraint. A dashed ghost marks where
  the block was; conflicted blocks turn red and the totals bar refuses to call the
  result a valid plan.
- Click any block for its member tasks and the reasons it was placed where it was.

The page reads `out/plan.json`; re-run the pipeline and `npm run sync` to refresh.

### Re-solving from a what-if state

```bash
python scripts/serve.py        # http://127.0.0.1:8000
```

Move blocks, then press **Re-solve holding these**. The solver takes those placements as
hard facts and re-optimises everything else around them — a different question from the
one the original solve answered, and the one a planner actually asks.

The button appears only when `/api/health` answers. Without the service the page still
loads `plan.json` and the what-if simulator still prices moves client-side; you just
cannot commit them back. That matters when demonstrating on a laptop that is not yours.

**Pinning costs something, and the UI says so.** Constraining the search almost always
lowers the headline — a typical single pin moves risk-per-block-hour by a point or two.
The result banner reports the before-and-after rather than quietly showing the new
number. A pin the solver cannot honour is refused **by name** with its reason
(`641: falls outside the horizon`), never silently dropped.

Endpoints: `GET /api/health`, `GET /api/plan`, `POST /api/resolve`
(`{pins: [{block_id, start_min, task_ids}], weights?, time_limit_s}`). Session state —
estate, fitted models, candidates — is built once (~4 s) and reused, so a re-solve is
just the solve (~10–20 s).

`samanvay/serialize.py` is the single payload builder for both `plan.json` and every API
response. The web client parses both, and two builders would drift the moment either
side gained a field.

### How what-if stays honest

Client-side re-pricing uses the **same detention weights and regulation overhead** the
solver optimised against — they travel in `plan.json` rather than being retyped in
TypeScript, because a client that priced windows differently would tell the planner a
move is cheap while the optimiser believed it expensive.

Conflicts are checked against the same four hard rules the CP-SAT model enforces: line
exclusivity, plant positioning (90-minute buffer, network-wide), the per-department
daily block limit, and night-working restrictions. These are refusals, not preferences.

Risk carried forward assumes an **exponential hazard** around the Cox expectation:
a task with E[days to failure] = 5 deferred by one day carries 1 − e^(−1/5) ≈ 19% added
failure probability. That memoryless assumption approximates the Cox model rather than
re-deriving it — it is an order of magnitude while dragging, not a substitute for the
nightly re-solve.

## The timetable

Two files ship, and the loader prefers the second whenever it is present:

| | services | times | running days |
|---|---:|---|---|
| `data/timetable_danapur.csv` | 212 | approximate, written by hand | approximate |
| `data/timetable_danapur.imported.csv` | **543** | **published** | **published** |

So a clone plans against published times by default. The approximate file stays as the
fallback: it is what makes the repository runnable if the imported one is ever removed,
and the Data Sources screen always says which is in force.

The imported file is a **derived extract** — 543 services over one division, reduced to
the ten columns this model needs — merged from a published schedule (stops and times) and
an NTES crawl via [railpull](https://github.com/shwetankg07/railpull) (running days). Its
header carries the attribution. The 116 MB of source datasets are not in the repository;
regenerate rather than copy the extract onward:

```bash
python scripts/import_opendata.py --file data/IRCTC_cleaned.csv \
    --ntes ../railpull/data/out -o data/timetable_danapur.imported.csv
python scripts/run_pipeline.py --days 7 --tasks 600 --monthly --validate
```

The merge takes stops and times from IRCTC, running days from the NTES crawl, and adds
any current service the published extract predates. Neither source is better at
everything, which is why it is a merge and not a choice.

## Not built yet

See [AUDIT.md](AUDIT.md) for the full list with severities. The short version:

- **Real execution feedback.** Nothing ingests what actually happened — actual durations,
  overruns, cancellations, failures — so the models cannot be monitored for drift or
  retrained against outcomes.
- **Authentication.** `_actor(name, role)` takes the caller's word for their role. The
  workflow rules are real; the identity behind them is not. Production blocker.
- **Persistence beyond the audit log.** Approvals replay from the log on restart, but the
  plan *content* they approved is not stored — only the decision is.
- **A single-vintage timetable.** Published times now come from IRCTC_cleaned and real
  running days from an NTES crawl, merged by `scripts/import_opendata.py`. Where a train
  was not crawled, its running days fall back to IRCTC's flattened column (all-seven or
  exactly-one), and the importer reports that split on every run.
- **Branch-to-branch services.** 85 trains work Barauni to Hajipur through the main line.
  The timetable schema holds one branch plus one main leg, so those are reported and
  skipped rather than guessed at.
- **Branch block planning.** `PLANNED_ROUTES = ["MAIN"]`; the eight branches are modelled
  for the traffic they put onto the main line and the junction throats they share with
  it, not as places work is scheduled.
