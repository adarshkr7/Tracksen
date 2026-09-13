# Roadmap — closing the gap between TRACKSEN and Indian Railways practice

Derived from [RESEARCH.md](RESEARCH.md). Every item here exists because a written Railway Board
rule, a CAG finding, or a real CRIS system says the current build is wrong or incomplete. Items
are ordered by *judge-visible value per hour of work*, not by size.

Nothing here changes the honesty discipline in [AUDIT.md](AUDIT.md): no item may introduce a
number that is not either measured or clearly labelled as synthetic.

**State after items 1–4: 256 tests passing, mutation check 15/15.** Headline figures in
[README.md](../README.md) have been re-run against the new corridor default. Two of the four
items changed a number the project was quoting, and both changes made the old number look
like what it was — an artefact of a constant nobody had checked against the rule.

| # | Item | Why | Status |
|---|---|---|---|
| 1 | Corridor regime — 240 / 2×150 / 180 | Joint Circular para 2.0. `CORRIDOR_HOURS = 3` is the *floor*, not the norm | **done** |
| 2 | Block bursting as the duration headline | CAG: 1,905 bursts → 4,659 trains delayed. We measure it and call it something else | **done** |
| 3 | Corridor fouling audit | CAG finding (ii): trains charted inside the corridor. Two-line query on data we hold | **done** |
| 3b | Place the corridor where the road is quietest | Found by item 3: the corridor was a stagger, not a cleared window | **done** |
| 4 | The two mandated returns | Joint Circular para 3.0: weekly to DRM, monthly to GM | **done** |
| 5 | 26-week rolling block programme | Board mandate 2023; being written into the G&SR | todo |
| 6 | Execution outcome feed (ICMS/PAM-shaped) | Top item in AUDIT.md; the feed exists in real IR | todo |

---

## 1. Corridor regime — the 240-minute norm

**The rule.** Joint Circular No. 2015/Track-III/TK/15 of 28.12.2016, para 2.0: every section shall
have a planned corridor block of assured duration — **one block of four hours, or two blocks of
two-and-a-half hours**. Para 3.0 sets a separate, weaker obligation: a **minimum three-hour**
maintenance block in each section where works are scheduled, even by regulating Mail/Express.

**What was wrong.** `CORRIDOR_HOURS = 3` hard-coded the para-3.0 floor as though it were the norm,
and the monthly model then reported *311 tasks cannot fit a corridor at all*. That number is an
artefact of the constant, not a property of the division.

**What to change.**

- `samanvay/network.py` — `CorridorRegime`, with the three canonical settings named after the
  circular: `single-240`, `split-150x2`, `min-180`. `generate_corridors(days, regime)` emits one or
  two windows per section-day.
- `samanvay/optimizer/cpsat.py` — candidate enumeration and the monthly slot builder handle more
  than one corridor window per section-day.
- `scripts/run_pipeline.py` — `--corridor-regime`, and an extended-block demand comparison across
  all three regimes so the cost of taking 180 instead of 240 is a printed number.

**How to check it.**

```bash
python scripts/run_pipeline.py --days 7 --tasks 200 --monthly --corridor-regime single-240
```

**What it measured.** On 200 pending tasks, extended-block demand by regime:

| Regime | Longest spell | Tasks that cannot fit a corridor |
|---|---:|---:|
| `split-150x2` | 150 min | 144 of 200 |
| `min-180` (the old hard-coded value) | 180 min | 99 of 200 |
| `single-240` (para 2.0, now the default) | 240 min | **40 of 200** |

**Nearly 60% of the extended-block demand this project used to report was manufactured by
its own constant.** The split limb is worse still, and that is a real finding rather than a
bug: it grants *more* corridor minutes per day (300 against 240) but its longest single
spell is shorter, and a four-hour job cannot be done in two halves with the line handed
back to traffic in between. Which limb a division picks is a genuine trade between total
corridor time and the longest job it can absorb, and TRACKSEN can now price it.

Default is now `single-240`, so the headline figures in [README.md](../README.md) need
re-running before they are quoted again.

Covered by [tests/test_corridor.py](../tests/test_corridor.py) — including the two failures
that do not throw: spells that silently overlap, and a corridor placed outside the
06:00–18:00 working day, which would quietly exclude every night-restricted task from the
possession meant to hold it.

---

## 2. Block bursting — the duration model's real name

**The rule.** "Block bursting" is IR's own term for a block utilised beyond its sanctioned time; the
CAG counted **1,905 cases delaying 4,659 trains** across six divisions on the NDLS–HWH route in
2018-19, average burst **38–103 minutes**, cause recorded as "lack of proper coordination between
men, machine and materials".

**What was wrong.** `demanded_coverage = 0.12` is the burst rate written backwards, and the word
"burst" appeared nowhere in the repository. A statistics slide that should have been a safety slide.

**What to change.**

- `samanvay/models/duration.py` — `burst_rate_as_demanded`, `burst_rate_at_p90` and
  `median_burst_min_as_demanded` alongside the coverage figures.
- `samanvay/evaluate.py` — `blocks_written_to_burst`, `burst_rate` and `burst_minutes` on both
  plans: blocks whose window is shorter than the work plus the withdrawal it needs, measured
  against simulator ground truth.
- `scripts/run_pipeline.py`, `samanvay/serialize.py` — the burst framing in the printed output and
  in `plan.json`, so the web client can say it too.

**What it measured.** The pipeline now opens the duration section with:

> as demanded, **86%** of these blocks are written to burst (median over-run **+19 min**);
> reserved at P90, **8%** would burst.

**The plan-level count does not separate the two plans, and that is the honest result.**
Both TRACKSEN and the FCFS baseline reserve at P90, so both burst on roughly the same four
blocks out of eighty-odd. Protection against bursting comes from the duration model, not
from the solver, and the comparison table should not be read as though the optimiser earned
it. What the optimiser earns is on the other rows.

Covered by [tests/test_bursting.py](../tests/test_bursting.py) and two additions to
[tests/test_models.py](../tests/test_models.py). The tests to keep are the ones guarding
failures that do not throw: a burst check that forgets the withdrawal (170 minutes of work
in a 180-minute possession is *not* comfortable once disconnection and restoration are
counted), and one that sums two departments' work instead of taking the longer, which would
report every clubbed block as bursting and make coordination look like a safety problem.

---

## 3. Corridor fouling audit

**The rule.** CAG finding (ii): "during planning for the corridor block for maintenance, trains were
scheduled for running during corridor blocks. This hampered the maintenance work, as corridor blocks
could not be utilised."

**Why it is nearly free.** The repository holds 543 published services and the corridor windows.
Intersecting the two is a query, and it reproduces a national audit finding on a real division.

**What to change.**

- `samanvay/network.py` — `audit_corridors(paths, corridors)` returning, per fouled window, the
  services that cross it, the expected goods, and whether any is premier.
- `scripts/run_pipeline.py` — printed as a named finding; carried into `plan.json` as
  `corridorAudit`, keyed so the UI can mark the fouled windows on the chart.

**What it found, and it was about us.** On the first run the audit reported **210 of 210 corridor
windows crossed by charted paths, 2,969 services, 17 of them premier.** The corridor in this
model was never a cleared window — it was a fixed stagger at 10:00, 11:00 or 12:00 by section,
and the solver was collecting a +40 adherence bonus for putting blocks into windows the chart
runs nineteen trains through. The audit was written to reproduce a CAG finding about Indian
Railways and the first thing it caught was this repository.

---

## 3b. Place the corridor where the road is quietest

**The rule.** The Rolling Block Programme says whose job this is: "**Sr. DOM shall indicate a
suitable corridor** for giving the blocks demanded taking into consideration the integrated
maintenance corridor block provided in the working timetable, **historical data and operational
patterns**." Historical data and operational patterns is what the traffic model is.

**What changed.**

- `samanvay/network.py` — `generate_corridors(days, regime, traffic)` now places each spell at the
  cheapest legal hour for that section and day, longest spell first, treating premier paths as a
  fence rather than a price. Without a traffic model it falls back to the old stagger, and the
  docstring says that a corridor placed that way is not a window anybody cleared.
- `samanvay/domain.py` — `DAY_START_MIN` / `DAY_END_MIN` moved here from the optimiser, because
  two places now need the same working-day window and a second copy would drift.
- `tests/conftest.py` — the `corridors` fixture is the session's own, not a freshly generated set.
  Two sets placed by different rules would have tests asserting against a plan nobody solved.

**What it measured.** Premier fouling went from **17 windows to 0**, and booked services crossing
a corridor from **2,969 to 2,642**.

**It is still 210 of 210, and that is the real answer.** On a division working 543 services there
is no four-hour window on any section with nothing charted through it. Para 2.0 anticipates
exactly this — "wherever margins are inadequate, above corridor blocks shall be **provided by
necessary rescheduling of trains** within Zonal Railway" — so the audit's useful output is not
that the corridor is fouled but **which windows are cheapest to clear**, which is the rescheduling
demand this plan puts on the working time table. The pipeline now prints that list.

---

## 4. The two mandated returns

**The rule.** Joint Circular para 3.0: "All cases of cancellation/deviation from agreed block,
**productivity of blocks given** and **overdue maintenance details**, etc. shall be put up **weekly
to DRM by Sr.DEN/Co-ord** and **monthly to GM by PCE**."

**Why it matters.** TRACKSEN already computes every quantity these returns ask for. Emitting them in
the mandated shape means a division can adopt the output without anyone inventing a new process.

**What to change.**

- `samanvay/reports.py` — `weekly_drm_return()` and `monthly_gm_return()`, built from the
  serialised payload rather than from live objects, so the same function serves `plan.json` on
  disk and an API response, and a return can be reproduced from an artefact archived months ago.
- `scripts/report.py` — renders either to text or Markdown.

```bash
python scripts/report.py --which both --markdown -o out/
```

Each return carries the parts para 3.0 names, lettered: blocks programmed, corridor, productivity
of blocks given, cancellation and deviation, overdue maintenance. The monthly return replaces the
first two with corridor-slot allocation and **extended and mega block demand** — the tasks that
cannot fit one corridor, broken down by department, which is the division's extended-block
requirement for the month.

**The deviation part is deliberately empty.** Para 3.0 asks which agreed blocks were not given and
which given blocks were not used. Nothing ingests what happened, so both rows say "no execution
feed connected" rather than being filled with the cancellation model's forecast — that is the one
substitution that would make this document actively misleading, since the DRM reads that part as a
record. The model's number appears below it, labelled as a prior. A test asserts this.

Covered by [tests/test_reports.py](../tests/test_reports.py). The mutation check gained an entry for
the failure that renders perfectly: a monthly return built from the weekly plan's blocks. **Writing
it found that the first version of that test did not catch it** — the overdue total comes from the
metrics, and the worst-offender list filled up with deferred tasks either way. The test now asserts
on a day only the monthly plan has.

---

## 5. 26-week rolling block programme

**The rule.** Since 2023 every division prepares a block programme **26 weeks ahead**, per traffic
section per line, reviews it weekly, and **adds a 26th week each week**. Being written into GR
Ch. 15 para 15.02(c) and Operating Manual Ch. 22.

**What to build.**

- A rolling driver: solve week 1 at fine granularity, weeks 2–26 at corridor-slot granularity,
  then roll forward one week and re-solve, carrying unstarted work.
- The weekly review artefact: blocks planned but not demanded, and planned but not granted — the
  two columns Prayagraj records in its Google Sheet.
- `--rbp` on the pipeline; the horizon selector in the web UI gains a third setting.

**Watch for.** The 30-day monthly solve already takes a corridor-slot model; 26 weeks is 182 days
and roughly six times the slots. Expect to need slot pruning or a week-by-week decomposition rather
than one monolithic solve.

---

## 6. Execution outcome feed

**The rule.** Not a rule — the top entry in [AUDIT.md](AUDIT.md). Nothing ingests what actually
happened, so no model can be monitored for drift.

**Why it is now tractable.** The feed exists in real IR: **ICMS/PAM** records detention with cause
attribution across 33 factors, including "Engineering" and "Planned block open line", and pulls its
timings from **COA**, which is fed by **RTIS** loco GPS every 30 seconds.

**What to build.**

- A fourth source in `samanvay/ingestion/sources.py` shaped like a PAM extract: block id, actual
  start, actual end, burst minutes, cause code, trains detained.
- The same adapter ladder and the same rejection-by-name discipline as the other three.
- A drift monitor: realised duration against P90 reservation, realised cancellation against the
  cancellation model's prior, per week.

---

## Also worth doing, smaller

- **Name the real systems in the UI.** TMS, SMMS and TDMS are genuine CRIS systems; **TMMS** (Track
  Machine Management System) is the real source for plant positioning and **ROBMS** is the official
  rolling-block portal. The Data Sources screen should say so.
- **Put the 2.2% on a slide.** The baseline TRACKSEN beats is the audited national practice, not a
  straw man, and that is the strongest sentence available.
- **UIC 406 capacity compression** as an alternative traffic price — compress the section's timetable
  graph until buffers are zero, and report capacity consumption with and without the block.
