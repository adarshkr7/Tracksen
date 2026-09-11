# SAMANVAY implementation status

Updated after the September 2026 code review. No completion percentage is claimed.

Implemented: synthetic departmental feeds and adapters; unified task representation;
criticality classifier, Cox model and SHAP; P50/P90 duration with conformal calibration;
traffic pricing; weekly/monthly CP-SAT scheduling; FCFS comparison; fixed-resource
constraints; explicit stability and placement-aware cancellation costs; validated pins;
readiness-driven standby proposals; snapshot-bound, persisted approval workflow;
audit verification; and the web visualization/what-if interface.

The numbered review defects are addressed by the implementation and regression tests
in [docs/review-fixes.md](docs/review-fixes.md). The earlier claimed benchmark improvements
and completion percentages are superseded. Use the recorded post-fix run or regenerate
results from the current source.

Still outside the implemented operational scope:

- Real railway feeds, authenticated identities and actual sanction authority.
- Measured resource inventories/availability, crew rosters and distance-dependent plant travel.
- Chainage-distance compatibility policy, power/disconnection containment rules,
  possession permissions, and a validated regulatory constraint set.
- Train dispatch/rescheduling and executable conflict-free revised train timetables.
- Automatic cancellation/release events; standby readiness comes from a planner.
- Execution records feeding retraining, drift monitoring and rolling nightly planning.
- Monthly allocations constraining the weekly schedule.
- A full approval UI and multi-user identity experience.
- Multi-process workflow writers or a production database; use one service worker.
- Independent audit anchoring against offline whole-log replacement.

This is a decision-support prototype. Operational policy gaps require real inputs and
validated rules; substituting invented railway rules would not close them.
