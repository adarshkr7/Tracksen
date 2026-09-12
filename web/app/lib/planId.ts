/**
 * The plan currently in front of the division.
 *
 * A single well-known id keeps the approval route, the audit trail and the dashboard
 * looking at the same thing. A multi-division deployment would key this by division and
 * horizon; for one corridor and one horizon, a constant is honest and sufficient.
 */
export const CURRENT_PLAN_ID = "WEEKLY-CURRENT";
