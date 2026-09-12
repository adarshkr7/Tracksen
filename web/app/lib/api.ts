/**
 * Client for the TRACKSEN solver service.
 *
 * The static plan in `public/plan.json` is always available; the service adds the
 * things only a running solver can do — re-solve, the approval route, the audit chain,
 * live adapter status. Every call here degrades to `null` rather than throwing, because
 * the UI must stay usable with the backend down (that is the deployed-demo case).
 */

import { PlanData } from "./plan";

export const API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** Alias, for callers that read better with a "base" in the name. */
export const API_BASE = API;

async function call<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 8000,
): Promise<T | null> {
  try {
    const r = await fetch(`${API}${path}`, {
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!r.ok) {
      // 403 / 409 from the approval route are meaningful answers, not transport faults.
      const body = await r.json().catch(() => null);
      throw Object.assign(new Error(body?.detail ?? `HTTP ${r.status}`), {
        status: r.status,
        detail: body?.detail,
      });
    }
    return (await r.json()) as T;
  } catch (e) {
    if ((e as { status?: number }).status) throw e;
    return null;
  }
}

export const health = () => call<{ ok: boolean; ready: boolean }>("/api/health", {}, 2500);

/* ------------------------------------------------------------------ */
/* Data sources                                                        */
/* ------------------------------------------------------------------ */

export interface SourceStatus {
  system: string;
  mode: string;
  connected: boolean;
  degraded: boolean;
  attempted: string[];
  skipped: Record<string, string>;
  fetched: number;
  accepted: number;
  rejected: string[];
  duplicates: number;
  error: string | null;
}

export interface SourcesPayload {
  demo: boolean;
  note: string;
  sources: SourceStatus[];
  unified_tasks: number;
}

export const sources = () => call<SourcesPayload>("/api/sources", {}, 60000);

/* ------------------------------------------------------------------ */
/* Approval route                                                      */
/* ------------------------------------------------------------------ */

export interface ApprovalStatus {
  plan_id: string;
  state: string;
  revision: number;
  departments: string[];
  concurrences: Record<
    string,
    { granted: boolean; by: string; role: string; at: string; remarks: string }
  >;
  operations_cleared_by: string | null;
  sanctioned_by: string | null;
  sanctioned_at: string | null;
  ready_for_sanction: boolean;
  blockers: string[];
}

export interface AuditEntry {
  seq: number;
  timestamp: string;
  actor: string;
  role: string;
  action: string;
  plan_id: string;
  detail: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditPayload {
  plan_id: string;
  entries: AuditEntry[];
  chain: { intact: boolean; entries: number; broken_at: number | null; reason: string | null };
}

/**
 * An approval action. The token identifies the caller; nothing in the body does.
 *
 * These used to take `actor` and `role` and send them, which meant the browser chose its
 * own authority and the service took its word. Both arguments are gone rather than
 * ignored: a parameter that is accepted and discarded invites someone to start trusting
 * it again.
 */
const act = <T>(path: string, token: string, body: unknown) =>
  call<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { Authorization: `Bearer ${token}` },
  });

export const submitPlan = (planId: string, token: string,
                           departments: string[], remarks = "") =>
  act<ApprovalStatus>(`/api/plans/${planId}/submit`, token,
    { plan_id: planId, departments, remarks });

export const concur = (planId: string, token: string,
                       department: string, granted: boolean, remarks = "") =>
  act<ApprovalStatus>(`/api/plans/${planId}/concur`, token,
    { department, granted, remarks });

export const clearOperations = (planId: string, token: string, remarks = "") =>
  act<ApprovalStatus>(`/api/plans/${planId}/clear`, token, { remarks });

export const sanction = (planId: string, token: string, remarks = "") =>
  act<ApprovalStatus>(`/api/plans/${planId}/sanction`, token, { remarks });

export const returnPlan = (planId: string, token: string, remarks: string) =>
  act<ApprovalStatus>(`/api/plans/${planId}/return`, token, { remarks });

export const planStatus = (planId: string) =>
  call<ApprovalStatus>(`/api/plans/${planId}/status`);

export interface StoredPlanPayload {
  plan_id: string;
  revision: number;
  content_hash: string;
  saved_at: string;
  horizon_days: number;
  label: string;
  blocks: { section_id: string; line: string; start_min: number; end_min: number;
            task_ids: string[]; departments: string[] }[];
  unscheduled_task_ids: string[];
  revisions: number[];
  /** Does the stored file still hash to the value saved beside it? */
  intact: boolean;
  sanctioned_hash: string | null;
  /** Is this the revision the DRM actually signed? */
  matches_sanctioned: boolean;
}

/** The plan content behind a plan id — what was approved, not what is loaded now. */
export const storedPlan = (planId: string, revision?: number) =>
  call<StoredPlanPayload>(
    `/api/plans/${planId}/plan${revision !== undefined ? `?revision=${revision}` : ""}`);

export const planAudit = (planId: string) =>
  call<AuditPayload>(`/api/plans/${planId}/audit`);

export const verifyChain = () =>
  call<{ intact: boolean; entries: number; broken_at: number | null;
         reason: string | null; head: string }>("/api/audit/verify");

/* ------------------------------------------------------------------ */
/* Re-solve                                                            */
/* ------------------------------------------------------------------ */

export interface Pin { block_id: string; start_min: number; task_ids: string[] }

/**
 * Re-solve. The token is only needed when `planId` names a plan already in the approval
 * route, because re-solving one invalidates every concurrence given to it — the service
 * answers 401 in that case and nowhere else.
 */
export const resolve = (pins: Pin[], timeLimit = 20, planId?: string,
                        token?: string | null) =>
  call<PlanData>("/api/resolve", {
    method: "POST",
    body: JSON.stringify({ pins, time_limit_s: timeLimit, plan_id: planId }),
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  }, (timeLimit + 25) * 1000);
