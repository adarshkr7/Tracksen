"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import KpiStrip from "./components/KpiStrip";
import TaskQueue from "./components/TaskQueue";
import TimeDistanceChart from "./components/TimeDistanceChart";
import WhatIfPanel from "./components/WhatIfPanel";
import {
  Block,
  CLASS_COLOR,
  DEPT_COLOR,
  DEPT_FULL,
  Dept,
  LineName,
  MIN_PER_DAY,
  PlanData,
  Task,
  dayLabel,
} from "./lib/plan";
import { buildPathIndex, findConflicts, planTotals } from "./lib/whatif";

type Which = "optimised" | "baseline";

export default function Page() {
  const [data, setData] = useState<PlanData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState(0);
  const [line, setLine] = useState<LineName | "BOTH">("BOTH");
  const [which, setWhich] = useState<Which>("optimised");
  const [selected, setSelected] = useState<Block | null>(null);
  const [moves, setMoves] = useState<Map<string, number>>(new Map());

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
    const m = new Map<string, Task>();
    data?.tasks.forEach((t) => m.set(t.id, t));
    return m;
  }, [data]);

  const pathIndex = useMemo(
    () => (data ? buildPathIndex(data.paths) : buildPathIndex([])),
    [data],
  );

  // Every moved block re-checked against the hard rules, so the chart can mark them
  // and the totals bar can refuse to call a broken plan an improvement.
  const conflictedIds = useMemo(() => {
    const out = new Set<string>();
    if (!data || moves.size === 0) return out;
    for (const [id, start] of moves) {
      const b = blocks.find((x) => x.id === id);
      if (!b) continue;
      if (findConflicts(b, start, data, blocks, moves, taskById).length > 0) out.add(id);
    }
    return out;
  }, [data, moves, blocks, taskById]);

  const totals = useMemo(
    () => (data ? planTotals(blocks, moves, data, pathIndex, conflictedIds) : null),
    [data, blocks, moves, pathIndex, conflictedIds],
  );

  const baselineTotals = useMemo(
    () => (data ? planTotals(blocks, new Map(), data, pathIndex, new Set()) : null),
    [data, blocks, pathIndex],
  );

  const onMove = useCallback((blockId: string, startMin: number) => {
    setMoves((prev) => {
      const next = new Map(prev);
      next.set(blockId, startMin);
      return next;
    });
  }, []);

  const onResetBlock = useCallback((blockId: string) => {
    setMoves((prev) => {
      const next = new Map(prev);
      next.delete(blockId);
      return next;
    });
  }, []);

  if (error) {
    return (
      <Shell>
        <div className="rounded-xl border p-6 text-[13px]"
          style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
          <p style={{ color: "var(--ink)" }} className="font-medium mb-1">No plan loaded</p>
          <p style={{ color: "var(--ink-2)" }}>{error}. Generate one first:</p>
          <pre className="mt-3 rounded-lg p-3 text-[11.5px] overflow-x-auto"
            style={{ background: "var(--surface-2)", color: "var(--ink-2)" }}>
python scripts/run_pipeline.py --days 7 --tasks 200{"\n"}
npm run sync
          </pre>
        </div>
      </Shell>
    );
  }

  if (!data || !totals || !baselineTotals) {
    return (
      <Shell>
        <div className="h-[420px] rounded-xl border animate-pulse"
          style={{ borderColor: "var(--line)", background: "var(--surface)" }} />
      </Shell>
    );
  }

  const m = data.metrics;
  const editable = which === "optimised";
  const dayBlocks = blocks.filter((b) => {
    const s = moves.get(b.id) ?? b.s;
    return Math.floor(s / MIN_PER_DAY) === day && (line === "BOTH" || b.line === line);
  });
  const clubbedToday = dayBlocks.filter((b) => b.depts.length > 1).length;
  const costDelta = totals.trafficCost - baselineTotals.trafficCost;

  return (
    <Shell>
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

      {/* ---------- what-if totals ---------- */}
      {moves.size > 0 && (
        <section className="mb-4 rounded-xl border px-4 py-2.5 flex items-center
                            gap-x-6 gap-y-2 flex-wrap fade-in"
          style={{
            borderColor: conflictedIds.size ? "var(--danger)" : "var(--line-2)",
            background: "var(--surface)",
          }}>
          <span className="text-[11px] uppercase tracking-wide"
            style={{ color: "var(--ink-3)", letterSpacing: "0.05em" }}>
            {moves.size} block{moves.size > 1 ? "s" : ""} moved
          </span>

          <span className="text-[12px] tnum" style={{ color: "var(--ink-2)" }}>
            traffic cost{" "}
            <b style={{ color: "var(--ink)" }}>{totals.trafficCost.toFixed(0)}</b>
            {Math.abs(costDelta) >= 0.5 && (
              <span style={{ color: costDelta < 0 ? "var(--accent)" : "var(--danger)" }}>
                {" "}{costDelta > 0 ? "+" : ""}{costDelta.toFixed(0)}
              </span>
            )}
          </span>

          <span className="text-[12px] tnum" style={{ color: "var(--ink-2)" }}>
            corridor{" "}
            <b style={{ color: "var(--ink)" }}>
              {Math.round(totals.corridorAdherence * 100)}%
            </b>
            <span style={{ color: "var(--ink-3)" }}>
              {" "}from {Math.round(baselineTotals.corridorAdherence * 100)}%
            </span>
          </span>

          {conflictedIds.size > 0 && (
            <span className="text-[12px] tnum font-medium" style={{ color: "var(--danger)" }}>
              {conflictedIds.size} in conflict — not a valid plan
            </span>
          )}

          <button onClick={() => setMoves(new Map())}
            className="ml-auto text-[11.5px] rounded-md px-2 py-1 border"
            style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}>
            Reset all
          </button>
        </section>
      )}

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
              <button key={d} onClick={() => setDay(d)}
                className="rounded-md px-2 py-1 text-[11.5px] tnum transition-colors"
                style={{
                  background: d === day ? "var(--surface-2)" : "transparent",
                  color: d === day ? "var(--ink)" : "var(--ink-3)",
                  border: `1px solid ${d === day ? "var(--line-2)" : "transparent"}`,
                }}>
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
            moves={moves}
            onMove={editable ? onMove : undefined}
            conflictedIds={conflictedIds}
            draggable={editable}
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
            {editable && " · drag a block to test a move"}
          </span>
        </div>
      </section>

      {selected && (
        <section className="mb-6">
          <WhatIfPanel
            block={selected}
            data={data}
            blocks={blocks}
            moves={moves}
            index={pathIndex}
            taskById={taskById}
            onMove={onMove}
            onReset={onResetBlock}
            onClose={() => setSelected(null)}
          />
        </section>
      )}

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

      <footer className="text-[11px] leading-relaxed pb-10" style={{ color: "var(--ink-3)" }}>
        <p>
          Synthetic data modelled on published maintenance intervals; no live railway
          operational data. Figures compare two runs of the same simulator over an
          identical task population. Solver stopped at a{" "}
          {typeof data.meta.solver.gap_pct === "number"
            ? `${data.meta.solver.gap_pct}%` : "reported"}{" "}
          optimality gap, so results are a floor. Weights — clubbing β{" "}
          {data.meta.weights.clubbing}, traffic λ {data.meta.weights.traffic}, corridor{" "}
          {data.meta.weights.corridor}, overdue μ {data.meta.weights.overdue} — are
          planner-tunable, not fixed constants.
        </p>
        <p className="mt-1.5">
          What-if re-prices windows client-side using the same detention weights and
          regulation overhead the solver optimised against. Risk carried forward assumes
          an exponential hazard around the Cox expectation — an order of magnitude while
          dragging, not a substitute for the nightly re-solve.
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
        <button key={o.id} onClick={() => onChange(o.id)}
          className="px-2.5 py-1 text-[11.5px] transition-colors"
          style={{
            background: value === o.id ? "var(--ink)" : "transparent",
            color: value === o.id ? "var(--bg)" : "var(--ink-2)",
            borderLeft: i === 0 ? "none" : "1px solid var(--line-2)",
          }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
