# SAMANVAY

SAMANVAY is a synthetic-data prototype for coordinating railway maintenance across
Engineering, Signal & Telecom and Traction Distribution. It normalizes departmental
records, estimates risk and duration, and recommends weekly or monthly block plans.
The competent authority reviews and sanctions a proposal; the solver never grants a block.

The September 2026 code-review fixes correct the overdue objective, machine sharing,
approval state transitions, proposal binding, pin failures, midnight traffic pricing,
stability, cancellation scoring, monthly accounting and persisted audit verification.
Previously published benchmark numbers predate those fixes and must not be reused.
See [STATUS.md](STATUS.md) for the remaining scope limitations and
[docs/review-fixes.md](docs/review-fixes.md) for validation results.

## Run locally

Use Python 3.12+ and Node.js 20.9+.

```bash
python -m venv .venv
# Activate .venv using your shell's activation script.
python -m pip install -r requirements-dev.txt
python -m pytest
python scripts/run_pipeline.py --days 7 --tasks 200 --time-limit 90 --monthly
```

On macOS, LightGBM requires an OpenMP runtime (`brew install libomp`).
`requirements.txt` includes the Cox model's `lifelines` dependency; development
requirements additionally install pytest and the HTTP test client.

```bash
cd web
npm ci
npm run sync
npm run build
npm run dev
```

The static page reads `public/plan.json`. Generate and sync it after changing the
models or scheduler. Without the API, the page supports local what-if exploration.

```bash
python scripts/serve.py
```

Run the local service as **one process/worker**. Its proposal workflow serializes
revision checks, solving and state publication. The web client loads a service-generated
proposal when the service is reachable, records its ID in `?plan=...`, and includes the
revision and content hash when re-solving. Failed requests preserve the displayed
proposal and the user's moves. Persisted proposals can be reloaded by ID.

## Scheduling semantics

Tasks are keyed by section, line and chainage. Candidate eligibility currently checks
section/line, duration and night-working permission. Cross-department tasks may share a
block, with at most one task per department and one simultaneous user of each machine
type. **The prototype assumes one machine of each non-NONE type network-wide.**
Line occupancy, a fixed 90-minute machine positioning buffer and daily department caps
are enforced. These simplified constraints do not constitute a complete operational
safety or regulatory model.

The objective rewards criticality, cross-department coordination, corridor use, avoided
lateness and retained task placements, and charges traffic and cancellation cost:

- Avoided lateness is measured against leaving each task overdue until horizon end.
  This is equivalent to charging unscheduled work its remaining overdue cost, up to
  an objective constant. Increasing the overdue weight no longer rewards dropping work.
- Stability rewards keeping a previously placed task at the same section, line and
  start time. Moving or dropping it forfeits the reward. This is an explicit preference;
  hard pins remain the way to require exact placements and membership.
- Cancellation features use the candidate's time, season and corridor membership.
  The objective charges expected cancelled tasks; each output block also carries its
  placement-specific cancellation probability, using the maximum member probability.
  Task-level probabilities are labeled priors, not the selected placement's score.
- Traffic windows include trains that entered before midnight and remain in the section.

Defaults: criticality 1, clubbing 25, traffic 0.05, overdue 1.5, corridor 40,
stability 10 and cancellation 10. The API accepts nonnegative finite weights.
CLI flags expose clubbing, traffic, overdue and corridor; the remaining defaults are
in `OptimiserWeights`. The solver's objective/gap applies to its enumerated candidates
and modeled rules only.

Duration models report P50 and reserve at least P90. Candidate capacity can exceed the
longest P90; the output returns that unused portion. Monthly planning uses corridor
slots; extended-block tasks remain in unscheduled totals and are also listed separately.
Weekly and monthly plans remain independent.

## Bound proposals and approvals (API v2)

`GET /api/plan` generates and stores a draft containing the actual schedule, derived
department scope and estate fingerprint. Response metadata includes `plan_id`,
`revision`, `content_hash` and `state`. `GET /api/plan?plan_id=...` reloads it.
An unknown ID cannot be submitted as a metadata-only placeholder.

Every edit/approval request carries the revision and content hash the caller reviewed.
A stale request returns 409. Example body for approval actions:

```json
{
  "actor": "Example officer",
  "role": "Sr.DOM",
  "revision": 1,
  "content_hash": "<64-character hash from the proposal metadata>",
  "remarks": "Reviewed this revision"
}
```

| Endpoint | Behavior |
|---|---|
| `POST /api/plans/{id}/submit` | JE submits an existing draft; department lists are not accepted |
| `POST /api/plans/{id}/concur` | Department head concurs/withholds; add `department` and optional `granted` |
| `POST /api/plans/{id}/clear` | Sr.DOM clears after all departmental concurrences |
| `POST /api/plans/{id}/sanction` | DRM sanctions only the valid operations-review state |
| `POST /api/plans/{id}/return` | Return for revision; invalidates concurrence and clearance |
| `POST /api/plans/{id}/cancel` | DRM/Sr.DOM cancels a sanctioned proposal |
| `POST /api/resolve` | JE revises an editable proposal; add `plan_id`, `pins`, optional `weights`, `time_limit_s` |
| `GET /api/plans/{id}/status` | State, revision, content hash and remaining blockers |
| `GET /api/plans/{id}/audit` | Persisted events, snapshots and integrity status |
| `GET /api/audit/verify` | Verify persisted bytes and the running audit head |

For resolve, each pin is `{block_id, start_min, task_ids}` and must match a stored
block's membership. Duplicate IDs, unknown tasks and contradictory placements are
refused. INFEASIBLE returns 422 with pin reasons; UNKNOWN/no incumbent returns 503.
Neither changes the current proposal. Sanctioned and terminal plans cannot be edited;
returns require revision, and cancelled/superseded plans cannot be reactivated.

**Identity remains a demo stand-in.** The caller supplies the actor and role; the web
client explicitly uses “Demo planner / JE”. This is not authentication. Bind `_actor`
to verified identity before allowing real approval authority.

## Standby suggestions

`POST /api/plans/{id}/standby` takes the usual actor/revision/hash plus
`released_block_id`, `ready_task_ids` and optional `time_limit_s`. The planner must
explicitly identify ready tasks from the unscheduled queue. The solver considers those
tasks inside the released slot while fixing all unaffected work, checking the same
prototype constraints. The result is a **new draft**, with a ranked compatible
`standbyQueue`. It neither cancels the original nor inherits its approvals. If no ready
replacement fits, the request is refused. There is no automatic operational cancellation
feed or automatic block handover.

## Persistence and audit boundary

Each workflow transition appends a complete revision-bound approval state to
`out/audit.jsonl` before publishing it in memory. Startup replays those events; legacy
metadata-only events cannot restore approval authority. Thread/process file locks
prevent interleaved writes and stale writers fail closed. Verification rereads the file,
checks hashes, and compares it with the process's known history; runtime deletion,
truncation and edits are detected.

This is a local event log, not an independently secured records system. Detecting an
attacker who rewrites the whole file while the service is stopped requires an external
trusted hash anchor or immutable storage. A damaged log must be investigated; do not
silently discard it to restart the service.

## Tests and interpretation

```bash
python -m pytest
python scripts/mutation_check.py
python scripts/validate.py --folds 5
```

Regression tests cover the review's failure cases, including revision binding, denied
edits without solver/state changes, concurrent audit appends, restart restoration,
conflicting pins, explicit stability/cancellation costs and monthly task accounting.
No real railway data is used. Results compare two policies under the same synthetic
instance; they are not estimates of savings or proof of safe railway operation.
