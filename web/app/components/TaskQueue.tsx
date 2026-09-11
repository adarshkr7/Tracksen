"use client";

import { useMemo, useState } from "react";
import { Block, DEPT_COLOR, DEPT_SYSTEM, Dept, Task } from "../lib/plan";

/**
 * One ranked queue across all three departments — which is the thing that does not
 * exist today. Each row carries its own attribution, because a planner being asked
 * to defer one department's work needs to see why.
 */

const DEPTS: Dept[] = ["ENGG", "S&T", "TRD"];

export default function TaskQueue({
  tasks, blocks,
}: { tasks: Task[]; blocks: Block[] }) {
  const [filter, setFilter] = useState<Dept | "ALL">("ALL");
  const [onlyUnscheduled, setOnlyUnscheduled] = useState(false);

  const scheduledDay = useMemo(() => {
    const m = new Map<string, number>();
    for (const b of blocks) for (const t of b.tasks) m.set(t, b.day);
    return m;
  }, [blocks]);

  const rows = useMemo(() => {
    return tasks
      .filter((t) => filter === "ALL" || t.dept === filter)
      .filter((t) => !onlyUnscheduled || !scheduledDay.has(t.id))
      .sort((a, b) => (b.criticality ?? 0) - (a.criticality ?? 0))
      .slice(0, 60);
  }, [tasks, filter, onlyUnscheduled, scheduledDay]);

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-3 flex-wrap">
        {(["ALL", ...DEPTS] as const).map((d) => (
          <button
            key={d}
            onClick={() => setFilter(d)}
            className="rounded-md px-2.5 py-1 text-[11.5px] border transition-colors"
            style={{
              borderColor: filter === d ? "var(--ink-3)" : "var(--line)",
              background: filter === d ? "var(--surface-2)" : "transparent",
              color: filter === d ? "var(--ink)" : "var(--ink-2)",
            }}
          >
            {d === "ALL" ? "All departments" : `${d} · ${DEPT_SYSTEM[d as Dept]}`}
          </button>
        ))}
        <button
          onClick={() => setOnlyUnscheduled((v) => !v)}
          className="rounded-md px-2.5 py-1 text-[11.5px] border transition-colors ml-auto"
          style={{
            borderColor: onlyUnscheduled ? "var(--accent)" : "var(--line)",
            background: onlyUnscheduled ? "var(--accent-bg)" : "transparent",
            color: onlyUnscheduled ? "var(--accent)" : "var(--ink-2)",
          }}
        >
          Deferred only
        </button>
      </div>

      <div className="rounded-xl border overflow-hidden"
        style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        {rows.map((t, i) => {
          const day = scheduledDay.get(t.id);
          const crit = t.criticality ?? 0;
          const reasons = Object.entries(t.attribution)
            .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
            .slice(0, 2);

          return (
            <div
              key={t.id}
              className="flex items-center gap-3 px-3.5 py-2.5 text-[12px]"
              style={{
                borderTop: i === 0 ? "none" : "1px solid var(--line)",
              }}
            >
              {/* criticality */}
              <div className="w-11 shrink-0">
                <div className="tnum text-[13px] font-medium leading-none"
                  style={{ color: "var(--ink)" }}>
                  {crit.toFixed(0)}
                </div>
                <div className="h-[3px] rounded-full mt-1.5"
                  style={{ background: "var(--line)" }}>
                  <div className="h-full rounded-full"
                    style={{ width: `${crit}%`, background: "var(--accent)" }} />
                </div>
              </div>

              <span className="rounded px-1.5 py-px text-[10px] font-medium shrink-0 w-11 text-center"
                style={{ background: DEPT_COLOR[t.dept], color: "#fff" }}>
                {t.dept}
              </span>

              <div className="min-w-0 flex-1">
                <div className="truncate" style={{ color: "var(--ink)" }}>
                  {t.type}
                </div>
                <div className="truncate text-[11px] tnum mt-0.5"
                  style={{ color: "var(--ink-3)" }}>
                  {t.section} · km {t.km.toFixed(1)} · {t.line}
                  {reasons.length > 0 && (
                    <> · {reasons.map(([k, v]) =>
                      `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)} ${k}`).join(", ")}</>
                  )}
                </div>
              </div>

              {/* duration: what was demanded vs what we reserve */}
              <div className="hidden md:block text-right shrink-0 tnum text-[11px]"
                style={{ color: "var(--ink-3)" }}>
                <div>demanded {t.demanded}m</div>
                <div style={{ color: (t.p90 ?? 0) > t.demanded ? "var(--accent)" : "var(--ink-3)" }}>
                  P90 {t.p90}m
                </div>
              </div>

              <div className="w-16 text-right shrink-0 text-[11px] tnum">
                {day === undefined ? (
                  <span style={{ color: "var(--ink-3)" }}>deferred</span>
                ) : (
                  <span style={{ color: "var(--ink-2)" }}>day {day + 1}</span>
                )}
              </div>
            </div>
          );
        })}
        {rows.length === 0 && (
          <div className="px-3.5 py-8 text-center text-[12px]"
            style={{ color: "var(--ink-3)" }}>
            Nothing matches that filter.
          </div>
        )}
      </div>
    </div>
  );
}
