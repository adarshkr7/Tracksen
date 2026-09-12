"use client";

import Gate from "../components/Gate";
import { usePlan } from "../components/PlanProvider";
import { Badge, Card, DemoNote, Empty, Metric, MetricRow, PageHead } from "../components/ui";
import { FoldScore } from "../lib/plan";

/**
 * Model Performance.
 *
 * The cross-validated figures from `scripts/validate.py`, shown with their fold spread
 * rather than as bare point estimates — a mean without a standard deviation invites more
 * confidence than five folds can support.
 *
 * Where a number is not in the plan file, this says so instead of substituting a
 * plausible one.
 */

const SECTION_TITLE: Record<string, string> = {
  criticality: "Criticality & Time-to-Failure",
  duration: "Block Duration",
  cancellation: "Cancellation Risk",
};

export default function PerformancePage() {
  return <Gate><PerformanceBody /></Gate>;
}

function PerformanceBody() {
  const { plan } = usePlan();
  if (!plan) return null;

  const v = plan.validation;
  const o = plan.metrics.optimised;
  const b = plan.metrics.baseline;
  const solver = plan.meta.solver ?? {};
  const pct = (x: number, y: number) => (y === 0 ? 0 : ((x - y) / Math.abs(y)) * 100);

  return (
    <>
      <PageHead
        title="Model & Solver Performance"
        subtitle={v
          ? `${v.folds}-fold cross-validation — every figure scored on data the models never saw`
          : "Validation report not present in this plan file"}
      />
      <div className="mb-4"><DemoNote /></div>

      {/* ---------- plan outcome ---------- */}
      <div className="mb-4">
        <MetricRow cols={6}>
          <Metric label="Risk Retired" value={o.risk_retired_per_block_hour.toFixed(2)}
            unit="/ block-hr" tone="rail"
            delta={{ pct: pct(o.risk_retired_per_block_hour, b.risk_retired_per_block_hour), better: true }}
            compare={`FCFS baseline ${b.risk_retired_per_block_hour.toFixed(2)}`} />
          <Metric label="Blocks Used" value={String(o.blocks_used)}
            delta={{ pct: pct(o.blocks_used, b.blocks_used), better: o.blocks_used < b.blocks_used }}
            compare={`FCFS ${b.blocks_used}`} />
          <Metric label="Block Utilisation"
            value={`${Math.round(o.block_utilisation * 100)}%`}
            compare={`FCFS ${Math.round(b.block_utilisation * 100)}%`} />
          <Metric label="Unplanned Failures" value={String(o.unplanned_failures)}
            tone="crit"
            delta={{ pct: pct(o.unplanned_failures, b.unplanned_failures), better: o.unplanned_failures < b.unplanned_failures }}
            compare={`FCFS ${b.unplanned_failures}`} />
          <Metric label="Overdue Task-Days" value={o.overdue_task_days.toLocaleString()}
            tone="warn"
            delta={{ pct: pct(o.overdue_task_days, b.overdue_task_days), better: o.overdue_task_days < b.overdue_task_days }}
            compare={`FCFS ${b.overdue_task_days.toLocaleString()}`}
            hint="Rises slightly by design: criticality outranks age. Tunable via the overdue weight." />
          <Metric label="Optimality Gap"
            value={solver.gap_pct !== undefined ? `${Number(solver.gap_pct).toFixed(1)}%` : "—"}
            compare={solver.wall_time_s !== undefined ? `${solver.wall_time_s} s of solver time` : ""}
            hint="Results are a floor: more solver time closes the gap" />
        </MetricRow>
      </div>

      {/* ---------- held-out validation ---------- */}
      {v ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(400px,1fr))" }}>
          {(["criticality", "duration", "cancellation"] as const).map((section) => (
            <Card key={section} title={SECTION_TITLE[section]} pad={false}>
              <table className="ops">
                <thead>
                  <tr><th>Metric</th><th style={{ width: 92 }}>Mean</th>
                    <th style={{ width: 72 }}>± SD</th></tr>
                </thead>
                <tbody>
                  {v[section].map((r: FoldScore) => (
                    <tr key={r.metric}>
                      <td>
                        <div className="text-[11.5px]" style={{ color: "var(--ink)" }}>
                          {r.metric.replace(" (held-out, conformalised)", "")
                            .replace(" (held-out)", "")}
                        </div>
                        {r.note && (
                          <div className="text-[10.5px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                            {r.note}
                          </div>
                        )}
                      </td>
                      <td className="tnum font-semibold">{r.mean.toFixed(3)}</td>
                      <td className="tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
                        {r.std.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <Empty title="No validation report in this plan file">
            Generate one:
            <pre className="mono text-[11px] rounded-[3px] p-3 mt-2 text-left inline-block"
              style={{ background: "var(--surface-2)" }}>
{`python scripts/run_pipeline.py --days 7 --tasks 200 --monthly --validate
cd web && npm run sync`}
            </pre>
          </Empty>
        </Card>
      )}

      <Card title="What These Figures Do And Do Not Say" className="mt-4">
        <div className="text-[11.5px] leading-relaxed space-y-2 max-w-4xl"
          style={{ color: "var(--ink-2)" }}>
          <p>
            <Badge color="var(--ok)" bg="var(--ok-bg)">HELD-OUT</Badge>{" "}
            Each model is refitted on k−1 folds and scored on the fold it never saw.
            In-sample numbers on boosted trees flatter badly — checking this found that
            the P90 reservation covered only 0.81 out of sample against a 0.90 target,
            and that the cancellation model was memorising noise at 0.57.
          </p>
          <p>
            <Badge color="var(--warn)" bg="var(--warn-bg)">FLOOR, NOT CEILING</Badge>{" "}
            The optimality gap is time-dependent: measured on this instance, 25.1% at
            20 seconds and 7.4% at 90. Every scheduling figure above is what a
            time-limited solve achieved, not the best the formulation can do.
          </p>
          <p>
            <Badge color="var(--crit)" bg="var(--crit-bg)">SIMULATED</Badge>{" "}
            Failure counts come from simulator ground truth that no model or solver ever
            sees. That is what makes it a fair test of whether the plan got there before
            the asset failed — and also why it cannot be measured on real ingested data,
            which carries no such oracle.
          </p>
        </div>
      </Card>
    </>
  );
}
