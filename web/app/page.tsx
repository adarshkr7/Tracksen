"use client";

import { useEffect, useMemo, useState } from "react";
import KpiStrip from "./components/KpiStrip";
import TaskQueue from "./components/TaskQueue";
import TimeDistanceChart from "./components/TimeDistanceChart";
import {
  Block,
  CLASS_COLOR,
  DEPT_COLOR,
  DEPT_FULL,
  Dept,
  LineName,
  PlanData,
  dayLabel,
  fmt,
  hhmm,
} from "./lib/plan";

type Which = "optimised" | "baseline";

export default function Page() {
  const [data, setData] = useState<PlanData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState(0);
  const [line, setLine] = useState<LineName | "BOTH">("BOTH");
  const [which, setWhich] = useState<Which>("optimised");
  const [selected, setSelected] = useState<Block | null>(null);

  useEffect(() => {
    fetch("/plan.json")
      .then((r) => {
        if (!r.ok) throw new Error(`plan.json ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  const blocks = useMemo(
    () => (!data ? [] : which === "optimised" ? data.blocks : data.baselineBlocks),
    [data, which],
  );

  const taskById = useMemo(() => {
    const m = new Map<string, PlanData["tasks"][number]>();
    data?.tasks.forEach((t) => m.set(t.id, t));
    return m;
  }, [data]);

  if (error) {
    return (
      <Shell>
        <div className="rounded-xl border p-6 text-[13px]"
          style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
          <p style={{ color: "var(--ink)" }} className="font-medium mb-1">
            No plan loaded
          </p>
          <p style={{ color: "var(--ink-2)" }}>
            {error}. Generate one first:
          </p>
          <pre className="mt-3 rounded-lg p-3 text-[11.5px] overflow-x-auto"
            style={{ background: "var(--surface-2)", color: "var(--ink-2)" }}>
python scripts/run_pipeline.py --days 7 --tasks 200{"\n"}
npm run sync   # copies out/plan.json into web/public/
          </pre>
        </div>
      </Shell>
    );
  }

  if (!data) {
    return (
      <Shell>
        <div className="h-[420px] rounded-xl border animate-pulse"
          style={{ borderColor: "var(--line)", background: "var(--surface)" }} />
      </Shell>
    );
  }

  const m = data.metrics;
  const dayBlocks = blocks.filter(
    (b) => b.day === day && (line === "BOTH" || b.line === line),
  );
  const clubbedToday = dayBlocks.filter((b) => b.depts.length > 1).length;

  return (
    <Shell>
      {/* ---------- header ---------- */}
      <header className="mb-6">
        <div className="flex items-baseline gap-2.5 flex-wrap">
          <h1 className="serif text-[26px] leading-none tracking-tight"
            style={{ color: "var(--ink)" }}>
            SAMANVAY
          </h1>
          <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Unified block plan · Ahmedabad–Vadodara · {data.meta.horizon_days}-day horizon
          </span>
        </div>
        <p className="mt-2 text-[12.5px] max-w-2xl" style={{ color: "var(--ink-2)" }}>
          A recommended plan across Engineering, S&amp;T and Traction. The competent
          authority sanctions — this system does not grant blocks.
        </p>
      </header>

      <section className="mb-6">
        <KpiStrip baseline={m.baseline} optimised={m.optimised} />
      </section>

      {/* ---------- chart ---------- */}
      <section className="rounded-xl border mb-6"
        style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b"
          style={{ borderColor: "var(--line)" }}>
          <Segmented
            options={[
              { id: "optimised", label: "SAMANVAY" },
              { id: "baseline", label: "Baseline" },
            ]}
            value={which}
            onChange={(v) => { setWhich(v as Which); setSelected(null); }}
          />
          <Segmented
            options={[
              { id: "BOTH", label: "Both" },
              { id: "DN", label: "DN" },
              { id: "UP", label: "UP" },
            ]}
            value={line}
            onChange={(v) => { setLine(v as LineName | "BOTH"); setSelected(null); }}
          />

          <div className="flex items-center gap-1 ml-auto">
            {Array.from({ length: data.meta.horizon_days }, (_, d) => (
              <button
                key={d}
                onClick={() => { setDay(d); setSelected(null); }}
                className="rounded-md px-2 py-1 text-[11.5px] tnum transition-colors"
                style={{
                  background: d === day ? "var(--surface-2)" : "transparent",
                  color: d === day ? "var(--ink)" : "var(--ink-3)",
                  border: `1px solid ${d === day ? "var(--line-2)" : "transparent"}`,
                }}
              >
                {dayLabel(d)}
              </button>
            ))}
          </div>
        </div>

        <div className="px-3 pt-3 pb-1">
          <TimeDistanceChart
            sections={data.sections}
            stations={data.stations}
            paths={data.paths}
            corridors={data.corridors}
            blocks={blocks}
            day={day}
            line={line}
            onSelect={setSelected}
            selectedId={selected?.id ?? null}
          />
        </div>

        <div className="flex items-center gap-x-5 gap-y-2 flex-wrap px-4 pb-3.5 pt-1
                        text-[11px]" style={{ color: "var(--ink-3)" }}>
          {(["ENGG", "S&T", "TRD"] as Dept[]).map((d) => (
            <span key={d} className="inline-flex items-center gap-1.5">
              <i className="w-2.5 h-2.5 rounded-[2px] inline-block"
                style={{ background: DEPT_COLOR[d], opacity: 0.55 }} />
              {DEPT_FULL[d]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <i className="w-2.5 h-2.5 rounded-[2px] inline-block"
              style={{ background: "var(--club)", opacity: 0.5 }} />
            clubbed
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="w-4 h-2.5 rounded-[2px] inline-block"
              style={{ background: "var(--accent)", opacity: 0.12 }} />
            mandated corridor
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="w-4 h-px inline-block" style={{ background: CLASS_COLOR[0] }} />
            premier path
          </span>
          <span className="ml-auto tnum">
            {dayBlocks.length} blocks · {clubbedToday} clubbed
          </span>
        </div>
      </section>

      {/* ---------- selection ---------- */}
      {selected && (
        <section className="rounded-xl border mb-6 fade-in"
          style={{ borderColor: "var(--line-2)", background: "var(--surface)" }}>
          <div className="flex items-center justify-between px-4 py-3 border-b"
            style={{ borderColor: "var(--line)" }}>
            <div className="flex items-baseline gap-2.5 flex-wrap">
              <span className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
                {data.sections[selected.sec].a}–{data.sections[selected.sec].b}
              </span>
              <span className="text-[12px] tnum" style={{ color: "var(--ink-3)" }}>
                {selected.line} · {dayLabel(selected.day)} {hhmm(selected.s)}–{hhmm(selected.e)}
                {" · "}{selected.e - selected.s} min
              </span>
            </div>
            <button onClick={() => setSelected(null)}
              className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              close
            </button>
          </div>

          <div className="px-4 py-3 grid gap-4 md:grid-cols-[1fr_240px]">
            <div>
              {selected.tasks.map((tid) => {
                const t = taskById.get(tid);
                if (!t) return null;
                return (
                  <div key={tid} className="flex items-start gap-2.5 py-1.5 text-[12px]">
                    <span className="rounded px-1.5 py-px text-[10px] font-medium shrink-0
                                     w-11 text-center mt-px"
                      style={{ background: DEPT_COLOR[t.dept], color: "#fff" }}>
                      {t.dept}
                    </span>
                    <div className="min-w-0">
                      <div style={{ color: "var(--ink)" }}>{t.type}</div>
                      <div className="text-[11px] tnum mt-0.5" style={{ color: "var(--ink-3)" }}>
                        {t.id} · km {t.km.toFixed(1)} · severity {t.severity} ·
                        criticality {t.criticality?.toFixed(0)} ·
                        demanded {t.demanded}m → reserved {t.p90}m
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="text-[11.5px] space-y-1.5 md:border-l md:pl-4"
              style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}>
              {selected.why.map((w, i) => (
                <div key={i} className="flex gap-1.5">
                  <span style={{ color: "var(--ink-3)" }}>—</span>
                  <span>{w}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ---------- queue ---------- */}
      <section className="mb-6">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
            Unified priority queue
          </h2>
          <span className="text-[11.5px] tnum" style={{ color: "var(--ink-3)" }}>
            {m.optimised.tasks_scheduled} of {data.tasks.length} scheduled ·
            {" "}{m.optimised.tasks_unscheduled} deferred
          </span>
        </div>
        <TaskQueue tasks={data.tasks} blocks={data.blocks} />
      </section>

      {/* ---------- footnote ---------- */}
      <footer className="text-[11px] leading-relaxed pb-10"
        style={{ color: "var(--ink-3)" }}>
        <p>
          Synthetic data modelled on published maintenance intervals; no live railway
          operational data. Figures compare two runs of the same simulator over an
          identical task population. Solver stopped at a{" "}
          {typeof data.meta.solver.gap_pct === "number"
            ? `${data.meta.solver.gap_pct}%`
            : "reported"}{" "}
          optimality gap, so results are a floor. Weights — clubbing β{" "}
          {data.meta.weights.clubbing}, traffic λ {data.meta.weights.traffic},
          corridor {data.meta.weights.corridor}, overdue μ {data.meta.weights.overdue}
          {" "}— are planner-tunable, not fixed constants.
        </p>
        <p className="mt-1.5">
          Duration model: the demanded figure contains the actual work{" "}
          {Math.round((data.model_checks.duration?.demanded_coverage ?? 0) * 100)}% of
          the time; the P90 reservation contains it{" "}
          {Math.round((data.model_checks.duration?.p90_coverage ?? 0) * 100)}%.
        </p>
      </footer>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen px-5 sm:px-8 py-8">
      <div className="mx-auto" style={{ maxWidth: 1240 }}>{children}</div>
    </main>
  );
}

function Segmented({
  options, value, onChange,
}: {
  options: { id: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="inline-flex rounded-md border overflow-hidden"
      style={{ borderColor: "var(--line-2)" }}>
      {options.map((o, i) => (
        <button
          key={o.id}
          onClick={() => onChange(o.id)}
          className="px-2.5 py-1 text-[11.5px] transition-colors"
          style={{
            background: value === o.id ? "var(--ink)" : "transparent",
            color: value === o.id ? "var(--bg)" : "var(--ink-2)",
            borderLeft: i === 0 ? "none" : "1px solid var(--line-2)",
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
