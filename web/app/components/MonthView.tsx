"use client";

import { useMemo, useState } from "react";
import { Block, DEPT_COLOR, Dept, MonthlyPlan, Section, Task, fmt } from "../lib/plan";

/**
 * The long horizon: which corridor slot goes to whom, section by section, day by day.
 *
 * A monthly plan answers a different question from a weekly one. Nobody commits a
 * tamping machine to 11:15 on the 24th four weeks out — they commit it to *a corridor
 * on the 24th*. So this view drops the time axis entirely and shows allocation: one
 * cell per section-day, split into UP and DN, coloured by the department holding it.
 */

interface Props {
  monthly: MonthlyPlan;
  sections: Section[];
  taskById: Map<string, Task>;
}

export default function MonthView({ monthly, sections, taskById }: Props) {
  const [hover, setHover] = useState<{ block: Block; x: number; y: number } | null>(null);

  // (section, day, line) -> block
  const grid = useMemo(() => {
    const m = new Map<string, Block>();
    for (const b of monthly.blocks) m.set(`${b.sec}:${b.day}:${b.line}`, b);
    return m;
  }, [monthly.blocks]);

  const days = monthly.days;
  const burn = monthly.backlogByDay;
  const mm = monthly.metrics;

  return (
    <div>
      {/* ---- summary ---- */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px rounded-xl overflow-hidden
                      border mb-4"
        style={{ borderColor: "var(--line)", background: "var(--line)" }}>
        <Tile label="Corridor slots used"
          value={`${monthly.slotsUsed}`}
          sub={`of ${monthly.slotsTotal} available · ${monthly.corridorMinutes} min each`} />
        <Tile label="Tasks placed"
          value={`${mm.tasks_scheduled}`}
          sub={`${mm.tasks_unscheduled} still deferred at day ${days}`} />
        <Tile label="Backlog burn-down"
          value={`${burn[0]} → ${burn[burn.length - 1]}`}
          sub={`over ${days} days`} />
        <Tile label="Need an extended block"
          value={`${monthly.extendedTasks.length}`}
          sub={`work longer than the ${monthly.corridorMinutes}-min corridor`}
          accent />
      </div>

      {/* ---- allocation grid ---- */}
      <div className="rounded-xl border overflow-x-auto"
        style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        <div className="min-w-[760px] p-3">
          {/* day header */}
          <div className="flex items-end mb-1.5" style={{ paddingLeft: 62 }}>
            {Array.from({ length: days }, (_, d) => (
              <div key={d} className="flex-1 text-center text-[9px] tnum"
                style={{ color: "var(--ink-3)" }}>
                {d % 5 === 0 || d === days - 1 ? d + 1 : ""}
              </div>
            ))}
          </div>

          {sections.map((sec, si) => (
            <div key={sec.id} className="flex items-center mb-[3px]">
              <div className="text-[10px] tnum shrink-0 text-right pr-2"
                style={{ width: 62, color: "var(--ink-3)" }}>
                {sec.id}
              </div>
              {Array.from({ length: days }, (_, d) => {
                const up = grid.get(`${si}:${d}:UP`);
                const dn = grid.get(`${si}:${d}:DN`);
                return (
                  <div key={d} className="flex-1 px-[1px]">
                    <Cell b={up} onHover={setHover} />
                    <div style={{ height: 2 }} />
                    <Cell b={dn} onHover={setHover} />
                  </div>
                );
              })}
            </div>
          ))}

          {/* backlog burn-down */}
          <div className="flex items-center mt-3 pt-3 border-t"
            style={{ borderColor: "var(--line)" }}>
            <div className="text-[10px] shrink-0 text-right pr-2"
              style={{ width: 62, color: "var(--ink-3)" }}>
              backlog
            </div>
            <svg viewBox={`0 0 ${days} 30`} preserveAspectRatio="none"
              className="flex-1" style={{ height: 34 }}>
              <polyline
                points={(() => {
                  const lo = Math.min(...burn);
                  const hi = Math.max(...burn);
                  const span = Math.max(1, hi - lo);
                  return burn
                    .map((v, i) => `${i},${28 - ((v - lo) / span) * 26 + 1}`)
                    .join(" ");
                })()}
                fill="none" stroke="var(--accent)" strokeWidth={0.6}
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <div className="text-[10px] tnum pl-2 shrink-0"
              style={{ color: "var(--ink-3)" }}>
              {burn[burn.length - 1]} left
            </div>
          </div>
        </div>
      </div>

      {/* ---- legend + tooltip ---- */}
      <div className="flex items-center gap-x-5 gap-y-2 flex-wrap mt-3 text-[11px]"
        style={{ color: "var(--ink-3)" }}>
        {(["ENGG", "S&T", "TRD"] as Dept[]).map((d) => (
          <span key={d} className="inline-flex items-center gap-1.5">
            <i className="w-2.5 h-2.5 rounded-[2px] inline-block"
              style={{ background: DEPT_COLOR[d], opacity: 0.75 }} />
            {d}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <i className="w-2.5 h-2.5 rounded-[2px] inline-block"
            style={{ background: "var(--club)", opacity: 0.7 }} />
          clubbed
        </span>
        <span className="ml-auto">
          each cell is one section-day: upper strip UP, lower strip DN
        </span>
      </div>

      {hover && (
        <div className="fixed z-30 pointer-events-none rounded-lg border px-3 py-2
                        shadow-sm text-[11.5px] fade-in"
          style={{
            left: Math.min(hover.x + 12, (typeof window !== "undefined" ? window.innerWidth : 900) - 300),
            top: hover.y + 12,
            maxWidth: 280,
            background: "var(--surface)", borderColor: "var(--line-2)",
            color: "var(--ink-2)",
          }}>
          <div className="font-medium mb-1" style={{ color: "var(--ink)" }}>
            {sections[hover.block.sec]?.id} · {hover.block.line} · day {hover.block.day + 1}
          </div>
          {hover.block.tasks.map((tid) => {
            const t = taskById.get(tid);
            return (
              <div key={tid} className="text-[11px] truncate">
                {t ? `${t.dept} · ${t.type}` : tid}
              </div>
            );
          })}
          <div className="text-[11px] mt-1 tnum" style={{ color: "var(--ink-3)" }}>
            criticality {fmt(hover.block.crit, 0)} · corridor slot
          </div>
        </div>
      )}
    </div>
  );
}

function Cell({
  b, onHover,
}: {
  b: Block | undefined;
  onHover: (v: { block: Block; x: number; y: number } | null) => void;
}) {
  if (!b) {
    return <div style={{ height: 9, background: "var(--surface-2)", borderRadius: 1 }} />;
  }
  const clubbed = b.depts.length > 1;
  const color = clubbed ? "var(--club)" : DEPT_COLOR[b.depts[0]];
  return (
    <div
      onMouseEnter={(e) => onHover({ block: b, x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
      style={{
        height: 9,
        background: color,
        opacity: clubbed ? 0.95 : 0.75,
        borderRadius: 1,
        cursor: "pointer",
      }}
    />
  );
}

function Tile({
  label, value, sub, accent,
}: { label: string; value: string; sub: string; accent?: boolean }) {
  return (
    <div className="p-3.5" style={{ background: "var(--surface)" }}>
      <div className="text-[10.5px] uppercase tracking-wide mb-1.5"
        style={{ color: "var(--ink-3)", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div className="text-[21px] leading-none tnum font-medium"
        style={{ color: accent ? "var(--accent)" : "var(--ink)" }}>
        {value}
      </div>
      <div className="text-[11px] mt-1" style={{ color: "var(--ink-3)" }}>{sub}</div>
    </div>
  );
}
