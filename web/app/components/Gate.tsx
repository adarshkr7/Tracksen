"use client";

/**
 * Loading and failure states for any screen that needs the plan.
 *
 * A control-room screen that silently shows nothing is worse than one that says what is
 * missing and how to produce it, so the failure case names the exact command.
 */

import { usePlan } from "./PlanProvider";

export default function Gate({ children }: { children: React.ReactNode }) {
  const { plan, loading, error } = usePlan();

  if (loading) {
    return (
      <div className="card p-4">
        <div className="sig mb-3">Loading plan…</div>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 rounded-[3px] animate-pulse"
              style={{ background: "var(--surface-2)" }} />
          ))}
        </div>
      </div>
    );
  }

  if (error || !plan) {
    return (
      <div className="card p-5 max-w-2xl">
        <h2 className="text-[14px] font-semibold mb-1" style={{ color: "var(--crit)" }}>
          No plan loaded
        </h2>
        <p className="text-[12px] mb-3" style={{ color: "var(--ink-2)" }}>
          {error ?? "plan.json is missing."} Generate one and copy it into the app:
        </p>
        <pre className="mono text-[11px] rounded-[3px] p-3 overflow-x-auto"
          style={{ background: "var(--surface-2)", color: "var(--ink-2)" }}>
{`python scripts/run_pipeline.py --days 7 --tasks 200 --monthly --validate
cd web && npm run sync`}
        </pre>
      </div>
    );
  }

  return <>{children}</>;
}
