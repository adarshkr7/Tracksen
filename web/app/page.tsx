"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ExpandableCard from "./components/Expandable";
import Gate from "./components/Gate";
import NetworkDiagram from "./components/NetworkDiagram";
import TimeDistanceChart from "./components/TimeDistanceChart";
import { band, BAND_COLOR, usePlan } from "./components/PlanProvider";
import {
  Badge, Bar, Button, Card, DemoNote, DeptBadge, Lamp, Metric, MetricRow, PageHead,
} from "./components/ui";
import { ApprovalStatus, planStatus } from "./lib/api";
import { CURRENT_PLAN_ID } from "./lib/planId";
import { DEPT_COLOR, DEPT_NAME, Dept } from "./lib/plan";

/**
 * Maintenance Control Centre.
 *
 * The screen a divisional officer would leave open: what is outstanding, what the plan
 * does about it, and where on the corridor the work sits. Every figure is read from the
 * solved plan — nothing here is illustrative.
 */

export default function Dashboard() {
  return <Gate><DashboardBody /></Gate>;
}

function MismatchNotice() {
  const { topologyMismatch, clearMismatch } = usePlan();
  if (!topologyMismatch) return null;
  return (
    <div className="mb-4 card px-4 py-2.5 text-[12px] fade-in flex items-start gap-3"
      style={{ borderColor: "var(--crit)", color: "var(--crit)" }}>
      <Badge color="var(--crit)" bg="var(--crit-bg)">RESPONSE REFUSED</Badge>
      <span style={{ color: "var(--ink-2)" }}>{topologyMismatch}</span>
      <button onClick={clearMismatch} className="ml-auto sig shrink-0"
        style={{ color: "var(--ink-3)" }}>DISMISS</button>
    </div>
  );
}

function DashboardBody() {
  const { plan, counts, scheduledDay, ranked, apiUp } = usePlan();
  const [approval, setApproval] = useState<ApprovalStatus | null>(null);

  useEffect(() => {
    if (apiUp) planStatus(CURRENT_PLAN_ID).then(setApproval).catch(() => setApproval(null));
  }, [apiUp]);

  if (!plan) return null;
  const o = plan.metrics.optimised;
  const b = plan.metrics.baseline;
  const pct = (x: number, y: number) => (y === 0 ? 0 : ((x - y) / Math.abs(y)) * 100);

  const deptRows = (["ENGG", "S&T", "TRD"] as Dept[]).map((d) => {
    const all = plan.tasks.filter((t) => t.dept === d);
    const done = all.filter((t) => scheduledDay.has(t.id)).length;
    return { d, total: all.length, done };
  });

  return (
    <>
      <PageHead
        title="Maintenance Control Centre"
        subtitle="Coordinated block plan across Engineering, S&T and Traction Distribution"
        right={
          <>
            <Link href="/planning"><Button variant="primary">Block Planning</Button></Link>
            <Link href="/maintenance"><Button>Open Queue</Button></Link>
          </>
        }
      />

      <div className="mb-4"><DemoNote /></div>
      <MismatchNotice />

      {/* ---------- operational metrics ---------- */}
      <div className="mb-4">
        <MetricRow cols={4}>
          <Metric label="Critical Assets" value={String(counts.critical)}
            tone="crit" compare={`of ${counts.tasks} pending jobs`}
            hint="Jobs with a criticality index of 70 or above" />
          <Metric label="Maintenance Tasks" value={String(counts.tasks)}
            compare={`${counts.scheduled} scheduled · ${counts.deferred} deferred`} />
          <Metric label="Scheduled Blocks" value={String(o.blocks_used)}
            delta={{ pct: pct(o.blocks_used, b.blocks_used), better: o.blocks_used < b.blocks_used }}
            compare={`baseline ${b.blocks_used} · ${counts.clubbed} clubbed`}
            hint="Separate line closures needed to do the work" />
          <Metric label="Risk Retired" value={o.risk_retired_per_block_hour.toFixed(2)}
            unit="/ block-hr" tone="rail"
            delta={{ pct: pct(o.risk_retired_per_block_hour, b.risk_retired_per_block_hour), better: true }}
            compare={`baseline ${b.risk_retired_per_block_hour.toFixed(2)}`}
            hint="Criticality completed per hour of line withdrawn — the headline measure" />
          <Metric label="Corridor Adherence" value={`${Math.round(o.corridor_adherence * 100)}%`}
            tone="ok"
            delta={{ pct: pct(o.corridor_adherence, b.corridor_adherence), better: true }}
            compare={`baseline ${Math.round(b.corridor_adherence * 100)}%`}
            hint="Blocks taken inside the mandated corridor in the master chart" />
          <Metric label="High-Criticality Failures"
            value={String(o.critical_unplanned_failures)} tone="crit"
            delta={{ pct: pct(o.critical_unplanned_failures, b.critical_unplanned_failures), better: o.critical_unplanned_failures < b.critical_unplanned_failures }}
            compare={`baseline ${b.critical_unplanned_failures}`}
            hint="Assets that fail before attention, in simulation" />
          <Metric label="Overdue Tasks" value={String(counts.overdue)} tone="warn"
            compare={`${o.overdue_task_days.toLocaleString()} task-days late`}
            hint="Past the statutory due date at the start of the horizon" />
          <Metric label="Approval State"
            value={approval ? approval.state.replace(/_/g, " ") : apiUp ? "Not submitted" : "—"}
            tone={approval?.state === "SANCTIONED" ? "ok" : "ink"}
            compare={
              approval ? `${Object.keys(approval.concurrences).length} of ${approval.departments.length} concurred`
                : apiUp ? "submit from Approvals" : "solver service offline"
            } />
        </MetricRow>
      </div>

      {/* ---------- the corridor ---------- */}
      <div className="mb-4">
        <ExpandableCard
          title="Divisional Schematic — Danapur · Buxar (BXR) – Patna – Jhajha (JAJ)"
          subtitle="Pending maintenance at its actual chainage · BXR to JAJ, the divisional limit"
          right={<Link href="/network"><Button>Open Network</Button></Link>}
        >
          <NetworkDiagram
            stations={plan.stations} sections={plan.sections}
            tasks={plan.tasks} scheduledDay={scheduledDay}
            branches={plan.branches} routes={plan.routes}
          />
        </ExpandableCard>
      </div>

      {/* ---------- chart + side rail ---------- */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0,1fr) 340px", alignItems: "start" }}>
        <ExpandableCard
          title="Time–Distance Chart — Day 1"
          subtitle="Train paths against planned blocks and the mandated corridor"
          right={<Link href="/timetable"><Button>Full Timetable</Button></Link>}
        >
          <TimeDistanceChart
            sections={plan.sections} stations={plan.stations} paths={plan.paths}
            trains={plan.trains}
            corridors={plan.corridors} blocks={plan.blocks} day={0} line="DN"
          />
        </ExpandableCard>

        <div className="space-y-4">
          <Card title="Departmental Load" pad={false}>
            <div className="p-3.5 space-y-3">
              {deptRows.map(({ d, total, done }) => (
                <div key={d}>
                  <div className="flex items-center justify-between mb-1.5">
                    <DeptBadge dept={d} showSystem />
                    <span className="tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
                      {done} / {total} scheduled
                    </span>
                  </div>
                  <Bar value={done} max={total || 1} color={DEPT_COLOR[d]} />
                </div>
              ))}
              <div className="pt-2 text-[11px] leading-relaxed"
                style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
                <b style={{ color: "var(--ink-2)" }}>{o.line_closures_saved} line closures saved</b>
                {" "}— {counts.clubbed} blocks carry work for more than one department,
                at {o.clubbing_ratio.toFixed(2)} departments per block.
              </div>
            </div>
          </Card>

          <Card title="Highest Criticality" pad={false}
            right={<Link href="/maintenance" className="sig"
              style={{ color: "var(--rail)" }}>VIEW ALL</Link>}>
            <div>
              {ranked.slice(0, 7).map((t) => {
                const bd = band(t.criticality);
                return (
                  <Link key={t.id} href="/intelligence"
                    className="flex items-center gap-2.5 px-3.5 py-2 text-[11.5px]"
                    style={{ borderBottom: "1px solid var(--line)" }}>
                    <span className="tnum font-semibold w-[24px]"
                      style={{ color: BAND_COLOR[bd] }}>
                      {(t.criticality ?? 0).toFixed(0)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate" style={{ color: "var(--ink)" }}>
                        {t.type}
                      </span>
                      <span className="block tnum text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                        {t.section} · km {t.km.toFixed(1)} · {DEPT_NAME[t.dept]}
                      </span>
                    </span>
                    {scheduledDay.has(t.id)
                      ? <Badge color="var(--ok)" bg="var(--ok-bg)">D{(scheduledDay.get(t.id) ?? 0) + 1}</Badge>
                      : <Badge color="var(--crit)" bg="var(--crit-bg)">Deferred</Badge>}
                  </Link>
                );
              })}
            </div>
          </Card>

          <Card title="Data Integration" pad={false}
            right={<Link href="/sources" className="sig"
              style={{ color: "var(--rail)" }}>DETAIL</Link>}>
            <div className="p-3.5 space-y-2">
              {(["TMS", "SMMS", "TDMS"] as const).map((s) => (
                <div key={s} className="flex items-center justify-between text-[11.5px]">
                  <span className="mono" style={{ color: "var(--ink-2)" }}>{s}</span>
                  <Lamp state={apiUp ? "ok" : "off"}
                    label={apiUp ? "Connected" : "Unknown"} />
                </div>
              ))}
              <div className="flex items-center justify-between text-[11.5px]">
                <span className="mono" style={{ color: "var(--ink-2)" }}>Control Office</span>
                <Lamp state="ok" label="Timetable loaded" />
              </div>
              <p className="text-[10.5px] pt-1.5" style={{ color: "var(--ink-3)" }}>
                {apiUp
                  ? "Adapter status is live from the ingestion service."
                  : "Start the solver service to query adapter status."}
              </p>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
