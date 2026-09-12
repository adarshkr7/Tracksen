"use client";

import { useMemo, useState } from "react";
import ExpandableCard from "../components/Expandable";
import Gate from "../components/Gate";
import NetworkDiagram from "../components/NetworkDiagram";
import TaskIntelligence from "../components/TaskIntelligence";
import { band, usePlan } from "../components/PlanProvider";
import { Badge, Card, DemoNote, PageHead } from "../components/ui";
import { DEPT_COLOR, DEPT_NAME, Dept, Task } from "../lib/plan";

/** Corridor view: the section diagram, plus a register of what sits on each section. */
export default function NetworkPage() {
  return <Gate><NetworkBody /></Gate>;
}

function NetworkBody() {
  const { plan, scheduledDay } = usePlan();
  const [selected, setSelected] = useState<Task | null>(null);

  const perSection = useMemo(() => {
    if (!plan) return [];
    return plan.sections.map((sec, idx) => {
      const tasks = plan.tasks.filter((t) => t.section === sec.id);
      const blocks = plan.blocks.filter((b) => b.sec === idx);
      const corridor = plan.corridors.filter((c) => c[0] === idx);
      return {
        sec, tasks, blocks,
        critical: tasks.filter((t) => band(t.criticality) === "critical").length,
        scheduled: tasks.filter((t) => scheduledDay.has(t.id)).length,
        clubbed: blocks.filter((b) => b.depts.length > 1).length,
        corridorMin: corridor.length ? corridor[0][3] - corridor[0][2] : 0,
      };
    });
  }, [plan, scheduledDay]);

  if (!plan) return null;

  return (
    <>
      <PageHead
        title="Railway Network"
        subtitle="Danapur division, East Central Railway · Buxar (BXR) – Patna – Jhajha (JAJ) main line and eight modelled branches"
      />
      <div className="mb-4"><DemoNote /></div>

      <div className="mb-4">
        <ExpandableCard
          title="Divisional Schematic"
          subtitle="Filled markers are in the plan; hollow markers are deferred beyond this horizon"
          expandedSubtitle="Main line and eight modelled branches. Filled markers are in the plan; hollow markers are deferred."
        >
          <NetworkDiagram
            stations={plan.stations} sections={plan.sections} tasks={plan.tasks}
            scheduledDay={scheduledDay} branches={plan.branches} routes={plan.routes}
            onSelect={setSelected} selectedId={selected?.id ?? null}
          />
        </ExpandableCard>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0,1fr) 400px", alignItems: "start" }}>
        <Card title="Section Register" pad={false}>
          <div className="overflow-x-auto">
            <table className="ops" style={{ minWidth: 760 }}>
              <thead>
                <tr>
                  <th>Block Section</th><th>Chainage</th><th>Length</th>
                  <th>Pending</th><th>Critical</th><th>Scheduled</th>
                  <th>Blocks</th><th>Clubbed</th><th>Corridor</th>
                </tr>
              </thead>
              <tbody>
                {perSection.map(({ sec, tasks, blocks, critical, scheduled, clubbed, corridorMin }) => (
                  <tr key={sec.id}>
                    <td>
                      <span className="font-medium">{sec.a}–{sec.b}</span>
                      <span className="block tnum text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                        {sec.id}
                      </span>
                    </td>
                    <td className="tnum text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {sec.km0.toFixed(0)} – {sec.km1.toFixed(0)} km
                    </td>
                    <td className="tnum text-[11.5px]">{(sec.km1 - sec.km0).toFixed(0)} km</td>
                    <td className="tnum">{tasks.length}</td>
                    <td className="tnum" style={{ color: critical ? "var(--crit)" : "var(--ink-3)" }}>
                      {critical}
                    </td>
                    <td className="tnum" style={{ color: "var(--ok)" }}>{scheduled}</td>
                    <td className="tnum">{blocks.length}</td>
                    <td>
                      {clubbed
                        ? <Badge color="var(--rail)" bg="var(--rail-bg)">{clubbed}</Badge>
                        : <span style={{ color: "var(--ink-3)" }}>—</span>}
                    </td>
                    <td className="tnum text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {corridorMin ? `${corridorMin / 60} h / day` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-4">
          <TaskIntelligence task={selected} />

          <Card title="Departmental Split by Section" pad={false}>
            <div className="p-3.5 space-y-2.5">
              {perSection.map(({ sec, tasks }) => {
                const counts = (["ENGG", "S&T", "TRD"] as Dept[])
                  .map((d) => ({ d, n: tasks.filter((t) => t.dept === d).length }));
                const total = tasks.length || 1;
                return (
                  <div key={sec.id}>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="tnum" style={{ color: "var(--ink-2)" }}>{sec.id}</span>
                      <span className="tnum" style={{ color: "var(--ink-3)" }}>{tasks.length}</span>
                    </div>
                    <div className="flex h-[6px] rounded-sm overflow-hidden"
                      style={{ background: "var(--surface-3)" }}>
                      {counts.map(({ d, n }) => (
                        <div key={d} title={`${DEPT_NAME[d]}: ${n}`}
                          style={{ width: `${(n / total) * 100}%`, background: DEPT_COLOR[d] }} />
                      ))}
                    </div>
                  </div>
                );
              })}
              <div className="flex gap-3 pt-1.5 text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                {(["ENGG", "S&T", "TRD"] as Dept[]).map((d) => (
                  <span key={d} className="inline-flex items-center gap-1.5">
                    <i style={{
                      width: 8, height: 8, background: DEPT_COLOR[d], display: "inline-block",
                    }} />
                    {DEPT_NAME[d]}
                  </span>
                ))}
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
