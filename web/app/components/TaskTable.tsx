"use client";

import { useMemo, useState } from "react";
import { DEPT_BLOCK, Dept, Task } from "../lib/plan";
import { Band, band, BAND_COLOR } from "./PlanProvider";
import { Badge, Bar, Chip, DeptBadge, Empty, PriorityBadge } from "./ui";

/**
 * The unified queue — all three departments in one ranking.
 *
 * This is the view that does not exist today: an Engineering JE cannot see what S&T has
 * outstanding on the same section, which is precisely why three separate blocks get
 * demanded where one would do. Columns follow the operational vocabulary rather than
 * ours: chainage, department, defect, block type.
 */

const DEPTS: Dept[] = ["ENGG", "S&T", "TRD"];

const BLOCK_LABEL: Record<string, string> = {
  TRAFFIC: "Traffic block",
  DISCONN: "Disconnection",
  POWER: "Power block",
};

export default function TaskTable({
  tasks, scheduledDay, onSelect, selectedId, limit = 200, blockTypeOf,
}: {
  tasks: Task[];
  scheduledDay: Map<string, number>;
  onSelect?: (t: Task) => void;
  selectedId?: string | null;
  limit?: number;
  blockTypeOf?: Map<string, string>;
}) {
  const [dept, setDept] = useState<Dept | "ALL">("ALL");
  const [bandFilter, setBandFilter] = useState<Band | "ALL">("ALL");
  const [onlyDeferred, setOnlyDeferred] = useState(false);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return tasks
      .filter((t) => dept === "ALL" || t.dept === dept)
      .filter((t) => bandFilter === "ALL" || band(t.criticality) === bandFilter)
      .filter((t) => !onlyDeferred || !scheduledDay.has(t.id))
      .filter((t) =>
        !needle ||
        t.id.toLowerCase().includes(needle) ||
        t.type.toLowerCase().includes(needle) ||
        t.section.toLowerCase().includes(needle))
      .sort((a, b) => (b.criticality ?? 0) - (a.criticality ?? 0))
      .slice(0, limit);
  }, [tasks, dept, bandFilter, onlyDeferred, q, scheduledDay, limit]);

  return (
    <div>
      {/* ---- filters ---- */}
      <div className="flex items-center gap-1.5 flex-wrap px-3.5 py-2.5"
        style={{ borderBottom: "1px solid var(--line)", background: "var(--surface-2)" }}>
        <Chip active={dept === "ALL"} onClick={() => setDept("ALL")}>All departments</Chip>
        {DEPTS.map((d) => (
          <Chip key={d} active={dept === d} onClick={() => setDept(d)}>
            {d === "ENGG" ? "Engineering" : d === "S&T" ? "S&T" : "Traction"}
          </Chip>
        ))}

        <span className="w-px h-4 mx-1" style={{ background: "var(--line-2)" }} />

        {(["critical", "high"] as Band[]).map((b) => (
          <Chip key={b} active={bandFilter === b}
            onClick={() => setBandFilter(bandFilter === b ? "ALL" : b)}>
            <i className="lamp" style={{ background: BAND_COLOR[b] }} />
            {b === "critical" ? "Critical" : "High"}
          </Chip>
        ))}
        <Chip active={onlyDeferred} onClick={() => setOnlyDeferred((v) => !v)}>
          Deferred only
        </Chip>

        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search id, work, section…"
          aria-label="Search tasks"
          className="ml-auto rounded-[3px] border px-2.5 py-[5px] text-[11.5px] outline-none w-[190px]"
          style={{ borderColor: "var(--line-2)", background: "var(--surface)" }}
        />
        <span className="tnum text-[11px] pl-1" style={{ color: "var(--ink-3)" }}>
          {rows.length} of {tasks.length}
        </span>
      </div>

      {/* ---- table ---- */}
      <div className="overflow-x-auto">
        <table className="ops" style={{ minWidth: 960 }}>
          <thead>
            <tr>
              <th style={{ width: 84 }}>Priority</th>
              <th style={{ width: 58 }}>Ref</th>
              <th style={{ minWidth: 190 }}>Work / Defect</th>
              <th style={{ width: 88 }}>Section</th>
              <th style={{ width: 74 }}>Chainage</th>
              <th style={{ width: 92 }}>Department</th>
              <th style={{ width: 100 }}>Block type</th>
              <th style={{ width: 96 }}>Risk</th>
              <th style={{ width: 84 }}>Duration</th>
              <th style={{ width: 80 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const b = band(t.criticality);
              const day = scheduledDay.get(t.id);
              const active = selectedId === t.id;
              const overdue = t.due_day <= 0;

              return (
                <tr key={t.id}
                  onClick={() => onSelect?.(t)}
                  style={{
                    cursor: onSelect ? "pointer" : undefined,
                    background: active ? "var(--rail-bg)" : undefined,
                    borderLeft: `2px solid ${active ? "var(--rail)" : "transparent"}`,
                  }}>
                  <td><PriorityBadge band={b} /></td>
                  <td className="mono text-[11px]" style={{ color: "var(--ink-3)" }}>{t.id}</td>
                  <td>
                    <div className="text-[12px]" style={{ color: "var(--ink)" }}>{t.type}</div>
                    {overdue && (
                      <div className="text-[10.5px] tnum mt-0.5" style={{ color: "var(--crit)" }}>
                        overdue by {Math.abs(t.due_day)} d against statutory date
                      </div>
                    )}
                  </td>
                  <td className="tnum text-[11.5px]">{t.section}</td>
                  <td className="tnum text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                    km {t.km.toFixed(1)} <span style={{ color: "var(--ink-3)" }}>{t.line}</span>
                  </td>
                  <td><DeptBadge dept={t.dept} /></td>
                  <td className="text-[11px]" style={{ color: "var(--ink-2)" }}>
                    {BLOCK_LABEL[blockTypeOf?.get(t.id) ?? ""] ?? DEPT_BLOCK[t.dept]}
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="tnum text-[12px] font-semibold w-[26px]"
                        style={{ color: BAND_COLOR[b] }}>
                        {(t.criticality ?? 0).toFixed(0)}
                      </span>
                      <Bar value={t.criticality ?? 0} color={BAND_COLOR[b]} />
                    </div>
                  </td>
                  <td className="tnum text-[11px]">
                    <span style={{ color: "var(--ink-2)" }}>P50 {t.p50}m</span>
                    <span className="block" style={{
                      color: (t.p90 ?? 0) > t.demanded ? "var(--warn)" : "var(--ink-3)",
                    }}>
                      P90 {t.p90}m
                    </span>
                  </td>
                  <td>
                    {day === undefined
                      ? <Badge color="var(--ink-3)">Deferred</Badge>
                      : <Badge color="var(--ok)" bg="var(--ok-bg)">Day {day + 1}</Badge>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <Empty title="Nothing matches that filter">
            Clear a filter or widen the search to see the rest of the queue.
          </Empty>
        )}
      </div>
    </div>
  );
}

