"use client";

/**
 * What is actually inside a block, on click.
 *
 * The time–distance chart set `cursor: pointer` on every block and wired the click to
 * nothing on two of the three screens that draw it — so it advertised an interaction it
 * did not have, which is worse than being plainly inert. This is the panel that click
 * opens: the possession, the work in it, what it cost and why the solver put it there.
 *
 * Read-only by design. Moving a block is the What-If screen's job, and mixing "look at
 * this" with "change this" on the planning view would invite someone to edit a plan they
 * are only meant to be reading.
 */

import { Block, DEPT_BLOCK, DEPT_FULL, PlanData, Task, dayLabel, hhmm } from "../lib/plan";
import { BAND_COLOR, BAND_LABEL, band } from "./PlanProvider";
import { DeptBadge } from "./ui";

export default function BlockDetail({
  block, data, taskById, onClose,
}: {
  block: Block;
  data: PlanData;
  taskById: Map<string, Task>;
  onClose: () => void;
}) {
  const sec = data.sections[block.sec];
  const minutes = block.e - block.s;
  const tasks = block.tasks
    .map((id) => taskById.get(id))
    .filter((t): t is Task => Boolean(t))
    .sort((a, b) => (b.criticality ?? 0) - (a.criticality ?? 0));

  // The longest job is what the possession was actually sized against; the rest run in
  // parallel beside it. Saying so stops the spare minutes reading as waste.
  const longest = Math.max(0, ...tasks.map((t) => t.p90 ?? t.demanded));

  return (
    <div className="card" style={{ borderColor: "var(--rail)" }}>
      <div className="flex items-start justify-between gap-4 px-4 pt-3.5 pb-2.5">
        <div>
          <div className="sig mb-1">Block {block.id}</div>
          <div className="text-[15px] font-medium" style={{ color: "var(--ink)" }}>
            {sec ? `${sec.a}–${sec.b}` : "—"}{" "}
            <span style={{ color: "var(--ink-3)" }}>· {block.line} line</span>
          </div>
          <div className="tnum text-[12px] mt-1" style={{ color: "var(--ink-2)" }}>
            {dayLabel(block.day)} {hhmm(block.s)}–{hhmm(block.e)} · {minutes} min
            {block.corridor
              ? " · inside the mandated corridor"
              : " · outside the corridor"}
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close block details"
          className="rounded-[3px] border px-2 py-[3px] text-[11px] shrink-0"
          style={{ borderColor: "var(--line-2)", color: "var(--ink-3)" }}
        >
          Close
        </button>
      </div>

      {/* ---- what it cost and what it bought ---- */}
      <div className="grid gap-px px-0" style={{ background: "var(--line)" }}>
        <div className="grid gap-px"
          style={{ background: "var(--line)",
                   gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
          <Cell label="Criticality retired" value={block.crit.toFixed(0)} tone="var(--ok)" />
          <Cell label="Traffic cost" value={`${Math.round(block.traffic)} wtd min`}
            tone={block.traffic > 400 ? "var(--warn)" : "var(--ink)"} />
          <Cell label="Departments" value={String(block.depts.length)}
            tone={block.depts.length > 1 ? "var(--club)" : "var(--ink)"} />
          <Cell label="Longest job (P90)" value={`${longest} min`} />
        </div>
      </div>

      {/* ---- who is in it ---- */}
      <div className="px-4 py-3" style={{ borderTop: "1px solid var(--line)" }}>
        <div className="flex flex-wrap items-center gap-1.5">
          {block.depts.map((d) => <DeptBadge key={d} dept={d} showSystem />)}
          {block.types.map((t) => (
            <span key={t} className="rounded-[3px] border px-1.5 py-px text-[10.5px]"
              style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}>
              {t}
            </span>
          ))}
        </div>
        {block.depts.length > 1 && (
          <div className="text-[11.5px] mt-2" style={{ color: "var(--ink-2)" }}>
            Clubbed: {block.depts.map((d) => DEPT_BLOCK[d]).join(" + ")} taken under one
            closure instead of {block.depts.length} separate ones.
          </div>
        )}
      </div>

      {/* ---- the work ---- */}
      <div style={{ borderTop: "1px solid var(--line)" }}>
        <div className="sig px-4 pt-3 pb-1.5">
          Work in this possession ({tasks.length})
        </div>
        <div className="overflow-x-auto">
          <table className="ops w-full">
            <thead>
              <tr>
                <th>Task</th><th>Department</th><th>Work</th>
                <th className="text-right">Chainage</th>
                <th className="text-right">P50 / P90</th>
                <th className="text-right">Criticality</th>
                <th className="text-right">Due</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const b = band(t.criticality);
                return (
                  <tr key={t.id}>
                    <td className="mono">{t.id}</td>
                    <td>{DEPT_FULL[t.dept]}</td>
                    <td>{t.type}</td>
                    <td className="tnum text-right">{t.km.toFixed(1)} km</td>
                    <td className="tnum text-right">
                      {t.p50 ?? "—"} / {t.p90 ?? "—"} min
                    </td>
                    <td className="tnum text-right" style={{ color: BAND_COLOR[b] }}>
                      {t.criticality?.toFixed(0) ?? "—"} · {BAND_LABEL[b]}
                    </td>
                    <td className="tnum text-right"
                      style={{ color: t.due_day <= 0 ? "var(--crit)" : "var(--ink-2)" }}>
                      {t.due_day <= 0 ? `${-t.due_day}d overdue` : `in ${t.due_day}d`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- why the solver chose this ---- */}
      {block.why.length > 0 && (
        <div className="px-4 py-3" style={{ borderTop: "1px solid var(--line)" }}>
          <div className="sig mb-1.5">Why here</div>
          {block.why.map((r, i) => (
            <div key={i} className="text-[11.5px] flex gap-2 py-[2px]"
              style={{ color: "var(--ink-2)" }}>
              <span style={{ color: "var(--rail)" }}>•</span>{r}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Cell({ label, value, tone = "var(--ink)" }: {
  label: string; value: string; tone?: string;
}) {
  return (
    <div className="px-4 py-2.5" style={{ background: "var(--surface)" }}>
      <div className="sig">{label}</div>
      <div className="text-[14px] font-medium tnum mt-[3px]" style={{ color: tone }}>
        {value}
      </div>
    </div>
  );
}
