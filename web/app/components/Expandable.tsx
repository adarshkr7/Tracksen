"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * A card whose contents can be opened full-screen.
 *
 * A divisional schematic with six routes and hundreds of jobs on it, or a day's block
 * chart across thirty-two sections, does not fit a dashboard column at a readable size.
 * Expanding renders exactly the same component in a full-viewport panel — there is no
 * separate "print view" to drift out of step with the real one.
 *
 * Escape closes it, and the page behind is locked so it cannot scroll away underneath.
 */

export default function ExpandableCard({
  title, subtitle, right, children, expandedSubtitle, pad = true,
}: {
  title: string;
  subtitle?: string;
  expandedSubtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  pad?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, close]);

  return (
    <>
      <section className="card">
        <header className="card-head">
          <div className="min-w-0">
            <h2 className="sig" style={{ color: "var(--ink-2)" }}>{title}</h2>
            {subtitle && (
              <p className="text-[11px] mt-0.5 truncate" style={{ color: "var(--ink-3)" }}>
                {subtitle}
              </p>
            )}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {right}
            <button
              onClick={() => setOpen(true)}
              title={`${title} — full screen`}
              className="inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-[4px]
                         text-[11px] font-medium transition-colors"
              style={{ borderColor: "var(--line-2)", background: "var(--surface)",
                       color: "var(--ink-2)" }}
            >
              <ExpandIcon />
              Full screen
            </button>
          </div>
        </header>
        <div className={pad ? "p-3.5" : ""}>{children}</div>
      </section>

      {open && (
        <div
          className="fixed inset-0 z-50 flex flex-col fade-in"
          style={{ background: "rgba(22,33,46,0.55)" }}
          onClick={close}
          role="dialog" aria-modal="true" aria-label={`${title}, full screen`}
        >
          <div
            className="m-3 flex-1 flex flex-col card overflow-hidden"
            style={{ boxShadow: "0 12px 40px #16212e55" }}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="card-head">
              <div className="min-w-0">
                <h2 className="sig" style={{ color: "var(--ink-2)" }}>{title}</h2>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                  {expandedSubtitle ?? subtitle}
                </p>
              </div>
              <div className="ml-auto flex items-center gap-3">
                <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                  Press Esc to close
                </span>
                <button onClick={close}
                  className="rounded-[3px] border px-2.5 py-[5px] text-[11.5px] font-medium"
                  style={{ borderColor: "var(--line-2)", background: "var(--surface)",
                           color: "var(--ink)" }}>
                  Close
                </button>
              </div>
            </header>
            <div className="flex-1 overflow-auto p-5">{children}</div>
          </div>
        </div>
      )}
    </>
  );
}

function ExpandIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"
        stroke="currentColor" strokeWidth="2.1" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  );
}
