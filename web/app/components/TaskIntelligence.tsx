"use client";

import { Task } from "../lib/plan";
import { band, BAND_COLOR, BAND_LABEL } from "./PlanProvider";
import { Badge, Bar, Card, DeptBadge } from "./ui";

/**
 * Why TRACKSEN ranked this job where it did.
 *
 * Every number here comes off the task itself — the criticality index, the Cox
 * expectation, the conformalised P90, the cancellation prior, and the SHAP attributions
 * the classifier produced. Nothing is recomputed in the browser and nothing is invented.
 *
 * The attribution panel is the point of the whole screen. Asking a divisional officer to
 * defer one department's work in favour of another's only works if he can interrogate
 * the reason, so the factors are shown in the model's own terms with their direction and
 * magnitude, not paraphrased into something friendlier and less checkable.
 */

export default function TaskIntelligence({ task }: { task: Task | null }) {
  if (!task) {
    return (
      <Card title="AI Maintenance Intelligence">
        <p className="text-[12px] py-8 text-center" style={{ color: "var(--ink-3)" }}>
          Select a job from the queue or the corridor to see its risk assessment.
        </p>
      </Card>
    );
  }

  const b = band(task.criticality);
  const pFail = task.p_fail ?? null;
  const eDays = task.e_days ?? null;

  // SHAP values are log-odds contributions. Shown as shares of the total moved, which
  // is what makes them comparable to each other -- not as probabilities, which they
  // are not.
  const factors = Object.entries(task.attribution)
    .sort((a, c) => Math.abs(c[1]) - Math.abs(a[1]))
    .slice(0, 5);
  const total = factors.reduce((s, [, v]) => s + Math.abs(v), 0) || 1;

  return (
    <Card
      title="AI Maintenance Intelligence"
      subtitle={`${task.id} · ${task.type}`}
      right={<DeptBadge dept={task.dept} showSystem />}
    >
      {/* ---- the three model outputs ---- */}
      <div className="grid gap-px mb-3.5"
        style={{ background: "var(--line)", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
        <Panel label="Failure risk"
          value={pFail !== null ? `${(pFail * 100).toFixed(1)}%` : "—"}
          tone={BAND_COLOR[b]}
          note={eDays !== null ? `expected failure in ${eDays.toFixed(0)} d` : "within 30-day horizon"} />
        <Panel label="Predicted duration"
          value={`P50 ${fmtH(task.p50)}`}
          note={`P90 ${fmtH(task.p90)} · demanded ${fmtH(task.demanded)}`}
          tone="var(--ink)" />
        <Panel label="Cancellation risk"
          value={task.cancellation_risk !== null
            ? `${(task.cancellation_risk * 100).toFixed(0)}%` : "—"}
          note="weak prior — near the information ceiling"
          tone="var(--ink)" />
      </div>

      {/* ---- criticality composition ---- */}
      <div className="rounded-[3px] p-3 mb-3.5" style={{ background: "var(--surface-2)" }}>
        <div className="flex items-baseline justify-between mb-2">
          <span className="sig">Criticality index</span>
          <span className="tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
            P(fail within H) × Urgency(E[time to failure]) × Consequence
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="tnum text-[26px] font-semibold leading-none"
            style={{ color: BAND_COLOR[b] }}>
            {(task.criticality ?? 0).toFixed(1)}
          </span>
          <Badge color={BAND_COLOR[b]} bg="var(--surface)">{BAND_LABEL[b]}</Badge>
          <div className="flex-1"><Bar value={task.criticality ?? 0} color={BAND_COLOR[b]} /></div>
        </div>
      </div>

      {/* ---- attribution ---- */}
      <div className="sig mb-2">Why this job is ranked here</div>
      {factors.length === 0 ? (
        <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
          No attribution recorded for this task.
        </p>
      ) : (
        <div className="space-y-[7px]">
          {factors.map(([name, v]) => {
            const share = (Math.abs(v) / total) * 100;
            const up = v >= 0;
            return (
              <div key={name} className="flex items-center gap-2.5">
                <span className="text-[11.5px] w-[168px] shrink-0 truncate"
                  style={{ color: "var(--ink-2)" }} title={name}>
                  {name}
                </span>
                <div className="flex-1 h-[6px] rounded-sm overflow-hidden"
                  style={{ background: "var(--surface-3)" }}>
                  <div className="h-full rounded-sm" style={{
                    width: `${share}%`,
                    background: up ? "var(--crit)" : "var(--ok)",
                  }} />
                </div>
                <span className="tnum text-[11px] w-[62px] text-right font-medium"
                  style={{ color: up ? "var(--crit)" : "var(--ok)" }}>
                  {up ? "+" : "−"}{share.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-[10.5px] mt-2.5 leading-relaxed" style={{ color: "var(--ink-3)" }}>
        Shares of the total SHAP contribution to the failure-risk classifier.
        Red raises the assessed risk, green lowers it.
      </p>
    </Card>
  );
}

function Panel({ label, value, note, tone }: {
  label: string; value: string; note: string; tone: string;
}) {
  return (
    <div className="px-3 py-2.5" style={{ background: "var(--surface)" }}>
      <div className="sig">{label}</div>
      <div className="tnum text-[19px] font-semibold leading-none mt-1.5" style={{ color: tone }}>
        {value}
      </div>
      <div className="text-[10.5px] mt-1 tnum" style={{ color: "var(--ink-3)" }}>{note}</div>
    </div>
  );
}

function fmtH(mins: number | null): string {
  if (mins === null || mins === undefined) return "—";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h${m ? ` ${m}m` : ""}` : `${m}m`;
}
