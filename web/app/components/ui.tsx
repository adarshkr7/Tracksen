"use client";

/**
 * Shared primitives.
 *
 * Kept deliberately plain: flat surfaces, 1px rules, 4px corners. Colour is reserved
 * for operational meaning — a badge is coloured because it carries a status, never
 * because a card needed brightening.
 */

import { Band, BAND_COLOR, BAND_LABEL } from "./PlanProvider";
import { DEPT_BLOCK, DEPT_COLOR, DEPT_NAME, DEPT_SYSTEM, Dept } from "../lib/plan";

export { DEPT_BLOCK, DEPT_COLOR, DEPT_NAME, DEPT_SYSTEM };

/* ------------------------------------------------------------------ */

export function Card({ title, subtitle, right, children, className = "", pad = true }: {
  title?: string; subtitle?: string; right?: React.ReactNode;
  children: React.ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <header className="card-head">
          <div className="min-w-0">
            <h2 className="sig" style={{ color: "var(--ink-2)" }}>{title}</h2>
            {subtitle && (
              <p className="text-[11px] mt-0.5 truncate" style={{ color: "var(--ink-3)" }}>
                {subtitle}
              </p>
            )}
          </div>
          {right && (
            <div className="head-tools ml-auto flex items-center gap-2">{right}</div>
          )}
        </header>
      )}
      <div className={pad ? "p-3.5" : ""}>{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------------ */

export function Metric({
  label, value, unit, delta, hint, tone = "ink", compare,
}: {
  label: string; value: string; unit?: string;
  delta?: { pct: number; better: boolean };
  hint?: string; tone?: "ink" | "ok" | "warn" | "crit" | "rail"; compare?: string;
}) {
  const colour = {
    ink: "var(--ink)", ok: "var(--ok)", warn: "var(--warn)",
    crit: "var(--crit)", rail: "var(--rail)",
  }[tone];

  return (
    <div className="px-3.5 py-3" style={{ background: "var(--surface)" }} title={hint}>
      <div className="sig">{label}</div>
      <div className="flex items-baseline gap-1.5 mt-1.5">
        <span className="tnum font-semibold leading-none text-[22px]" style={{ color: colour }}>
          {value}
        </span>
        {unit && (
          <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>{unit}</span>
        )}
        {delta && Math.abs(delta.pct) >= 0.5 && (
          <span className="tnum text-[11px] font-semibold ml-0.5 inline-flex items-center gap-[3px]"
            style={{ color: delta.better ? "var(--ok)" : "var(--crit)" }}>
            <Caret up={delta.pct > 0} />
            {Math.abs(delta.pct).toFixed(0)}%
          </span>
        )}
      </div>
      {compare && (
        <div className="text-[10.5px] tnum mt-1" style={{ color: "var(--ink-3)" }}>
          {compare}
        </div>
      )}
    </div>
  );
}

export function MetricRow({ children, cols = 4 }: {
  children: React.ReactNode; cols?: number;
}) {
  // A fixed column count rather than auto-fit: auto-fit strands the last tile on its
  // own row whenever the count does not divide evenly, which reads as a layout fault.
  return (
    <div
      className="card overflow-hidden metric-row"
      style={{ ["--cols" as string]: cols }}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export function Badge({ children, color, bg, title }: {
  children: React.ReactNode; color?: string; bg?: string; title?: string;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center rounded-[3px] px-1.5 py-[2px]
                 text-[10px] font-semibold tracking-[0.03em] whitespace-nowrap"
      style={{
        color: color ?? "var(--ink-2)",
        background: bg ?? "var(--surface-3)",
        border: `1px solid ${color ? `${color}33` : "transparent"}`,
      }}
    >
      {children}
    </span>
  );
}

export function DeptBadge({ dept, showSystem = false }: {
  dept: Dept; showSystem?: boolean;
}) {
  return (
    <Badge color={DEPT_COLOR[dept]} bg="var(--surface-2)"
      title={`${DEPT_NAME[dept]} — plans in ${DEPT_SYSTEM[dept]}`}>
      {DEPT_NAME[dept]}{showSystem && ` · ${DEPT_SYSTEM[dept]}`}
    </Badge>
  );
}

export function PriorityBadge({ band: b }: { band: Band }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <i className="lamp" style={{
        background: BAND_COLOR[b],
        boxShadow: `0 0 0 2px ${BAND_COLOR[b]}22`,
      }} />
      <span className="text-[11px] font-medium" style={{ color: BAND_COLOR[b] }}>
        {BAND_LABEL[b]}
      </span>
    </span>
  );
}

export function Lamp({ state, live = false, label }: {
  state: "ok" | "warn" | "crit" | "off"; live?: boolean; label?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <i className={`lamp lamp-${state}${live ? " lamp-live" : ""}`} />
      {label && <span className="text-[11px]" style={{ color: "var(--ink-2)" }}>{label}</span>}
    </span>
  );
}

/* ------------------------------------------------------------------ */

export function Bar({ value, max = 100, color }: {
  value: number; max?: number; color?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-[4px] rounded-full w-full" style={{ background: "var(--surface-3)" }}>
      <div className="h-full rounded-full"
        style={{ width: `${pct}%`, background: color ?? "var(--rail)" }} />
    </div>
  );
}

export function Button({
  children, onClick, variant = "default", disabled, title, type = "button",
}: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "default" | "primary" | "danger" | "quiet";
  disabled?: boolean; title?: string; type?: "button" | "submit";
}) {
  const style: React.CSSProperties = {
    primary: { background: "var(--rail)", color: "#fff", borderColor: "var(--rail)" },
    danger: { background: "var(--crit-bg)", color: "var(--crit)", borderColor: "#00000018" },
    quiet: { background: "transparent", color: "var(--ink-2)", borderColor: "transparent" },
    default: { background: "var(--surface)", color: "var(--ink)", borderColor: "var(--line-2)" },
  }[variant];

  return (
    <button
      type={type} onClick={onClick} disabled={disabled} title={title}
      className="rounded-[3px] border px-2.5 py-[5px] text-[11.5px] font-medium
                 whitespace-nowrap transition-colors
                 disabled:opacity-40 disabled:cursor-not-allowed"
      style={style}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */

/**
 * Segmented control — one choice out of a short, fixed set.
 *
 * Three pages had grown their own version of this, each with its own height, weight and
 * active colour, so the same gesture looked like a different control depending on where
 * you met it. The styling now lives in one place and the pressed state is announced
 * rather than only coloured.
 */
export function Seg<T extends string>({ options, value, onChange, label }: {
  options: readonly { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label?: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Filter chip — an independent toggle, unlike a segment. */
export function Chip({ children, active, onClick, title }: {
  children: React.ReactNode; active: boolean; onClick: () => void; title?: string;
}) {
  return (
    <button type="button" onClick={onClick} title={title} aria-pressed={active}
      className="chip inline-flex items-center gap-1.5">
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */

export function Empty({ title, children }: {
  title: string; children?: React.ReactNode;
}) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>{title}</p>
      {children && (
        <div className="text-[11.5px] mt-1.5 max-w-lg mx-auto leading-relaxed"
          style={{ color: "var(--ink-3)" }}>
          {children}
        </div>
      )}
    </div>
  );
}

export function PageHead({ title, subtitle, right }: {
  title: string; subtitle?: string; right?: React.ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap mb-4">
      <div>
        <h1 className="text-[19px] font-semibold leading-none tracking-[-0.01em]"
          style={{ color: "var(--ink)" }}>
          {title}
        </h1>
        {subtitle && (
          <p className="text-[12px] mt-1.5" style={{ color: "var(--ink-3)" }}>{subtitle}</p>
        )}
      </div>
      {right && <div className="flex items-center gap-2 shrink-0">{right}</div>}
    </div>
  );
}

/** Shown wherever a figure could be mistaken for live railway data. */
export function DemoNote({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-[3px] px-3 py-2 text-[11px] leading-relaxed"
      style={{ background: "var(--warn-bg)", color: "#6b3d00",
               border: "1px solid #e8c990" }}>
      <Badge color="var(--warn)" bg="#fff">DEMO DATA</Badge>
      <span>
        {children ?? (
          // Precise about which half is which. "Synthetic railway operations data"
          // covered everything when the timetable was written by hand; now that the
          // train paths are published data, saying it flatly understates them, and a
          // viewer would reasonably read the whole chart as invented. Every clause
          // here carries a disclosure -- the explanations behind them do not, and a
          // banner nobody finishes reading discloses nothing.
          <>Maintenance demands, assets and defect history are <b>synthetic</b>; goods
          paths are forecast. The coaching timetable is <b>published data</b>. Not
          connected to Indian Railways systems.</>
        )}
      </span>
    </div>
  );
}

/** Direction of travel against the baseline. Drawn rather than typed: ▲/▼ sit off the
 *  text baseline and their weight varies by platform font, which shows up immediately
 *  in a column of figures. */
function Caret({ up }: { up: boolean }) {
  return (
    <svg width="7" height="7" viewBox="0 0 8 8" aria-hidden="true"
      style={{ display: "block" }}>
      <path d={up ? "M4 1l3.2 5.4H0.8z" : "M4 7L0.8 1.6h6.4z"} fill="currentColor" />
    </svg>
  );
}
