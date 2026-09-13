# TRACKSEN — System Audit

**Date:** 12 September 2026
**Scope:** whole repository — backend, solver, governance, web client, documentation
**Test suite:** 211 passing · mutation check 11/11
**Plan:** 7 days, 600 tasks, Danapur division (41 sections, 15 planned), 600 s solve
**Solver:** monthly `OPTIMAL` · weekly `FEASIBLE` 12.9% at 600 s (76.6% at 240 s)
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

### Found later, by the corridor audit — 13 September

Two defects that no test could have caught, because nothing in the repository knew what
the rule was. Both were found by building the check in [ROADMAP.md](ROADMAP.md) item 3 and
pointing it at our own output. See [RESEARCH.md](RESEARCH.md) for the sources.

| # | Defect | Where | Why it mattered |
|---|--------|-------|-----------------|
| 9 | **The corridor was the wrong length, by circular** | `samanvay/network.py:718` | `CORRIDOR_HOURS = 3` hard-coded para 3.0's *floor* of Railway Board's joint circular of 28.12.2016 as though it were para 2.0's *norm* — "One Block of four hours or two blocks of two and half hours". Every downstream figure about what fits a corridor was therefore an artefact of the weaker rule: the monthly plan reported **311 tasks needing an extended block** where the mandated four-hour corridor holds all but a fraction of them. On the 200-task run the count falls from **99 to 40**. Now a named regime with all three settings, defaulting to `single-240`. |
| 10 | **The corridor was a scoring preference, not a cleared window** | `samanvay/network.py:721` | Corridors were placed on a fixed stagger at 10:00, 11:00 or 12:00 by section, with no reference to traffic. The first run of the new audit reported **210 of 210 corridor windows crossed by charted paths — 2,969 services, 17 of them premier** — while the solver collected a +40 adherence bonus for putting blocks there. Corridors are now placed where each section's road is quietest, which is what the Rolling Block Programme says Sr.DOM does, and premier paths are a fence rather than a price: premier fouling went to **zero**. |

It is **still 210 of 210** for booked traffic and that is the correct answer, not a
residual defect: on a division working 543 services there is no four-hour window on any
section with nothing charted through it. Para 2.0 anticipates it — the corridor is then to
be provided "by necessary rescheduling of trains within Zonal Railway" — so the pipeline
reports which windows are cheapest to clear. **A block marked "inside mandated corridor"
on this division is inside a promise the chart does not currently keep**, and both the
pipeline and the Data Sources screen now say so.

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

- [x] **What was approved is now stored, and checked.** The audit chain proved a plan was
      sanctioned and the content hash proved *which* plan, but nothing stored the plan —
      so a restarted service could verify a sanction and be unable to show anybody what
      had been sanctioned.

      `samanvay/governance/planstore.py` keeps every revision of every plan and checks
      what it reads back against the hash recorded beside it. That turns the hash from a
      claim into a test: presented with a plan and an audit entry you can say whether they
      are the same plan, which is the whole reason the hash was worth recording.
      `GET /api/plans/{id}/plan` answers two separate questions — `intact` (has the file
      been edited since it was stored) and `matches_sanctioned` (is this the revision the
      DRM actually signed), which differ because a plan is re-solved several times before
      anyone approves it.

      `Plan.content_hash()` and the store go through one `plan_content_hash()` function.
      A second implementation of "what a plan is, canonically" would drift, and the one
      thing that value must never do is disagree with itself.

      Verified across a cold restart: sanction a plan, kill the service, start it with no
      solve performed, and the 78-block plan comes back with `matches_sanctioned: true`.
      Editing one block's start time on disk flips both flags to false.

- [x] **The API no longer trusts client-supplied identity.** Any caller could POST
      `{"role": "DRM"}` and sanction a plan, which meant every rule in the approval route
      was one JSON field away from being nothing.

      A caller now presents a bearer token; `samanvay/governance/identity.py` resolves it
      to a name and a role; and `actor`/`role` are **gone from the request bodies** rather
      than validated — a field that is sometimes trusted eventually is. Tokens are stored
      as SHA-256 hashes and compared in constant time, so the identity file names who may
      act but does not confer the ability to act. On first run the service mints one token
      per role, prints them once and stores only the hashes; there is deliberately no
      "no identity file means trust the caller" path, because that is an authentication
      system with a hole beside it and the hole is what gets used.

      The client changed to match: the role *selector* is gone, replaced by a sign-in that
      shows whatever `/api/me` resolved the token to. The audit trail records the
      authenticated name, so a refused escalation is logged against who actually tried it.

      What remains a stand-in is the identity *store*, not the identity *check*. A
      deployment swaps it for the divisional directory; the seam is one function wide.

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

- [x] **The timetable now carries published times.** Closed, and it went further than
      planned. Three published sources were evaluated and the best two are merged:

      | | IRCTC_cleaned | data.gov.in | Kaggle | NTES (railpull) |
      |---|---:|---:|---:|---:|
      | Services over this division | **543** | 319 | 319 | 98 |
      | Main-line services | **203** | 101 | 101 | 44 |
      | Stop lists include passing points | yes | no | yes | no |
      | Running days | flattened | none | none | **real** |
      | Vande Bharat present | **yes** | no | no | yes |

      `scripts/import_opendata.py` merges them field by field, because neither is better
      at everything: stops and times from IRCTC, running days from an NTES crawl, and any
      service NTES has that the published extract predates is added whole. 39 sets of
      running days replaced, 11 services added. The frequency spread went from `{1, 7}` —
      a binary, not a timetable — to `{1, 2, 3, 4, 6, 7}`.

      `samanvay/timetable_import.py` holds the part that is the same whatever the source:
      mapping a published stop sequence onto this division's roads.

      **The committed `plan.json` is still built from the shipped approximate timetable.**
      The merged file is git-ignored, because it derives from datasets whose licences
      differ from this repository's. Regenerating it locally is one command, and the
      loader prefers it automatically.

### 🔴 Blocking

- [x] **The gap at realistic traffic density was a search budget, not a formulation
      failure.** Against the merged 543-service timetable the weekly gap is 76.6% at
      240 s — where it was 2.4% against the 212-service authored one. Diagnosed rather
      than guessed: the real road is 2.2x busier, so the objective's traffic term went
      from a tenth of the total to half of it, and criticality and traffic now genuinely
      contend where criticality used to dominate.

      | | authored (212 svc) | published (543 svc) |
      |---|---:|---:|
      | Baseline traffic cost | ~72,000 | **155,321** |
      | Weekly gap @ 240 s | 2.4% | 76.6% |
      | Weekly gap @ 600 s | — | **12.9%** |
      | Monthly @ 600 s | — | **OPTIMAL** |

      More search closes it, so the model is sound and the default budget was simply too
      small for this density. The committed plan is solved at 600 s. Still open below:
      the weekly pass has no symmetry breaking or LNS, which is what would close the
      remaining 12.9% rather than more wall-clock.

### 🔴 Blocking

- [ ] **Nothing blocking.** Every item below is a real limitation, but none of them makes
      a number on a screen wrong.

### 🟠 New, from the authentication work

- [ ] **The estate is still regenerated on every start.** Plans persist; the assets,
      defect history and task population do not — they come from `seed=42` each time, so
      the service always plans the same world. A stored plan therefore references task
      ids that only exist because the seed is fixed. Persisting the estate is the next
      layer, and is what `STATUS.md` means by PostgreSQL.
- [ ] **Tokens are bearer credentials with no expiry and no revocation list.** Losing one
      means deleting the identity file and reissuing every token, because there is no way
      to withdraw a single one. A directory binding solves this; a `revoked` flag would
      be the cheap interim.
- [ ] **The service distinguishes "no such plan" (409) from "not permitted" (403) before
      checking authority**, so an unauthorised caller can probe which plan ids exist.
      Minor — ids are sequential and guessable anyway — and reversing the order would put
      DENIED entries in the audit log for plans that do not exist. Recorded rather than
      changed.
- [ ] **No rate limiting on the token endpoint.** Tokens are 24 random bytes so guessing
      is not a practical attack, but nothing slows an attempt down either.

### Found by putting real data through it

Worth recording separately, because none of these would have surfaced against the
authored timetable:

- **Luckeesarai was on the wrong line.** Modelled as the first station of the Kiul–Gaya
  branch; it is on the Kiul–Patna main line. Every main-line train passing it counted as
  branch traffic — the Gaya branch showed 71 services against the main line's 40. The
  published data made it obvious: 159 calls, as many as Buxar, which no single-line
  branch station produces. Corrected to MAIN 203 / GAYA 13.
- **Station codes collide across the network.** `MDR` resolved to Madhira in Telangana
  rather than Makhdumpur, `KIQ` to "Khai Phemeki". Name-based resolution with an explicit
  alias table replaced it; 40 of 41 stations resolve, and Simariya is deliberately left
  unmatched because every candidate is elsewhere in the country.
- **The importer wrote straight to its target.** A crash mid-write left a truncated
  timetable — and the loader *prefers* the imported file, so the next run planned against
  zero services instead of falling back to the shipped one. It writes to a temporary file
  and moves it into place now.

### 🟠 Significant — real limitations, currently unstated or understated



- [ ] **311 of 600 tasks cannot fit a corridor at all.** Their P90 exceeds the 180-minute
      window, so they are named as needing an extended/mega block rather than scheduled.
      Honest, but it means a third of the backlog is outside what the system plans.
- [ ] **Only the main line is planned.** `PLANNED_ROUTES = ["MAIN"]` (15 of 41 sections).
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
| Risk retired per block-hour | 8.4 | **21.3** | **+154%** |
| Blocks used | 191 | 121 | −37% |
| Block hours consumed | 643.0 | 393.0 | −39% |
| Departments per block (clubbing) | 1.00 | 1.59 | +59% |
| Traffic cost (wtd detention min) | 155,321 | 77,838 | −50% |
| Corridor adherence | 31% | 60% | +94% |
| Unplanned failures | 71 | 63 | −11% |
| — of which high-criticality | 18 | 13 | −28% |
| Overdue task-days | 3,880 | 4,001 | **+3% worse** |

**Solver:** monthly `OPTIMAL`, weekly `FEASIBLE` gap **12.9%**, 600 s each.
Measured against the **published** 543-service timetable, not the authored one.

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

The original list is done. What is left, in order:

1. **Close the execution loop** — ingest actual durations, overruns and cancellations so
   the models can be monitored for drift.
2. **Shrink the payload** so `web/public/plan.json` stops being a 2.7 MB commit.
3. **Handle branch-to-branch services.** 85 trains work Barauni to Hajipur through the
   main line; the timetable schema holds one branch plus one main leg, so they are
   reported and skipped. They are real traffic this division sees.
