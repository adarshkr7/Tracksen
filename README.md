# SAMANVAY

**AI-powered automatic block planning for Indian Railways** — SIH 2026, PS 26027, Ministry of Railways.

Three departments plan maintenance blocks independently. Engineering works out of TMS,
Signal & Telecom out of SMMS, Traction Distribution out of TDMS. All three raise demands
into BDMS for the same scarce block sections, and none of them can see the other two
queues. The result is three separate line closures where one would have done, and a
critical defect waiting behind routine work that asked first.

SAMANVAY is a decision-support layer over those existing systems. It does not replace
any of them and it **never grants a block** — it produces a recommended plan, and the
competent authority sanctions.

---

## Running it

```bash
pip install -r requirements.txt
```

```bash
python scripts/run_pipeline.py --days 7 --tasks 200 --time-limit 45
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

Measured over a 7-day horizon, 200 pending tasks, 7 block sections of the
Ahmedabad–Vadodara corridor, against an FCFS baseline on the identical task population:

| Measure | Baseline | SAMANVAY | |
|---|---:|---:|---|
| **Risk retired per block-hour** | 32.5 | **47.1** | **+45%** |
| Blocks used | 101 | 76 | −25% |
| Block hours consumed | 250.2 | 196.5 | −21% |
| Clubbing ratio (depts per block) | 1.00 | 1.35 | +35% |
| Line closures saved | 0 | 27 | — |
| Traffic cost (wtd detention min) | 15,598 | 13,306 | −15% |
| Corridor adherence | 22% | 49% | +123% |
| High-criticality unplanned failures | 36 | 33 | −8% |
| Overdue task-days | 1,160 | 1,230 | **+6% worse** |

Both plans complete about the same number of tasks (101 vs 103). The gain is not in
doing more — it is in doing the *right* work, in *fewer* closures, at *cheaper* hours.

**The overdue regression is real and is not a bug.** The optimiser ranks by criticality,
not by age, so it will pass over a long-overdue low-consequence job in favour of a newer
defect about to fail under a premier path. Raise `--overdue` to buy that back; it costs
risk-retired-per-block-hour. The trade-off is the planner's to make, which is why it is
a slider and not a constant.

---

## How it works

```
samanvay/
  domain.py          Unified Task Model — every task keyed by (section, line, chainage)
  network.py         Ahmedabad–Vadodara topology, working timetable, goods forecast,
                     mandated corridor windows
  generator.py       Synthetic TMS / SMMS / TDMS feeds + historical blocks and defects
  models/
    traffic.py       Traffic cost surface; per-section consequence weighting
    criticality.py   LightGBM failure risk + Cox PH time-to-failure + SHAP attribution
    duration.py      Quantile GBM — P50 reported, P90 reserved against
    cancellation.py  Will this block, if sanctioned, actually run?
  optimizer/
    cpsat.py         OR-Tools CP-SAT: the scheduling model
    baseline.py      First-come-first-served — current practice, reproduced
  evaluate.py        KPIs, computed identically for both plans
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
- **The solver stops at a ~17% optimality gap** in 45 seconds on this instance. The
  reported figures are therefore a floor, not a ceiling, on what the formulation
  achieves. The gap is printed on every run.
- **Consequence weighting is weak on this topology** (0.87–0.98 across sections). Most
  traffic on a single trunk corridor runs through, so exposure genuinely is similar
  section to section. The term will discriminate properly across a division with branch
  lines and mixed route classifications.
- Model diagnostics are in-sample. Held-out validation is outstanding.

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

## Not built yet

Web interface — time–distance chart, ranked queue with SHAP chips, what-if simulator.
Rolling-horizon re-solve with warm start (the hook exists in `BlockOptimiser.solve`,
untested). Monthly corridor-slot horizon. FastAPI service. Held-out model validation.
