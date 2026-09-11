# Review fixes and validation

Base commit: `622fb8c62ece0b0ca033ca115b12b2c1f1095ae2`.
Branch: `fix/review-correctness`.

## Fix coverage

| Review | Implementation |
|---|---|
| 1 — Invalid approval transitions | Explicit editable/review/terminal state gates; returns and changed concurrence invalidate clearance |
| 2 — Denied edit changes last plan | Permission/revision checks before solving; publish only after successful persisted transition |
| 3 — Unbound approvals | Stored schedule snapshot, estate fingerprint, derived departments, revision/hash checks, restart replay, updated client |
| 4 — Overdue incentive | Avoided lateness measured against horizon-end unscheduled cost |
| 5 — Shared machine inside clubbing | AtMostOne member per machine type per block under the one-unit prototype fleet |
| 6 — Infeasible pins return success | 422 for invalid/infeasible constraints, 503 for no incumbent; keep previous plan/moves |
| 7 — Missing dependency | Declare lifelines; add development requirements and macOS runtime notes |
| 8 — Overwritten pins | Reject repeated block/task IDs, mixed unknown IDs and mismatched stored membership |
| 9 — Midnight traffic | Index every occupied day; deduplicate query hits and consequence counts |
| 10 — Missing stability cost | Explicit retained-position reward, by task/location/time rather than candidate ID |
| 11 — Cancellation disconnected | Candidate-specific scoring/objective; block-specific output and baseline metrics; readiness-driven standby proposal API |
| 12 — Monthly undercount | Extended tasks remain unscheduled and solver report/metrics agree |
| 13 — Cached-only audit check | Locked disk verification, durable write before state publication, stale-writer rejection |

Other integration corrections: no extra task may be added to a pinned block; proposal
reloads preserve weights; monthly results remain available after service loading and
weekly re-solves; mutation checks now run relative to the repository on any OS and do
not count skipped anchors or infrastructure failures as caught mutations.

## Validation

The full Python suite passes: **154 passed, no skipped tests**. This includes the new
counterexamples and the regenerated pipeline payload check. The frontend production build and TypeScript
checks pass. All 11 historical mutations were caught. Full weekly/monthly CLI generation
and payload synchronization were exercised. No live railway data or real approval
identity was used. Model training algorithms were unchanged; five-fold model validation
was not rerun.

## Post-fix benchmark

Command: `python scripts/run_pipeline.py --days 7 --tasks 200 --time-limit 90 --monthly`.
Seed: 42. Weekly solver: OPTIMAL; gap
0.0%; solver wall time 75.78 s.
Monthly solver: OPTIMAL; gap 0.0%.

| Measure | FCFS | SAMANVAY |
|---|---:|---:|
| Tasks scheduled | 103 | 109 |
| Blocks used | 103 | 79 |
| Block hours | 282.0 | 200.75 |
| Risk retired per block-hour | 15.14 | 30.02 |
| Traffic cost | 18280.2 | 13092.6 |
| Overdue task-days | 1242 | 1206 |
| Expected cancellations | 28.36 | 16.15 |
| Unplanned failures (simulation) | 42 | 30 |

Monthly: 111 scheduled and
89 unscheduled out of 200;
81 unscheduled tasks require an extended block.

These are results for one synthetic instance. They replace the earlier numbers and
are not a guarantee of real operational savings. The optimality result applies only
to the encoded candidate set, costs and simplified constraints.

## API migration and limits

Clients must first obtain a stored proposal from GET /api/plan, then supply its
plan_id, revision and content_hash for edits. Approval requests supply revision/hash;
department scope is derived from the schedule and cannot be sent by the caller.
Use one service process. Legacy metadata-only audit entries are retained as history
but cannot restore authority over an unidentified schedule.

Standby requests create a new draft and require an explicit ready-task list; original
approvals do not carry over. Runtime audit edits/truncation are detected, but protection
against offline whole-log rewriting requires an external trusted anchor.

Authenticated identity, real resource availability, validated power/disconnection
containment rules, chainage-distance compatibility, execution feedback and rolling
weekly/monthly coordination remain outside this prototype. See STATUS.md. These are
not replaced with invented policies in this patch.
