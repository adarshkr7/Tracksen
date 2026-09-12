"use client";

import { useMemo, useState } from "react";
import Gate from "../components/Gate";
import TaskIntelligence from "../components/TaskIntelligence";
import TaskTable from "../components/TaskTable";
import { usePlan } from "../components/PlanProvider";
import { Card, DemoNote, Metric, MetricRow, PageHead } from "../components/ui";
import { Task } from "../lib/plan";

/** The unified queue — the view that does not exist across the three systems today. */
export default function MaintenancePage() {
  return <Gate><MaintenanceBody /></Gate>;
}

function MaintenanceBody() {
  const { plan, counts, scheduledDay } = usePlan();
  const [selected, setSelected] = useState<Task | null>(null);

  // The plan records a block type per block; map it back to the tasks inside it.
  const blockTypeOf = useMemo(() => {
    const m = new Map<string, string>();
    if (plan) for (const b of plan.blocks) for (const t of b.tasks) m.set(t, b.types[0] ?? "");
    return m;
  }, [plan]);

  if (!plan) return null;
  const dur = plan.model_checks?.duration ?? {};

  return (
    <>
      <PageHead
        title="Maintenance Queue"
        subtitle="Defects and overdue work from TMS, SMMS and TDMS, ranked together"
      />
      <div className="mb-4"><DemoNote /></div>

      <div className="mb-4">
        <MetricRow cols={5}>
          <Metric label="Pending Jobs" value={String(counts.tasks)} />
          <Metric label="Critical" value={String(counts.critical)} tone="crit"
            hint="Criticality index 70 or above" />
          <Metric label="Overdue" value={String(counts.overdue)} tone="warn"
            compare="past statutory due date" />
          <Metric label="Scheduled" value={String(counts.scheduled)} tone="ok"
            compare={`${counts.deferred} deferred beyond horizon`} />
          <Metric
            label="Demanded Duration Holds"
            value={dur.demanded_coverage !== undefined
              ? `${Math.round(dur.demanded_coverage * 100)}%` : "—"}
            tone="crit"
            compare={dur.p90_coverage !== undefined
              ? `P90 reservation holds ${Math.round(dur.p90_coverage * 100)}%` : ""}
            hint="Share of jobs whose true duration fits the figure the department demanded"
          />
        </MetricRow>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0,1fr) 340px", alignItems: "start" }}>
        <Card pad={false}>
          <TaskTable
            tasks={plan.tasks} scheduledDay={scheduledDay}
            onSelect={setSelected} selectedId={selected?.id ?? null}
            blockTypeOf={blockTypeOf}
          />
        </Card>
        <div><TaskIntelligence task={selected} /></div>
      </div>
    </>
  );
}
