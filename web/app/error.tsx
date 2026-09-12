"use client";

import { useEffect } from "react";

/**
 * Route-level error boundary.
 *
 * Without one, a throw during render blanks the page: no message, no way back, and
 * nothing in front of the user that says what went wrong. That is the worst failure
 * mode for a control-room screen, because a blank panel and a working panel showing
 * nothing look identical.
 *
 * The failures worth catching here are the honest ones the code raises deliberately —
 * a plan.json missing the solver's pricing weights, say, which what-if refuses to
 * substitute a guess for. Those should surface as a stated reason, not a white screen.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("TRACKSEN screen failed:", error);
  }, [error]);

  return (
    <div className="card p-6 max-w-2xl">
      <div className="sig mb-2" style={{ color: "var(--crit)" }}>
        Screen unavailable
      </div>
      <p className="text-[13px] mb-3" style={{ color: "var(--ink-2)" }}>
        This screen could not be rendered. The rest of the control centre is unaffected —
        the plan itself is not modified by anything on this page.
      </p>
      <pre
        className="mono text-[11.5px] rounded-[3px] p-3 mb-4 whitespace-pre-wrap"
        style={{ background: "var(--surface-2)", color: "var(--ink-2)" }}
      >
        {error.message || "No message was attached to the error."}
      </pre>
      <div className="flex items-center gap-2">
        <button
          onClick={reset}
          className="rounded-[3px] px-3 py-[6px] text-[12px] font-medium"
          style={{ background: "var(--chrome)", color: "#fff" }}
        >
          Try again
        </button>
        <a
          href="/"
          className="rounded-[3px] border px-3 py-[6px] text-[12px]"
          style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}
        >
          Back to dashboard
        </a>
      </div>
      {error.digest && (
        <div className="mono text-[10.5px] mt-3" style={{ color: "var(--ink-3)" }}>
          digest {error.digest}
        </div>
      )}
    </div>
  );
}
