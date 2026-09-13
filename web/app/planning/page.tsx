"use client";

import { useEffect, useMemo, useState } from "react";
import ExpandableCard from "../components/Expandable";
import Gate from "../components/Gate";
import BlockDetail from "../components/BlockDetail";
import TimeDistanceChart from "../components/TimeDistanceChart";
import { usePlan } from "../components/PlanProvider";
import {
  Badge, Bar, Button, Card, Chip, DemoNote, DeptBadge, Empty, Lamp, Metric, MetricRow,
  PageHead, Seg,
} from "../components/ui";
import { resolve } from "../lib/api";
import { CURRENT_PLAN_ID } from "../lib/planId";
import { useRole } from "../components/RoleProvider";
import { Block, LineName, PlanData, dayLabel, hhmm } from "../lib/plan";

/**
 * Block Planning & Optimisation.
 *
 * The CP-SAT result, laid against the first-come-first-served baseline it is measured
 * over. Both plans draw from the same candidate pool and obey the same physical
 * constraints, so the difference is attributable to coordination and prioritisation
 * rather than to the baseline being handicapped — that is what makes the comparison
 * worth showing at all.
 */

export default function PlanningPage() {
  return <Gate><PlanningBody /></Gate>;
}

function PlanningBody() {
  const { plan, setPlan, apiUp, taskById } = usePlan();
  const { token } = useRole();
  const [which, setWhich] = useState<"optimised" | "baseline">("optimised");
  const [selected, setSelected] = useState<Block | null>(null);
  const [day, setDay] = useState(0);
  // One direction at a time. Drawing both overlays UP and DN in the same band, which
  // doubles the crossings for no information a planner uses -- a block sits on one line,
  // never both -- and halves the height each block gets drawn at.
  const [line, setLine] = useState<LineName | "BOTH">("DN");
  const [solving, setSolving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const blocks = useMemo(
    () => (!plan ? [] : which === "optimised" ? plan.blocks : plan.baselineBlocks),
    [plan, which],
  );

  if (!plan) return null;
  const o = plan.metrics.optimised;
  const b = plan.metrics.baseline;
  const solver = plan.meta.solver ?? {};
  const w = plan.meta.weights ?? {};
  const pct = (x: number, y: number) => (y === 0 ? 0 : ((x - y) / Math.abs(y)) * 100);

  const dayBlocks = blocks.filter(
    (bl) => bl.day === day && (line === "BOTH" || bl.line === line),
  );

  async function optimise() {
    setSolving(true);
    setNote(null);
    const before = plan!.metrics.optimised.risk_retired_per_block_hour;
    try {
      const next = await resolve([], SOLVER_BUDGET_S, CURRENT_PLAN_ID, token);
      if (!next) {
        setNote("Solver service did not respond. Showing the plan already loaded.");
      } else {
        const after = (next as PlanData).metrics.optimised.risk_retired_per_block_hour;
        const gap = (next as PlanData).meta.solver?.gap_pct;
        setPlan(next as PlanData);
        setNote(
          `Schedule re-optimised. Risk retired per block-hour ${before.toFixed(2)} → ` +
          `${after.toFixed(2)} (${after >= before ? "+" : ""}${(after - before).toFixed(2)})` +
          (gap === undefined ? "." : `, within ${Number(gap).toFixed(1)}% of the bound.`),
        );
      }
    } catch (e) {
      setNote(`Optimisation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSolving(false);
    }
  }

  return (
    <>
      <PageHead
        title="Block Planning & Optimisation"
        subtitle="CP-SAT schedule over the mandated corridor, against the baseline"
        right={
          <>
            <Lamp state={apiUp ? "ok" : "warn"} live={apiUp}
              label={apiUp ? "Solver reachable" : "Solver offline"} />
            <Button variant="primary" onClick={optimise} disabled={!apiUp || solving}
              title={apiUp ? "Re-run CP-SAT over the full queue"
                : "Start scripts/serve.py to enable optimisation"}>
              {solving ? "Optimising…" : "Optimise Schedule"}
            </Button>
          </>
        }
      />

      <div className="mb-4"><DemoNote /></div>

      {solving && <SolverProgress jobs={plan.tasks.length} />}
      {note && (
        <div className="mb-4 card px-4 py-2.5 text-[12px] fade-in flex items-center gap-3"
          style={{ color: "var(--ink-2)" }}>
          <Badge color="var(--ok)" bg="var(--ok-bg)">SCHEDULE UPDATED</Badge>
          <span className="tnum">{note}</span>
          <button onClick={() => setNote(null)} className="ml-auto sig"
            style={{ color: "var(--ink-3)" }}>DISMISS</button>
        </div>
      )}

      {/* ---------- optimised vs baseline ---------- */}
      <div className="mb-4">
        <MetricRow cols={6}>
          <Metric label="Risk Retired" value={o.risk_retired_per_block_hour.toFixed(2)}
            unit="/ block-hr" tone="rail"
            delta={{ pct: pct(o.risk_retired_per_block_hour, b.risk_retired_per_block_hour), better: true }}
            compare={`FCFS ${b.risk_retired_per_block_hour.toFixed(2)}`} />
          <Metric label="Blocks Used" value={String(o.blocks_used)}
            delta={{ pct: pct(o.blocks_used, b.blocks_used), better: o.blocks_used < b.blocks_used }}
            compare={`FCFS ${b.blocks_used}`} />
          <Metric label="Block Hours" value={o.block_hours.toFixed(1)}
            delta={{ pct: pct(o.block_hours, b.block_hours), better: o.block_hours < b.block_hours }}
            compare={`FCFS ${b.block_hours.toFixed(1)}`} />
          <Metric label="Depts per Block" value={o.clubbing_ratio.toFixed(2)}
            delta={{ pct: pct(o.clubbing_ratio, b.clubbing_ratio), better: true }}
            compare={`${o.line_closures_saved} closures saved`} />
          <Metric label="Traffic Cost" value={Math.round(o.traffic_cost).toLocaleString()}
            unit="wtd min"
            delta={{ pct: pct(o.traffic_cost, b.traffic_cost), better: o.traffic_cost < b.traffic_cost }}
            compare={`FCFS ${Math.round(b.traffic_cost).toLocaleString()}`} />
          <Metric label="Corridor Adherence" value={`${Math.round(o.corridor_adherence * 100)}%`}
            tone="ok"
            delta={{ pct: pct(o.corridor_adherence, b.corridor_adherence), better: true }}
            compare={`FCFS ${Math.round(b.corridor_adherence * 100)}%`} />
        </MetricRow>
      </div>

      <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", alignItems: "start" }}>
        {/* ---------- the chart ---------- */}
        <ExpandableCard
          title={`${which === "optimised" ? "TRACKSEN" : "Baseline (FCFS)"} — ${dayLabel(day)}`}
          subtitle="Same traffic, same constraints; only the scheduling policy differs"
          pad={false}
          right={
            <>
              <Seg label="Schedule shown" options={[
                { id: "optimised", label: "TRACKSEN" },
                { id: "baseline", label: "Baseline" },
              ]} value={which} onChange={setWhich} />
              <Seg label="Direction" options={[
                { id: "BOTH", label: "Both" }, { id: "DN", label: "DN" }, { id: "UP", label: "UP" },
              ]} value={line} onChange={setLine} />
            </>
          }
        >
          <div className="flex items-center gap-1 px-3.5 pt-3">
            {Array.from({ length: plan.meta.horizon_days }, (_, d) => (
              <Chip key={d} active={d === day} onClick={() => setDay(d)}>
                <span className="tnum">{dayLabel(d)}</span>
              </Chip>
            ))}
            <span className="ml-auto tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
              {dayBlocks.length} blocks · {dayBlocks.filter((x) => x.depts.length > 1).length} clubbed
            </span>
          </div>
          <div className="px-3 pt-2 pb-3">
            <TimeDistanceChart
              sections={plan.sections} stations={plan.stations} paths={plan.paths}
              trains={plan.trains}
              onSelect={setSelected} selectedId={selected?.id ?? null}
              corridors={plan.corridors} blocks={blocks} day={day} line={line}
            />
          </div>
        </ExpandableCard>

        {selected && (
          <BlockDetail block={selected} data={plan} taskById={taskById}
            onClose={() => setSelected(null)} />
        )}

        {/* ---------- solver + constraints ---------- */}
        <div className="space-y-4">
          <Card title="Solver Status" pad={false}>
            <div className="p-3.5 space-y-2 text-[11.5px]">
              <Row k="Engine" v="OR-Tools CP-SAT" />
              <Row k="Status" v={String(solver.status ?? "—")} />
              <Row k="Optimality gap" v={solver.gap_pct !== undefined
                ? `${Number(solver.gap_pct).toFixed(1)}%` : "—"} />
              <Row k="Wall time" v={solver.wall_time_s !== undefined
                ? `${solver.wall_time_s} s` : "—"} />
              <Row k="Candidates" v={solver.candidates !== undefined
                ? Number(solver.candidates).toLocaleString() : "—"} />
              <Row k="Assignment vars" v={solver.assign_vars !== undefined
                ? Number(solver.assign_vars).toLocaleString() : "—"} />
              <p className="pt-1.5 text-[10.5px] leading-relaxed"
                style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
                A feasible plan at a stated gap is a floor, not a ceiling: more solver
                time closes the gap and improves the result.
              </p>
            </div>
          </Card>

          <Card title="Objective Weights" pad={false}
            subtitle="Planner-tunable, not fixed constants">
            <div className="p-3.5 space-y-2 text-[11.5px]">
              <Row k="β  Clubbing bonus" v={String(w.clubbing ?? "—")} />
              <Row k="λ  Traffic cost" v={String(w.traffic ?? "—")} />
              <Row k="Corridor adherence" v={String(w.corridor ?? "—")} />
              <Row k="μ  Overdue penalty" v={String(w.overdue ?? "—")} />
              <Row k="Max blocks / dept / day" v={String(plan.maxBlocksPerDeptPerDay ?? "—")} />
              <Row k="Plant positioning" v={`${plan.machinePositioningMin ?? "—"} min`} />
            </div>
          </Card>

          <Card title="Hard Constraints" pad={false}>
            <div className="p-3.5 space-y-1.5 text-[11px]" style={{ color: "var(--ink-2)" }}>
              {[
                "Line exclusivity — one occupant per section and line",
                "One gang per department per block",
                "Plant cannot be in two places at once",
                "Departmental daily block cap",
                "Night-working restrictions by work type",
                "P90 duration must fit the window",
                "Statutory due date plus tolerance",
              ].map((c) => (
                <div key={c} className="flex gap-2">
                  <span style={{ color: "var(--ok)" }}>✓</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* ---------- the blocks themselves ---------- */}
      <Card title="Proposed Blocks" pad={false}
        subtitle={`${blocks.length} in the ${which === "optimised" ? "optimised" : "baseline"} plan`}>
        <div className="overflow-x-auto" style={{ maxHeight: 460 }}>
          <table className="ops" style={{ minWidth: 900 }}>
            <thead>
              <tr>
                <th>Day</th><th>Window</th><th>Section</th><th>Line</th>
                <th>Departments</th><th>Jobs</th><th>Corridor</th>
                <th>Criticality</th><th>Traffic cost</th><th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {blocks.slice(0, 120).map((bl: Block) => (
                <tr key={bl.id}>
                  <td className="tnum">{dayLabel(bl.day)}</td>
                  <td className="tnum text-[11.5px]">{hhmm(bl.s)}–{hhmm(bl.e)}</td>
                  <td className="tnum text-[11.5px]">{plan.sections[bl.sec]?.id}</td>
                  <td className="tnum text-[11.5px]">{bl.line}</td>
                  <td>
                    <span className="flex gap-1 flex-wrap">
                      {bl.depts.map((d) => <DeptBadge key={d} dept={d} />)}
                    </span>
                  </td>
                  <td className="tnum">{bl.tasks.length}</td>
                  <td>
                    {bl.corridor
                      ? <Badge color="var(--ok)" bg="var(--ok-bg)">In corridor</Badge>
                      : <Badge color="var(--warn)" bg="var(--warn-bg)">Outside</Badge>}
                  </td>
                  <td className="tnum">{bl.crit.toFixed(0)}</td>
                  <td className="tnum">{bl.traffic.toFixed(0)}</td>
                  <td className="text-[11px]" style={{ color: "var(--ink-3)" }}>
                    {bl.why[0] ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {blocks.length === 0 && <Empty title="No blocks in this plan" />}
        </div>
      </Card>
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span style={{ color: "var(--ink-3)" }}>{k}</span>
      <span className="tnum font-medium" style={{ color: "var(--ink)" }}>{v}</span>
    </div>
  );
}

/** The solver's time budget, in seconds. Also what the progress bar is measured against. */
const SOLVER_BUDGET_S = 30;

/**
 * How far through the solve we are.
 *
 * Measured in SECONDS SPENT, not in closeness to the optimum, and it says so. CP-SAT
 * does not publish a monotonic notion of progress -- it holds a bound and an incumbent,
 * and the gap between them can sit still for ten seconds and then collapse -- so a bar
 * claiming to show "72% optimised" would be an invention. The budget is the one thing
 * genuinely known in advance, and running out of it is genuinely what ends most solves.
 *
 * A solve that proves its bound early returns before the bar fills, which is the good
 * outcome rather than a broken indicator; the note that follows carries the gap it
 * actually reached.
 */
function SolverProgress({ jobs }: { jobs: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 200);
    return () => clearInterval(id);
  }, []);

  // Held just short of full: the solve is not finished until the response lands, and a
  // bar sitting at 100% while nothing happens reads as a hang.
  const pct = Math.min(99, (elapsed / SOLVER_BUDGET_S) * 100);

  return (
    <div className="mb-4 card px-4 py-3">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <span className="text-[12px]" style={{ color: "var(--ink-2)" }}>
          CP-SAT over {jobs} jobs and the enumerated corridor windows
        </span>
        <span className="tnum text-[13px] font-semibold" style={{ color: "var(--rail)" }}>
          {pct.toFixed(0)}%
        </span>
      </div>
      <Bar value={pct} />
      <div className="text-[11px] mt-1.5 tnum" style={{ color: "var(--ink-3)" }}>
        {elapsed.toFixed(1)}s of a {SOLVER_BUDGET_S}s solver budget — time spent, not
        distance to the optimum. It returns early if it proves the bound.
      </div>
    </div>
  );
}
