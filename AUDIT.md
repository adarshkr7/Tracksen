# TRACKSEN — System Audit

**Date:** 12 September 2026
**Scope:** whole repository — backend, solver, governance, web client, documentation
**Test suite:** 153 passing · mutation check 11/11
**Plan:** 7 days, 600 tasks, Danapur division (42 sections, 15 planned), 240 s solve
**Solver:** weekly gap 1.1% · monthly gap 5.8%
**Web build:** clean (Next.js 16, TypeScript, 14 static routes)

This is a point-in-time review of what is broken, what is incomplete, and what is
claimed but not implemented. It is deliberately unflattering — the useful version of
this document is the one that lists everything, not the one that reads well.

Everything below was verified against the code, not inferred from comments. Items are
grouped by whether they are **defects** (the system does the wrong thing) or **gaps**
(the system does not yet do the thing at all). File references are `path:line`.

> **Status of the working tree:** the fixes in §1 are applied but **not committed**.
> `git status` shows 20 modified and 25 untracked files. Nothing here has been pushed.

---

## 1. Defects found and fixed in this pass

These were real. Each is fixed, with a regression test unless noted.

| # | Defect | Where | Why it mattered |
|---|--------|-------|-----------------|
| 1 | **Pinned blocks bypassed the premier-path fence** | `samanvay/session.py:174` | Candidate windows refuse to cross a Rajdhani/Vande Bharat path, but pins mint their own candidate and never met that check. A planner dragging a block on the What-If chart could park a possession across a protected path — walking straight past the one rule the solver is not allowed to trade away. Now refused **by name**: *"would stand in front of 12309 Rajdhani at 19:15"*. |
| 2 | **Plan-id collision after restart** | `scripts/serve.py:72` | `_plan_counter` starts at 0 each boot, but approvals are now replayed from the audit log. The next auto-allocated id collided with a restored plan — and the re-solve path treats an existing id as *modify this plan*, so it would have **wiped a stranger's concurrences and written the change into the audit trail against their plan**. This bug was *created by* adding replay; it was invisible while the workflow started empty. |
| 3 | **Block types were decorative** | `samanvay/optimizer/cpsat.py:61` | `TRAFFIC` / `DISCONN` / `POWER` were emitted in results and shown in the UI but constrained nothing. A block could be granted exactly the P90 of its longest job, leaving zero minutes for OHE isolation or signalling disconnection — the plan promised working time the possession did not contain, and the overrun would surface on the ground. Withdrawal setup/restore minutes are now enforced, taking the **maximum** across clubbed withdrawals rather than the sum (one isolation covers every gang under it — summing would delete the reason to club). |
| 4 | **Baseline cached ignoring the weights** | `samanvay/session.py:128` | `baseline(weights)` stored the first result forever. Move the operational sliders, re-solve, and every percentage on the comparison screen was measured against a datum built under the old limits. Now keyed by weights. |
| 5 | **`DETENTION_WEIGHTS` was a hand-kept mirror** | `samanvay/serialize.py:59` | A literal `[4.0, 2.5, 1.5, 1.0]` copied from the enum. It went stale the moment premier detention was repriced to 12.0, so client-side What-If pricing silently disagreed with what the solver had optimised. Now derived from `TrainClass`. |
| 6 | **A second stale copy of the same weights, client-side** | `web/app/lib/whatif.ts:251` | `data.detentionWeights ?? [4, 2.5, 1.5, 1]` — the identical stale fallback, moved to the browser. What-If exists to show what a move would cost *the solver*; pricing it off numbers the solver is not using makes it confidently wrong, which is worse than blank. The fallback is gone; it now refuses. |
| 7 | **Unknown department returned HTTP 500** | `scripts/serve.py:207` | `Department("ENG")` raises `ValueError`, which FastAPI renders as a server error. The caller could not tell "you sent a bad code" from "the service is broken". Now 422 with the valid codes listed. |
| 8 | **No error boundary anywhere in the web app** | `web/app/error.tsx` *(new)* | A throw during render blanked the page — no message, no way back. For a control-room screen that is the worst failure mode, because a blank panel and a working panel showing nothing look identical. |

### Already fixed before this pass

An external review flagged three more. All three were **real in `HEAD`** and **already
fixed in the working tree** — the review read the committed version:

- **Reservation semantics disagreed between optimiser and display.** `HEAD:cpsat.py:512`
  shortened the extracted block to the longest P90 while CP-SAT had reserved and priced
  the full candidate capacity. Fixed: `reserved_min = c.capacity_min`.
- **Baseline comparison was not like-for-like.** `HEAD:baseline.py` reserved only the
  task's P90 while CP-SAT locked the full capacity, letting FCFS pack work the optimiser
  had correctly held unavailable. Fixed: both reserve the candidate possession.
- **Approval state was lost on restart.** `workflow.py:158` now replays state from the
  audit log — and refuses to replay a tampered chain, because replaying a forged log
  would quietly reinstate concurrences nobody gave.

---

## 2. Open defects and gaps

Ordered by how much they threaten the claims the project makes.

### ✅ Closed since the first pass

- [x] **Both optimality gaps were bad, and it was a bug, not tuning.** Weekly was 84.75%
      and monthly 76.8%. `needs_extended_block` compared bare P90 against the corridor and
      ignored the withdrawal, so a 170-minute disconnection was handed to the solver as
      fitting a 180-minute corridor when it actually needs 205. Those tasks could never be
      placed, and their criticality inflated the objective's upper bound.
      Fixed → **weekly 1.1%, monthly 5.8%**. No extra solver time was needed.
- [x] **Documentation described a different system.** `README.md` and `STATUS.md` are
      rewritten against the Danapur division with current measured figures, and both now
      point here for what is unfinished.
- [x] **Sanctioned plan content is now recorded.** `Plan.content_hash()` fingerprints the
      operative content — where each block sits, for how long, on which road, holding
      which work — and it goes into the `CREATE`, `MODIFY` and `SANCTION` entries. Labels,
      reasons and scores are excluded, so re-scoring an unchanged plan does not read as a
      modification. Replayed on restart.
- [x] **`requires_power_block` / `requires_disconnection` are live.** They now feed
      `withdrawals_for()`, so a P.Way job on an OHE mast pays for isolation even though
      its department filed it as a plain traffic block.
- [x] **Branding finished in the documents.** `PLAN.md`, `SLIDES.md`, `SPEECH.md`,
      `docs/paper.html` and the PDF. Module paths under `samanvay/` deliberately untouched.

### 🔴 Blocking — these undermine stated results

- [ ] **The timetable's times are still approximate.** This is now the single weakest
      claim in the project. 212 services carry real numbers, names and routes; the times
      and running days are plausible, not booked. `scripts/import_railpull.py` has been
      **verified against railpull's actual exporter** — three bugs were found and fixed in
      doing so, one of them fatal (it read `train` where railpull writes `train_number`,
      so it would have imported nothing). The crawl itself has not been run: it is several
      hours against a public enquiry service and is yours to start.

      ```
      cd D:/CODE/railpull && pip install -r requirements.txt
      python ntes/crawl.py && python transform/export.py
      cd D:/CODE/SIH && python scripts/import_railpull.py           --railpull ../railpull/data/out -o data/timetable_danapur.imported.csv
      ```

### 🟠 Significant — real limitations, currently unstated or understated

- [ ] **The API trusts client-supplied identity.** Any caller can POST
      `{"role": "DRM"}` and sanction a plan (`scripts/serve.py:58`). The code documents
      this as a deliberate seam and the workflow rules are real, but it is a hard
      production blocker: roles must bind to authenticated server-side identities.
- [ ] **Nothing persists except the audit log.** Plans, the planning session, the id
      counter and all solve results live in memory. A restart replays approvals but
      cannot show you the plan they approved.
- [ ] **311 of 600 tasks cannot fit a corridor at all.** Their P90 exceeds the 180-minute
      window, so they are named as needing an extended/mega block rather than scheduled.
      Honest, but it means a third of the backlog is outside what the system plans.
- [ ] **Only the main line is planned.** `PLANNED_ROUTES = ["MAIN"]` (15 of 42 sections).
      The eight branches are modelled for traffic and junction contention only. This is
      deliberate and documented, but it is a scope limit, not a solved problem.
- [ ] **No execution feedback loop.** Nothing ingests what actually happened — actual
      durations, overruns, cancellations, failures — so the models cannot be monitored
      for drift or retrained. The generator produces ground truth for evaluation; the
      running system has no equivalent.

### 🟡 Housekeeping — small, cheap, worth doing before submission

- [ ] **`web/public/plan.json` is committed** — 2.7 MB, rewritten on every regeneration.
      *Considered and rejected:* git-ignoring it breaks deployment, because the client
      fetches `/plan.json` as a static asset at runtime and the build host has no Python
      or OR-Tools to regenerate it. A clean checkout would deploy an app with no data in
      it. The note now sits in `.gitignore` so the next person does not repeat the
      attempt. Repo size is the cheaper problem; a smaller payload would be the real fix.
- [ ] **`Horizon` is never instantiated** outside a test (`samanvay/domain.py:320`).
      Day 0 is a module constant meaning "Monday"; no part of the system maps a plan to
      a real calendar date, so nothing can be scheduled against an actual week.
- [ ] **`STATUS.md` completion percentages are still judgement, not measurement.** The
      figures they cite are now current, but "~95% complete" is an opinion with a number
      attached. Either derive it from something or drop it.

---

## 3. Current measured results

Regenerated after the fixes above, so these supersede every figure in `README.md` and
`STATUS.md`. 7 days, 600 tasks, Danapur division, 240 s solve, held-out validation on.

| Measure | FCFS baseline | TRACKSEN | Change |
|---|---:|---:|---:|
| Risk retired per block-hour | 8.5 | **19.4** | **+128%** |
| Blocks used | 189 | 146 | −23% |
| Block hours consumed | 623.0 | 450.0 | −28% |
| Departments per block (clubbing) | 1.00 | 1.32 | +32% |
| Traffic cost (wtd detention min) | 72,730 | 46,673 | −36% |
| Corridor adherence | 38% | 73% | +92% |
| Unplanned failures | 73 | 61 | −16% |
| — of which high-criticality | 24 | 16 | −33% |
| Overdue task-days | 3,903 | 3,965 | **+2% worse** |

**Solver:** weekly `FEASIBLE` gap **1.1%**, monthly `FEASIBLE` gap **5.8%**, both at 240 s.

Both sides fell against the run before the withdrawal overheads were enforced (risk
retired per block-hour was 10.98 → 25.49) because **both now pay them**. Fewer jobs fit a
given possession. That is the correct answer and a less flattering one; the ratio between
the two is what the claim rests on, and it held.

The overdue regression is real and is not a bug: the optimiser ranks by criticality, not
by age, so it passes over a long-overdue low-consequence job in favour of a newer defect
about to fail under a premier path. `--overdue` buys it back, at a cost in risk retired.

---

## 4. What is solid

Stated for balance, and because the checklist above is not the whole picture.

- **Four ML models, all held-out validated** — criticality (Spearman ρ against simulator
  ground truth the models never saw), duration (conformal P90, 0.924 coverage against a
  0.90 target), cancellation (0.663 AUC against an oracle ceiling of 0.662), traffic.
- **The CP-SAT model is correct on its own terms** — line exclusivity, junction-throat
  exclusivity across 8 junctions, plant positioning, staffing limits, corridor policy,
  premier-path protection, and now withdrawal nesting. Invariants are tested, not assumed.
- **Ingestion degrades honestly** — REST → read-only DB view → CSV drop, per system, with
  the reason each rung was skipped reported rather than swallowed.
- **The audit chain is real** — SHA-256 hash-chained, append-only, verified on load, and
  replay refuses a broken chain rather than silently trusting it.
- **The topology guard works.** A solver process holding a stale network is detected by
  fingerprint and the client refuses the response instead of quietly switching division.
  This caught two real stale-process incidents during development.
- **The test suite has been shown to fail.** Mutation testing confirmed the tests detect
  the defects they claim to — including one tautological test that was found and fixed.

---

## 5. Suggested order of work

Items 2–7 of the original list are done. What is left, in order:

1. **Run the railpull crawl and import.** The only blocking item, and the importer is
   ready and verified against railpull's own exporter. Everything else on this list is
   smaller.
2. **Bind roles to authenticated identities.** The workflow rules are real and tested;
   the identity behind them is asserted by the caller. Nothing else can be called
   pilotable until this exists.
3. **Persist plan content, not just the decision.** The hash proves which plan was
   signed; storing the plan itself would let you show it.
4. **Close the execution loop** — ingest actual durations, overruns and cancellations so
   the models can be monitored for drift.
5. **Shrink the payload** so `web/public/plan.json` stops being a 2.7 MB commit.
