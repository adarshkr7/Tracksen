"use client";

/**
 * Operational context strip.
 *
 * Division, horizon, solver status and who is signed in — the things a controller needs
 * on screen at all times to know *which* plan they are looking at and *as whom*.
 *
 * The role selector is not authentication. It chooses the capacity a request is made in;
 * the backend enforces what that capacity may do and refuses anything else. Saying so
 * here is better than implying an identity system that does not exist.
 */

import { useRole } from "./RoleProvider";
import { useState } from "react";
import { usePlan } from "./PlanProvider";
import SignIn from "./SignIn";
import { Lamp } from "./ui";

export default function TopBar() {
  const { plan, apiUp, loading } = usePlan();
  const { session, checking, signOut } = useRole();
  const [signingIn, setSigningIn] = useState(false);

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

        {/* Identity, not a choice. The role shown is whatever the service resolved the
            token to; there is nothing here to pick, which is the point. */}
        <div className="flex items-center gap-2 pl-4"
          style={{ borderLeft: "1px solid var(--line)" }}>
          {checking ? (
            <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              checking session…
            </span>
          ) : session ? (
            <>
              <div className="text-right leading-none">
                <div className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
                  {session.name}
                </div>
                <div className="sig mt-[3px]">Signed in as</div>
              </div>
              <span
                className="rounded-[3px] border px-2 py-[5px] text-[11.5px] font-medium"
                style={{
                  borderColor: "var(--line-2)", background: "var(--surface-2)",
                  color: "var(--rail)",
                }}
              >
                {session.role}
              </span>
              <button
                onClick={signOut}
                className="text-[11px] underline"
                style={{ color: "var(--ink-3)" }}
              >
                sign out
              </button>
            </>
          ) : (
            <>
              <div className="text-right leading-none">
                <div className="text-[12px] font-medium" style={{ color: "var(--ink-3)" }}>
                  Not signed in
                </div>
                <div className="sig mt-[3px]">Read-only</div>
              </div>
              <button
                onClick={() => setSigningIn(true)}
                className="rounded-[3px] px-3 py-[5px] text-[11.5px] font-medium"
                style={{ background: "var(--chrome)", color: "#fff" }}
              >
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
      {signingIn && <SignIn onClose={() => setSigningIn(false)} />}
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
