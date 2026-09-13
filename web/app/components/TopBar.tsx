"use client";

/**
 * Operational context strip.
 *
 * Division, horizon, solver status and who is signed in — the things a controller needs
 * on screen at all times to know *which* plan they are looking at and *as whom*.
 *
 * Everything here is one line or it is not here. A header that wraps its own fields onto
 * three lines when the window narrows stops being a fixed reference point, so the fields
 * drop out in order of importance instead: solver first, then section, then the estate
 * lamp's label. Nothing that drops is unavailable — it is on the page it belongs to.
 *
 * The identity shown is not a selector. It is whatever the service resolved this tab's
 * session to; there is nothing here to pick, which is the point. It carries an expiry,
 * so it is shown -- a control-room screen that says "DRM" without saying "for another
 * 40 minutes" is telling half the truth.
 */

import { useState } from "react";
import { usePlan } from "./PlanProvider";
import { useRole } from "./RoleProvider";
import SignIn from "./SignIn";

/**
 * How much of this session is left, in words a glance can take in.
 *
 * Rounded down deliberately: "expires in 1 minute" and then a refusal is worse than
 * "expires in under a minute" and then a refusal.
 */
function remaining(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return "expired";
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "under a minute left";
  if (minutes < 60) return `${minutes}m left`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m left`;
}

export default function TopBar() {
  const { plan, apiUp, loading } = usePlan();
  const { session, checking, signOut, endedReason } = useRole();
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
      <Field label="Section" value="BXR–PNBE–JAJ · 281 km" at="lg" />
      <Divider at="lg" />
      <Field label="Horizon" value={`${horizon} days`} />
      <Divider at="xl" />
      <Field
        label="Solver"
        at="xl"
        value={
          loading ? "loading…"
            : gap !== undefined ? `feasible · ${Number(gap).toFixed(1)}% gap`
            : "static plan"
        }
      />

      <div className="ml-auto flex items-center gap-4 shrink-0">
        <span
          className="inline-flex items-center gap-2 whitespace-nowrap"
          title={apiUp ? "Solver service reachable" : "Serving the last saved plan file"}
        >
          <i className={`lamp lamp-${apiUp ? "ok" : "warn"}${apiUp ? " lamp-live" : ""}`} />
          <span className="sig hidden md:inline">
            {apiUp ? "System Operational" : "Plan-Only Mode"}
          </span>
        </span>

        <div className="flex items-center gap-2.5 pl-4 whitespace-nowrap"
          style={{ borderLeft: "1px solid var(--line)" }}>
          {checking ? (
            <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              checking session…
            </span>
          ) : session ? (
            <>
              <span className="text-right leading-none hidden sm:block">
                <span className="sig block">
                  {session.role}
                  {session.expiresAt && (
                    <span style={{ color: "var(--ink-3)" }}>
                      {" · "}{remaining(session.expiresAt)}
                    </span>
                  )}
                </span>
                <span className="block text-[12px] font-medium mt-[3px]"
                  style={{ color: "var(--ink)" }}>
                  {session.name}
                </span>
              </span>
              <button
                onClick={signOut}
                title="End this session, here and on the service"
                className="rounded-[3px] border px-2.5 py-[5px] text-[11.5px] font-medium"
                style={{ borderColor: "var(--line-2)", background: "var(--surface)",
                         color: "var(--ink-2)" }}
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <span className="sig hidden sm:inline"
                style={endedReason ? { color: "var(--warn)" } : undefined}
                title={endedReason ?? undefined}>
                {endedReason ? "Session ended" : "Read-only"}
              </span>
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

/** `at` is the width below which the field gives up its space. */
function Field({ label, value, at }: { label: string; value: string; at?: "lg" | "xl" }) {
  const hide = at === "lg" ? "hidden lg:block" : at === "xl" ? "hidden xl:block" : "";
  return (
    <div className={`leading-none whitespace-nowrap ${hide}`}>
      <div className="sig">{label}</div>
      <div className="text-[12px] font-medium mt-[3px] tnum" style={{ color: "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}

function Divider({ at }: { at?: "lg" | "xl" }) {
  const hide = at === "lg" ? "hidden lg:block" : at === "xl" ? "hidden xl:block" : "";
  return <span className={`h-7 w-px shrink-0 ${hide}`} style={{ background: "var(--line)" }} />;
}
