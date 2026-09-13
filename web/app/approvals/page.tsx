"use client";

import { useCallback, useEffect, useState } from "react";
import Gate from "../components/Gate";
import { usePlan } from "../components/PlanProvider";
import { useRole } from "../components/RoleProvider";
import {
  Badge, Button, Card, DemoNote, DeptBadge, Empty, Lamp, PageHead,
} from "../components/ui";
import {
  ApprovalStatus, StoredPlanPayload, clearOperations, concur, planStatus, returnPlan,
  sanction, storedPlan, submitPlan,
} from "../lib/api";
import { CURRENT_PLAN_ID } from "../lib/planId";
import { Dept, ROLE_DEPARTMENT } from "../lib/plan";

/**
 * Approval Control.
 *
 * The route a block demand actually travels. Every button here calls the backend and
 * the backend decides: a 403 means the acting role may not do it, a 409 means the plan
 * is not at a stage where it can be done. The UI disables what it can predict will be
 * refused, but it never decides on the backend's behalf — the refusal, and the reason,
 * come from the workflow.
 */

const STAGES = [
  { key: "JE", label: "JE Review", who: "Junior / Section Engineer" },
  { key: "CONCUR", label: "Department Concurrence", who: "Sr.DEN · Sr.DSTE · Sr.DEE/TrD" },
  { key: "CLEAR", label: "Sr.DOM Clearance", who: "Operations — traffic impact" },
  { key: "SANCTION", label: "DRM Sanction", who: "Divisional Railway Manager" },
] as const;

/** The route as drawn: the four decisions plus the state they arrive at. */
const ROUTE = [
  ...STAGES,
  { key: "DONE", label: "Sanctioned", who: "" },
] as const;

function stageIndex(s: ApprovalStatus | null): number {
  if (!s) return -1;
  if (s.state === "SANCTIONED") return 4;
  if (s.operations_cleared_by) return 3;
  if (Object.keys(s.concurrences).length > 0) return 2;
  return 1;
}

export default function ApprovalsPage() {
  return <Gate><ApprovalsBody /></Gate>;
}

function ApprovalsBody() {
  const { plan, apiUp } = usePlan();
  const { session, token } = useRole();
  // Everything the page offers keys off the role the SERVICE resolved, not a
  // choice made here. Hiding a button the token cannot use is a courtesy; the
  // refusal that matters happens on the server either way.
  const role = session?.role ?? null;
  const [status, setStatus] = useState<ApprovalStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [remarks, setRemarks] = useState("");
  const [stored, setStored] = useState<StoredPlanPayload | null>(null);

  const refresh = useCallback(async () => {
    if (!apiUp) return;
    try { setStatus(await planStatus(CURRENT_PLAN_ID)); } catch { setStatus(null); }
    // The content behind the plan id, fetched alongside its approval state. Absent is
    // normal for a plan that was never submitted; a 404 is not an error here.
    try { setStored(await storedPlan(CURRENT_PLAN_ID)); } catch { setStored(null); }
  }, [apiUp]);

  useEffect(() => { refresh(); }, [refresh]);

  const run = useCallback(async (fn: () => Promise<ApprovalStatus | null>) => {
    setBusy(true); setErr(null);
    try {
      const s = await fn();
      if (s) setStatus(s); else await refresh();
      setRemarks("");
    } catch (e) {
      // The backend's refusal is the message worth showing, verbatim.
      const d = (e as { detail?: string }).detail;
      setErr(typeof d === "string" ? d : e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }, [refresh]);

  if (!plan) return null;

  if (!apiUp) {
    return (
      <>
        <PageHead title="Approval Control"
          subtitle="JE → departmental concurrence → Sr.DOM clearance → DRM sanction" />
        <Card>
          <Empty title="Solver service offline">
            The approval route and its audit trail live in the service. Start it to submit,
            concur, clear and sanction:
            <pre className="mono text-[11px] rounded-[3px] p-3 mt-2 text-left inline-block"
              style={{ background: "var(--surface-2)" }}>python scripts/serve.py</pre>
          </Empty>
        </Card>
      </>
    );
  }

  const idx = stageIndex(status);
  const myDept = role ? ROLE_DEPARTMENT[role] : undefined;
  const depts = (status?.departments ?? ["ENGG", "S&T", "TRD"]) as Dept[];

  return (
    <>
      <PageHead
        title="Approval Control"
        subtitle={`Plan ${CURRENT_PLAN_ID} · revision ${status?.revision ?? "—"}`}
        right={
          <>
            <Lamp state={status?.state === "SANCTIONED" ? "ok" : "warn"}
              label={status ? status.state.replace(/_/g, " ") : "NOT SUBMITTED"} />
            <Button onClick={refresh} disabled={busy}>Refresh</Button>
          </>
        }
      />
      <div className="mb-4"><DemoNote>
        Roles are <b>authenticated</b> — a username and password resolve to a session,
        and the session to a name and a role, server-side. Sessions expire and can be
        revoked. The account <b>store</b> is the stand-in: a deployment reads the
        divisional directory instead, under the same rules.
      </DemoNote></div>

      {err && (
        <div className="mb-4 card px-4 py-2.5 text-[12px] fade-in flex items-start gap-3"
          style={{ borderColor: "var(--crit)", color: "var(--crit)" }}>
          <Badge color="var(--crit)" bg="var(--crit-bg)">REFUSED</Badge>
          <span>{err}</span>
          <button onClick={() => setErr(null)} className="ml-auto sig shrink-0"
            style={{ color: "var(--ink-3)" }}>DISMISS</button>
        </div>
      )}

      {/* ---------- the route ----------
          Equal cells in one strip with the stage carried by the underline, rather than
          boxes joined by typed arrows: the arrows wrapped onto a second line on any
          narrow window and left one pointing at nothing. */}
      <Card title="Workflow" className="mb-4" pad={false}>
        <div className="grid" style={{
          gridTemplateColumns: "repeat(auto-fit,minmax(158px,1fr))",
          background: "var(--surface)",
        }}>
          {ROUTE.map((s, i) => {
            // The terminal cell is not a decision, so it lights only once every
            // decision behind it has been taken -- never as "current".
            const terminal = s.key === "DONE";
            const done = terminal ? idx >= STAGES.length : idx > i;
            const current = !terminal && idx === i + 1 && idx < STAGES.length;
            const tone = done ? "var(--ok)" : current ? "var(--rail)" : "var(--ink-3)";
            const rule = done ? "var(--ok)" : current ? "var(--rail)" : "var(--line-2)";
            return (
              <div key={s.key} className="px-3.5 pt-2.5 pb-3 relative"
                style={{
                  boxShadow: "1px 0 0 var(--line), 0 1px 0 var(--line)",
                  background: current ? "var(--rail-bg)" : "var(--surface)",
                }}>
                <div className="flex items-baseline gap-2">
                  <span className="sig tnum" style={{ color: tone }}>{i + 1}</span>
                  <span className="text-[12px] font-semibold leading-tight"
                    style={{ color: tone }}>{s.label}</span>
                </div>
                <div className="text-[10.5px] mt-1" style={{ color: "var(--ink-3)" }}>
                  {s.key === "DONE" ? (status?.sanctioned_by ?? "pending") : s.who}
                </div>
                <span className="absolute left-0 right-0 bottom-0"
                  style={{ height: 2, background: rule }} />
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0,1fr) 360px" }}>
        {/* ---------- concurrence register ---------- */}
        <Card title="Departmental Concurrence" pad={false}>
          <table className="ops">
            <thead>
              <tr>
                <th>Department</th><th>Authority</th><th>Decision</th>
                <th>By</th><th>Timestamp</th><th>Remarks</th>
              </tr>
            </thead>
            <tbody>
              {depts.map((d) => {
                const c = status?.concurrences?.[d];
                return (
                  <tr key={d}>
                    <td><DeptBadge dept={d} showSystem /></td>
                    <td className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {d === "ENGG" ? "Sr.DEN" : d === "S&T" ? "Sr.DSTE" : "Sr.DEE/TrD"}
                    </td>
                    <td>
                      {!c ? <Badge color="var(--ink-3)">Pending</Badge>
                        : c.granted ? <Badge color="var(--ok)" bg="var(--ok-bg)">Concurred</Badge>
                        : <Badge color="var(--crit)" bg="var(--crit-bg)">Withheld</Badge>}
                    </td>
                    <td className="text-[11.5px]">{c?.by ?? "—"}</td>
                    <td className="tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
                      {c ? c.at.slice(0, 19).replace("T", " ") : "—"}
                    </td>
                    <td className="text-[11px]" style={{ color: "var(--ink-3)" }}>
                      {c?.remarks || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {status && status.blockers.length > 0 && (
            <div className="px-3.5 py-3" style={{ borderTop: "1px solid var(--line)" }}>
              <div className="sig mb-1.5" style={{ color: "var(--warn)" }}>
                Outstanding before sanction
              </div>
              {status.blockers.map((b, i) => (
                <div key={i} className="text-[11.5px] flex gap-2 py-[2px]"
                  style={{ color: "var(--ink-2)" }}>
                  <span style={{ color: "var(--warn)" }}>•</span>{b}
                </div>
              ))}
            </div>
          )}
          {stored && (
            <div className="px-3.5 py-3" style={{ borderTop: "1px solid var(--line)" }}>
              <div className="sig mb-1.5">The plan itself</div>
              <div className="text-[11.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                <span className="tnum">{stored.blocks.length}</span> blocks, revision{" "}
                <span className="tnum">{stored.revision}</span>
                {stored.revisions.length > 1 &&
                  ` of ${stored.revisions.length} stored`}. Fingerprint{" "}
                <span className="mono">{stored.content_hash.slice(0, 12)}…</span>
              </div>
              {/* The two checks are different questions and both are worth stating:
                  one asks whether the stored file has been edited, the other whether
                  this is the revision the DRM actually put their name to. */}
              <div className="flex flex-col gap-1 mt-2">
                <Check ok={stored.intact}
                  yes="Content matches its stored fingerprint"
                  no="Content has been altered since it was stored" />
                {stored.sanctioned_hash && (
                  <Check ok={stored.matches_sanctioned}
                    yes="This is the revision that was sanctioned"
                    no="NOT the revision that was sanctioned" />
                )}
              </div>
            </div>
          )}
        </Card>

        {/* ---------- actions ---------- */}
        <Card title="Actions"
          subtitle={session ? `Signed in as ${session.name} · ${session.role}`
                             : "Sign in to act on this plan"}>
          <textarea
            value={remarks} onChange={(e) => setRemarks(e.target.value)}
            placeholder="Remarks (recorded in the audit trail)"
            rows={3}
            className="w-full rounded-[3px] border px-2.5 py-2 text-[11.5px] outline-none mb-3 resize-none"
            style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
          />

          {!session && (
            <div className="rounded-[3px] border px-3 py-2.5 mb-3 text-[11.5px] leading-relaxed"
              style={{ borderColor: "var(--line-2)", background: "var(--surface-2)",
                       color: "var(--ink-2)" }}>
              <b>Not signed in.</b> The approval route needs an account — sign in from
              the top bar. The plan itself is readable without one.
            </div>
          )}

          <div className="space-y-2" style={{ opacity: session ? 1 : 0.45,
                                              pointerEvents: session ? "auto" : "none" }}>
            {!status && (
              <Button variant="primary" disabled={busy}
                onClick={() => run(() => submitPlan(
                  CURRENT_PLAN_ID, token!, ["ENGG", "S&T", "TRD"], remarks))}>
                Submit plan into the route
              </Button>
            )}

            {status && myDept && (
              <div className="flex gap-2">
                <Button variant="primary" disabled={busy}
                  onClick={() => run(() => concur(
                    CURRENT_PLAN_ID, token!, myDept, true, remarks))}>
                  Concur for {myDept}
                </Button>
                <Button variant="danger" disabled={busy}
                  onClick={() => run(() => concur(
                    CURRENT_PLAN_ID, token!, myDept, false, remarks))}>
                  Withhold
                </Button>
              </div>
            )}

            {status && role === "Sr.DOM" && (
              <Button variant="primary" disabled={busy}
                onClick={() => run(() => clearOperations(CURRENT_PLAN_ID, token!, remarks))}>
                Clear traffic impact
              </Button>
            )}

            {status && role === "DRM" && (
              <Button variant="primary" disabled={busy}
                onClick={() => run(() => sanction(CURRENT_PLAN_ID, token!, remarks))}>
                Sanction plan
              </Button>
            )}

            {status && role !== "JE" && role !== "Viewer" && (
              <Button disabled={busy || !remarks.trim()}
                title={remarks.trim() ? "" : "Returning a plan requires remarks"}
                onClick={() => run(() => returnPlan(CURRENT_PLAN_ID, token!, remarks))}>
                Return for revision
              </Button>
            )}
          </div>

          <p className="text-[10.5px] mt-3 pt-3 leading-relaxed"
            style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
            {myDept
              ? `As ${role} you may concur for ${myDept} only. Another department's work is someone else's accountability.`
              : role === "DRM"
              ? "Only the DRM may sanction, and only once every department has concurred and operations has cleared."
              : role === "Sr.DOM"
              ? "Traffic clearance comes after departmental concurrence, not before."
              : role
              ? "This role cannot concur, clear or sanction. Sign in as somebody who can."
              : "Sign in to act. Browsing the plan needs no account; acting on it does."}
          </p>
        </Card>
      </div>
    </>
  );
}

/** A verified/failed assertion about the stored plan. A lamp carries the state to a
 *  reader who does not distinguish the two greens and reds, and it is the same lamp
 *  used everywhere else for a pass or a fail. */
function Check({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px]"
      style={{ color: ok ? "var(--ok)" : "var(--crit)" }}>
      <i className={`lamp lamp-${ok ? "ok" : "crit"}`} />
      {ok ? yes : no}
    </span>
  );
}
