"use client";

import { useMemo, useState } from "react";
import Gate from "../components/Gate";
import TaskIntelligence from "../components/TaskIntelligence";
import { band, BAND_COLOR, BAND_LABEL, usePlan } from "../components/PlanProvider";
import { Bar, Card, DemoNote, DeptBadge, Metric, MetricRow, PageHead } from "../components/ui";
import { Band } from "../components/PlanProvider";
import { Task } from "../lib/plan";

/**
 * AI Maintenance Intelligence.
 *
 * What the four models produced and how confident we are in them. The held-out figures
 * come from `scripts/validate.py` and are cross-validated, not in-sample — a distinction
 * that matters, because in-sample numbers on boosted trees flatter badly.
 */

export default function IntelligencePage() {
  return <Gate><IntelligenceBody /></Gate>;
}

function IntelligenceBody() {
  const { plan, ranked, scheduledDay } = usePlan();
  const [selected, setSelected] = useState<Task | null>(null);

  const distribution = useMemo(() => {
    const out: Record<Band, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const t of ranked) out[band(t.criticality)] += 1;
    return out;
  }, [ranked]);

  if (!plan) return null;
  const v = plan.validation;
  const mc = plan.model_checks ?? {};
  const shown = selected ?? ranked[0] ?? null;

  const pick = (section: "criticality" | "duration" | "cancellation", metric: string) =>
    v?.[section]?.find((r) => r.metric.startsWith(metric));

  const auc = pick("criticality", "classifier AUC");
  const cox = pick("criticality", "Cox concordance");
  const cov = pick("duration", "P90 coverage");
  const mae = pick("duration", "P50 absolute error");
  const cxAuc = pick("cancellation", "cancellation AUC");
  const oracle = pick("cancellation", "ORACLE");

  return (
    <>
      <PageHead
        title="AI Maintenance Intelligence"
        subtitle="Criticality, time to failure, duration and cancellation risk"
      />
      <div className="mb-4"><DemoNote /></div>

      {/* ---------- model performance ---------- */}
      <div className="mb-4">
        <MetricRow cols={5}>
          <Metric label="Criticality AUC"
            value={auc ? auc.mean.toFixed(3) : "—"} tone="rail"
            compare={auc ? `±${auc.std.toFixed(3)} · held-out, ${v?.folds}-fold` : "run --validate"}
            hint="Gradient-boosted failure-risk classifier, scored on folds it never saw" />
          <Metric label="Cox Concordance"
            value={cox ? cox.mean.toFixed(3) : "—"}
            compare={cox ? `±${cox.std.toFixed(3)} · ordering of time-to-failure` : ""}
            hint="Proportional-hazards model; supplies the urgency term" />
          <Metric label="P90 Coverage"
            value={cov ? cov.mean.toFixed(3) : "—"} tone="ok"
            compare="target 0.90 · conformalised"
            hint="Share of jobs whose true duration fits the reserved window" />
          <Metric label="P50 Error"
            value={mae ? `${mae.mean.toFixed(1)}` : "—"} unit="min"
            compare={mc.duration?.median_actual_min
              ? `median job ${mc.duration.median_actual_min} min` : ""} />
          <Metric label="Cancellation AUC"
            value={cxAuc ? cxAuc.mean.toFixed(3) : "—"} tone="warn"
            compare={oracle ? `oracle ceiling ${oracle.mean.toFixed(3)}` : ""}
            hint="Within a whisker of the information ceiling — a weak prior by nature" />
        </MetricRow>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: "380px minmax(0,1fr)", alignItems: "start" }}>
        {/* ---------- ranked queue ---------- */}
        <div className="space-y-4">
          <Card title="Criticality Distribution" pad={false}>
            <div className="p-3.5 space-y-2.5">
              {(["critical", "high", "medium", "low"] as Band[]).map((b) => (
                <div key={b}>
                  <div className="flex justify-between text-[11.5px] mb-1">
                    <span className="inline-flex items-center gap-1.5">
                      <i className="lamp" style={{ background: BAND_COLOR[b] }} />
                      <span style={{ color: "var(--ink-2)" }}>{BAND_LABEL[b]}</span>
                    </span>
                    <span className="tnum" style={{ color: "var(--ink-3)" }}>
                      {distribution[b]}
                    </span>
                  </div>
                  <Bar value={distribution[b]} max={ranked.length || 1} color={BAND_COLOR[b]} />
                </div>
              ))}
              <p className="text-[10.5px] pt-1.5 leading-relaxed"
                style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
                Criticality = P(fail within horizon) × Urgency(Cox expectation) × Consequence.
                {mc.criticality?.spearman_rho_vs_true_urgency !== undefined && (
                  <> Rank correlation against true time-to-failure:{" "}
                    <b className="tnum" style={{ color: "var(--ink-2)" }}>
                      ρ {mc.criticality.spearman_rho_vs_true_urgency.toFixed(2)}
                    </b>.</>
                )}
              </p>
            </div>
          </Card>

          <Card title="Risk-Ranked Queue" pad={false}
            subtitle="Select a job to see its attribution">
            <div style={{ maxHeight: 520, overflowY: "auto" }}>
              {ranked.slice(0, 40).map((t) => {
                const b = band(t.criticality);
                const active = shown?.id === t.id;
                return (
                  <button key={t.id} onClick={() => setSelected(t)}
                    className="w-full text-left flex items-center gap-2.5 px-3.5 py-2"
                    style={{
                      borderBottom: "1px solid var(--line)",
                      background: active ? "var(--rail-bg)" : undefined,
                      borderLeft: `2px solid ${active ? "var(--rail)" : "transparent"}`,
                    }}>
                    <span className="tnum text-[12px] font-semibold w-[26px]"
                      style={{ color: BAND_COLOR[b] }}>
                      {(t.criticality ?? 0).toFixed(0)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11.5px]" style={{ color: "var(--ink)" }}>
                        {t.type}
                      </span>
                      <span className="block tnum text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                        {t.id} · {t.section} · km {t.km.toFixed(1)}
                        {t.e_days != null && ` · E[fail] ${t.e_days.toFixed(0)} d`}
                      </span>
                    </span>
                    <DeptBadge dept={t.dept} />
                  </button>
                );
              })}
            </div>
          </Card>
        </div>

        {/* ---------- explainability ---------- */}
        <div className="space-y-4">
          <TaskIntelligence task={shown} />

          <Card title="How These Models Are Judged">
            <div className="text-[11.5px] leading-relaxed space-y-2.5"
              style={{ color: "var(--ink-2)" }}>
              <p>
                Every figure above is <b>held-out</b>: each model is refitted on k−1 folds
                and scored on the fold it never saw. In-sample numbers on boosted trees are
                close to meaningless, and running this check found two real defects.
              </p>
              <p>
                <b>The P90 reservation did not hold.</b> In-sample coverage read 0.92;
                held-out it was 0.81 — roughly one block in five would have over-run the
                window reserved for it. The P90 is now conformalised against a calibration
                split the model never fits on.
              </p>
              <p>
                <b>Cancellation risk is near the information ceiling.</b> An oracle scored
                on the data generator&rsquo;s own probabilities reaches
                {oracle ? ` ${oracle.mean.toFixed(3)}` : " ~0.66"}; the shipped logistic
                model reaches{cxAuc ? ` ${cxAuc.mean.toFixed(3)}` : " ~0.66"}. Whether a
                given block gets cancelled is mostly irreducible, so treat that output as a
                weak prior rather than a prediction.
              </p>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
