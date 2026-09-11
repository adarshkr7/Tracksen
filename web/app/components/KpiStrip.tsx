"use client";

import { Metrics, fmt } from "../lib/plan";

interface Row {
  label: string;
  get: (m: Metrics) => number;
  format: (v: number) => string;
  higherBetter: boolean;
  hint?: string;
}

const ROWS: Row[] = [
  {
    label: "Risk retired / block-hour",
    get: (m) => m.risk_retired_per_block_hour,
    format: (v) => fmt(v, 1),
    higherBetter: true,
    hint: "Criticality completed per hour of line withdrawn — the headline measure",
  },
  {
    label: "Blocks used",
    get: (m) => m.blocks_used,
    format: (v) => fmt(v),
    higherBetter: false,
    hint: "Separate line closures needed to do the work",
  },
  {
    label: "Depts per block",
    get: (m) => m.clubbing_ratio,
    format: (v) => v.toFixed(2),
    higherBetter: true,
    hint: "Above 1.00 means departments are genuinely sharing closures",
  },
  {
    label: "Traffic cost",
    get: (m) => m.traffic_cost,
    format: (v) => fmt(v),
    higherBetter: false,
    hint: "Expected weighted detention minutes across the horizon",
  },
  {
    label: "Corridor adherence",
    get: (m) => m.corridor_adherence,
    format: (v) => `${Math.round(v * 100)}%`,
    higherBetter: true,
    hint: "Share of blocks inside the mandated corridor in the master chart",
  },
  {
    label: "Critical failures",
    get: (m) => m.critical_unplanned_failures,
    format: (v) => fmt(v),
    higherBetter: false,
    hint: "High-criticality assets that fail before attention",
  },
];

export default function KpiStrip({
  baseline, optimised,
}: { baseline: Metrics; optimised: Metrics }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-px rounded-xl overflow-hidden border"
      style={{ borderColor: "var(--line)", background: "var(--line)" }}>
      {ROWS.map((r) => {
        const b = r.get(baseline);
        const o = r.get(optimised);
        const pct = b === 0 ? (o > 0 ? 100 : 0) : ((o - b) / Math.abs(b)) * 100;
        const better = (pct > 0) === r.higherBetter;
        const flat = Math.abs(pct) < 0.5;

        return (
          <div
            key={r.label}
            className="p-3.5"
            style={{ background: "var(--surface)" }}
            title={r.hint}
          >
            <div className="text-[10.5px] uppercase tracking-wide mb-1.5"
              style={{ color: "var(--ink-3)", letterSpacing: "0.05em" }}>
              {r.label}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-[21px] leading-none tnum font-medium"
                style={{ color: "var(--ink)" }}>
                {r.format(o)}
              </span>
              {!flat && (
                <span
                  className="text-[11px] tnum font-medium"
                  style={{ color: better ? "var(--accent)" : "var(--ink-3)" }}
                >
                  {pct > 0 ? "+" : ""}{pct.toFixed(0)}%
                </span>
              )}
            </div>
            <div className="text-[11px] tnum mt-1" style={{ color: "var(--ink-3)" }}>
              baseline {r.format(b)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
