"use client";

/**
 * TRACKSEN wordmark.
 *
 * The mark is a length of track seen in plan — two rails, sleepers, and a switch
 * diverging to a second route, with a signal lamp at the junction. Track plus a
 * decision point plus a signal is the whole product in one glyph: infrastructure,
 * a choice about it, and an indication of whether it is safe.
 *
 * Deliberately not derived from any Indian Railways emblem. TRACKSEN is not an
 * official Indian Railways product and the mark must not imply that it is.
 */

export function TracksenMark({ size = 22, color = "currentColor" }: {
  size?: number; color?: string;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      aria-hidden="true" style={{ flex: "none" }}>
      {/* main route */}
      <path d="M2 15.5h20" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M2 18.5h20" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
      {/* sleepers */}
      <path d="M5 15.5v3M9 15.5v3M13 15.5v3M17 15.5v3M21 15.5v3"
        stroke={color} strokeWidth="1" opacity="0.5" strokeLinecap="round" />
      {/* the switch: a second route diverging */}
      <path d="M9 15.5C13 15.5 16 11 21 11" stroke={color} strokeWidth="1.6"
        strokeLinecap="round" />
      {/* signal at the junction */}
      <circle cx="6" cy="7" r="2.4" stroke={color} strokeWidth="1.5" />
      <path d="M6 9.4v4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export default function Brand({ compact = false, onDark = true }: {
  compact?: boolean; onDark?: boolean;
}) {
  const ink = onDark ? "var(--chrome-ink)" : "var(--ink)";
  const sub = onDark ? "var(--chrome-ink-2)" : "var(--ink-3)";

  return (
    <div className="flex items-center gap-2.5">
      <span style={{ color: onDark ? "#e7ecf2" : "var(--rail)" }}>
        <TracksenMark size={compact ? 20 : 23} />
      </span>
      {!compact && (
        <span className="leading-none">
          <span className="block font-bold tracking-[0.14em] text-[15px]"
            style={{ color: ink }}>
            TRACKSEN
          </span>
          <span className="block mt-[3px] text-[9.5px] tracking-[0.045em]"
            style={{ color: sub }}>
            AI-Powered Railway Maintenance Intelligence
          </span>
        </span>
      )}
    </div>
  );
}
