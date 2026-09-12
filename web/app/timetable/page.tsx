"use client";

import { useState } from "react";
import BlockDetail from "../components/BlockDetail";
import ExpandableCard from "../components/Expandable";
import Gate from "../components/Gate";
import MonthView from "../components/MonthView";
import TimeDistanceChart from "../components/TimeDistanceChart";
import { usePlan } from "../components/PlanProvider";
import { Card, Chip, DemoNote, Empty, Metric, MetricRow, PageHead, Seg } from "../components/ui";
import { Block, LIVERY_COLOR, LIVERY_LABEL, LineName, dayLabel } from "../lib/plan";

/**
 * The control chart.
 *
 * Time across, chainage down — the artefact railway operating staff already read daily.
 * Train paths are the diagonals, blocks are rectangles, and the mandated corridor is the
 * shaded band. The month view answers the other question: which section-day corridor
 * goes to whom, four weeks out.
 */

export default function TimetablePage() {
  return <Gate><TimetableBody /></Gate>;
}

function TimetableBody() {
  const { plan, taskById } = usePlan();
  const [horizon, setHorizon] = useState<"week" | "month">("week");
  const [day, setDay] = useState(0);
  const [line, setLine] = useState<LineName | "BOTH">("BOTH");
  const [selected, setSelected] = useState<Block | null>(null);

  if (!plan) return null;
  const m = plan.monthly;
  const dayBlocks = plan.blocks.filter(
    (b) => b.day === day && (line === "BOTH" || b.line === line),
  );

  return (
    <>
      <PageHead
        title="Timetable & Block Chart"
        subtitle="Train paths, maintenance windows and the mandated corridor on one chart"
        right={
          <Seg
            label="Planning horizon"
            options={[
              { id: "week", label: "Weekly · 15 min" },
              { id: "month", label: "Monthly · corridor slot" },
            ] as const}
            value={horizon}
            onChange={setHorizon}
          />
        }
      />
      <div className="mb-4"><DemoNote /></div>

      {horizon === "week" ? (
        <>
        <ExpandableCard
          title={`Time–Distance Chart — ${dayLabel(day)}`}
          subtitle="Chainage down the main line, time across; the shaded band is the mandated corridor"
          pad={false}
        >
          <div className="flex items-center gap-1 px-3.5 pt-3 flex-wrap">
            {Array.from({ length: plan.meta.horizon_days }, (_, d) => (
              <Chip key={d} active={d === day} onClick={() => setDay(d)}>
                <span className="tnum">{dayLabel(d)}</span>
              </Chip>
            ))}
            <span className="w-px h-4 mx-1.5" style={{ background: "var(--line-2)" }} />
            {(["BOTH", "DN", "UP"] as const).map((l) => (
              <Chip key={l} active={line === l} onClick={() => setLine(l)}>
                {l === "BOTH" ? "Both lines" : `${l} line`}
              </Chip>
            ))}
            <span className="ml-auto tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
              {dayBlocks.length} blocks
            </span>
          </div>

          <div className="px-3 pt-2 pb-1">
            <TimeDistanceChart
              sections={plan.sections} stations={plan.stations} paths={plan.paths}
              trains={plan.trains}
              onSelect={setSelected} selectedId={selected?.id ?? null}
              corridors={plan.corridors} blocks={plan.blocks} day={day} line={line}
            />
          </div>

          <div className="flex items-center gap-x-5 gap-y-2 flex-wrap px-4 pb-3.5 pt-1 text-[10.5px]"
            style={{ color: "var(--ink-3)" }}>
            {LIVERY_LABEL.map((label, i) => (
              <span key={label} className="inline-flex items-center gap-1.5">
                <i style={{
                  width: 16, height: 2.5, background: LIVERY_COLOR[i], display: "inline-block",
                }} />
                {label}
              </span>
            ))}
            <span className="inline-flex items-center gap-1.5">
              <i style={{
                width: 16, height: 9, background: "var(--rail)", opacity: 0.12,
                display: "inline-block",
              }} />
              mandated corridor
            </span>
            <span className="ml-auto">
              hover a path for the train; branch services show their main-line running only
            </span>
          </div>
        </ExpandableCard>
        {selected && (
          <div className="mt-4">
            <BlockDetail block={selected} data={plan} taskById={taskById}
              onClose={() => setSelected(null)} />
          </div>
        )}
        </>
      ) : m ? (
        <>
          <div className="mb-4">
            <MetricRow cols={4}>
              <Metric label="Corridor Slots Used" value={String(m.slotsUsed)}
                compare={`of ${m.slotsTotal} available · ${m.corridorMinutes} min each`} />
              <Metric label="Jobs Placed" value={String(m.metrics.tasks_scheduled)}
                tone="ok" compare={`${m.metrics.tasks_unscheduled} still deferred at day ${m.days}`} />
              <Metric label="Backlog Burn-down"
                value={`${m.backlogByDay[0]} → ${m.backlogByDay[m.backlogByDay.length - 1]}`}
                compare={`over ${m.days} days`} />
              <Metric label="Need an Extended Block" value={String(m.extendedTasks.length)}
                tone="warn"
                compare={`work longer than the ${m.corridorMinutes}-min corridor`}
                hint="These go up as separate extended or mega blocks negotiated with operations" />
            </MetricRow>
          </div>
          <Card title="Monthly Corridor Allocation"
            subtitle="One cell per section-day; upper strip UP, lower strip DN">
            <MonthView monthly={m} sections={plan.sections} taskById={taskById} />
          </Card>
        </>
      ) : (
        <Card>
          <Empty title="No monthly plan in this file">
            Regenerate with the monthly horizon enabled:
            <pre className="mono text-[11px] rounded-[3px] p-3 mt-2 text-left inline-block"
              style={{ background: "var(--surface-2)" }}>
{`python scripts/run_pipeline.py --days 7 --tasks 200 --monthly
cd web && npm run sync`}
            </pre>
          </Empty>
        </Card>
      )}
    </>
  );
}
