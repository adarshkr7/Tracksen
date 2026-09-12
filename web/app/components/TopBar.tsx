"use client";

/**
 * Operational context strip.
 *
 * Division, horizon, solver status and the acting role — the things a controller needs
 * on screen at all times to know *which* plan they are looking at and *as whom*.
 *
 * The role selector is not authentication. It chooses the capacity a request is made in;
 * the backend enforces what that capacity may do and refuses anything else. Saying so
 * here is better than implying an identity system that does not exist.
 */

import { useRole } from "./RoleProvider";
import { usePlan } from "./PlanProvider";
import { Lamp } from "./ui";
import { ROLES } from "../lib/plan";

export default function TopBar() {
  const { plan, apiUp, loading } = usePlan();
  const { actor, role, setRole, setActor } = useRole();

  const horizon = plan?.meta.horizon_days ?? 7;
  const gap = plan?.meta.solver?.gap_pct;

  return (
    <header
      className="fixed top-0 right-0 z-20 flex items-center gap-4 px-5"
      style={{
        left: "var(--sidebar-w)", height: "var(--topbar-h)",
        background: "var(--surface)", borderBottom: "1px solid var(--line-2)",
      }}
    >
      <Field label="Division" value="Danapur (DNR)" />
      <Divider />
      <Field label="Section" value="BXR–PNBE–JAJ · 281 km" />
      <Divider />
      <Field label="Planning Horizon" value={`${horizon} days`} />
      <Divider />
      <Field
        label="Solver"
        value={
          loading ? "loading…"
            : gap !== undefined ? `feasible · ${Number(gap).toFixed(1)}% gap`
            : "static plan"
        }
      />

      <div className="ml-auto flex items-center gap-4">
        <Lamp
          state={apiUp ? "ok" : "warn"}
          live={apiUp}
          label={apiUp ? "SYSTEM OPERATIONAL" : "PLAN-ONLY MODE"}
        />

        <div className="flex items-center gap-2 pl-4"
          style={{ borderLeft: "1px solid var(--line)" }}>
          <div className="text-right leading-none">
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              aria-label="Acting officer name"
              className="text-[12px] font-medium text-right bg-transparent outline-none w-[104px]"
              style={{ color: "var(--ink)" }}
            />
            <div className="sig mt-[3px]">Acting as</div>
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            aria-label="Acting role"
            className="rounded-[3px] border px-2 py-[5px] text-[11.5px] font-medium outline-none"
            style={{
              borderColor: "var(--line-2)", background: "var(--surface-2)",
              color: "var(--rail)",
            }}
          >
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>
    </header>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="leading-none">
      <div className="sig">{label}</div>
      <div className="text-[12px] font-medium mt-[3px] tnum" style={{ color: "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}

function Divider() {
  return <span className="h-7 w-px" style={{ background: "var(--line)" }} />;
}
