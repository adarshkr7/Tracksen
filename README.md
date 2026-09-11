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
| **Risk retired per block-hour** | 20.0 | **29.4** | **+47%** |
| Blocks used | 101 | 77 | −24% |
| Block hours consumed | 250.2 | 194.5 | −22% |
| Clubbing ratio (depts per block) | 1.00 | 1.29 | +29% |
| Line closures saved | 0 | 22 | — |
| Traffic cost (wtd detention min) | 15,598 | 12,037 | −23% |
| Corridor adherence | 22% | 53% | +141% |
| High-criticality unplanned failures | 23 | 21 | −9% |
| Overdue task-days | 1,160 | 1,240 | **+7% worse** |

Both plans complete about the same number of tasks (101 vs 99). The gain is not in
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
    criticality.py   P(fail within H) x Urgency(E[time to failure]) x Consequence
                     LightGBM classifier + Cox PH + SHAP attribution
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
  shaded band. `Both` overlays UP and DN on half-bands; `SAMANVAY / Baseline` swaps the
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

## Not built yet

Re-solving from a what-if state (the moves are explored, not committed back to the
solver). Rolling-horizon re-solve with warm start (the hook exists in `BlockOptimiser.solve`,
untested). Monthly corridor-slot horizon. FastAPI service. Held-out model validation.
