"use client";

import { useCallback, useMemo, useState } from "react";
import Gate from "../components/Gate";
import TimeDistanceChart from "../components/TimeDistanceChart";
import WhatIfPanel from "../components/WhatIfPanel";
import { usePlan } from "../components/PlanProvider";
import { useRole } from "../components/RoleProvider";
import {
  Badge, Button, Card, DemoNote, Lamp, Metric, MetricRow, PageHead,
} from "../components/ui";
import { resolve } from "../lib/api";
import { CURRENT_PLAN_ID } from "../lib/planId";
import { Block, LineName, MIN_PER_DAY, PlanData, dayLabel } from "../lib/plan";
import { buildPathIndex, findConflicts, planTotals } from "../lib/whatif";

/**
 * What-If Analysis.
 *
 * Drag a block and the consequences are re-priced in the browser against the *same*
 * detention weights and regulation overhead the solver optimised with — those travel in
 * the plan rather than being retyped here, because a client that priced windows
 * differently would tell a planner a move is cheap while the optimiser believed it
 * expensive.
 *
 * "Apply scenario" hands the moves back to CP-SAT as fixed placements and re-optimises
 * everything else around them. Pinning constrains the search, so the headline usually
 * drops — the result banner says so rather than quietly showing the new number.
 */

export default function WhatIfPage() {
  return <Gate><WhatIfBody /></Gate>;
}

function WhatIfBody() {
  const { plan, setPlan, taskById, apiUp } = usePlan();
  const { token } = useRole();
  const [day, setDay] = useState(0);
  // One direction at a time. Drawing both overlays UP and DN in the same band, which
  // doubles the crossings for no information a planner uses -- a block sits on one line,
  // never both -- and halves the height each block gets drawn at.
  const [line, setLine] = useState<LineName | "BOTH">("DN");
  const [selected, setSelected] = useState<Block | null>(null);
  const [moves, setMoves] = useState<Map<string, number>>(new Map());
  // Held durations, separate from starts: a planner argues about when a possession
  // begins and about how long the line is given up for, and they are different levers.
  const [lengths, setLengths] = useState<Map<string, number>>(new Map());
  const [solving, setSolving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const pathIndex = useMemo(
    () => buildPathIndex(plan?.paths ?? []), [plan],
  );

  const conflictedIds = useMemo(() => {
    const out = new Set<string>();
    if (!plan || moves.size === 0) return out;
    for (const [id, start] of moves) {
      const b = plan.blocks.find((x) => x.id === id);
      if (!b) continue;
      if (findConflicts(b, start, plan, plan.blocks, moves, taskById, lengths).length > 0)
      out.add(id);
    }
    return out;
  }, [plan, moves, lengths, taskById]);

  const totals = useMemo(
    () => (plan
      ? planTotals(plan.blocks, moves, plan, pathIndex, conflictedIds, lengths) : null),
    [plan, moves, lengths, pathIndex, conflictedIds],
  );
  const basis = useMemo(
    () => (plan ? planTotals(plan.blocks, new Map(), plan, pathIndex, new Set()) : null),
    [plan, pathIndex],
  );

  const onResize = useCallback((blockId: string, minutes: number) => {
    setLengths((prev) => new Map(prev).set(blockId, minutes));
  }, []);

  const onMove = useCallback((blockId: string, startMin: number) => {
    setMoves((prev) => new Map(prev).set(blockId, startMin));
  }, []);
  const onReset = useCallback((blockId: string) => {
    setMoves((prev) => { const n = new Map(prev); n.delete(blockId); return n; });
    setLengths((prev) => { const n = new Map(prev); n.delete(blockId); return n; });
  }, []);

  const apply = useCallback(async () => {
    if (!plan || moves.size === 0) return;
    setSolving(true); setNote(null);
    const before = plan.metrics.optimised.risk_retired_per_block_hour;
    const pins = [...moves.entries()].map(([blockId, startMin]) => ({
      block_id: blockId, start_min: startMin,
      task_ids: plan.blocks.find((b) => b.id === blockId)?.tasks ?? [],
    }));
    try {
      const next = await resolve(pins, 25, CURRENT_PLAN_ID, token);
      if (!next) { setNote("Solver service did not respond."); return; }
      const after = (next as PlanData).metrics.optimised.risk_retired_per_block_hour;
      const rejected = (next as PlanData).meta.rejectedPins ?? [];
      setPlan(next as PlanData);
      setMoves(new Map()); setLengths(new Map()); setSelected(null);
      setNote(
        `Re-solved around ${pins.length - rejected.length} pinned block` +
        `${pins.length - rejected.length === 1 ? "" : "s"}. ` +
        `Risk retired per block-hour ${before.toFixed(2)} → ${after.toFixed(2)} ` +
        `(${after >= before ? "+" : ""}${(after - before).toFixed(2)}).` +
        (rejected.length ? ` Refused: ${rejected.join("; ")}` : ""),
      );
    } catch (e) {
      setNote(`Re-solve failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setSolving(false); }
  }, [plan, moves, token, setPlan]);

  if (!plan || !totals || !basis) return null;
  const costDelta = totals.trafficCost - basis.trafficCost;

  return (
    <>
      <PageHead
        title="What-If Analysis"
        subtitle="Move a block and see what it costs and what it breaks"
        right={<Lamp state={apiUp ? "ok" : "warn"} live={apiUp}
          label={apiUp ? "Solver reachable" : "Exploration only"} />}
      />
      <div className="mb-4"><DemoNote /></div>

      {(moves.size > 0 || lengths.size > 0) && (
        <div className="mb-4 card px-4 py-2.5 flex items-center gap-x-6 gap-y-2 flex-wrap fade-in"
          style={{ borderColor: conflictedIds.size ? "var(--crit)" : "var(--line-2)" }}>
          <span className="sig">
            {moves.size} block{moves.size === 1 ? "" : "s"} moved
            {lengths.size > 0 && `, ${lengths.size} resized`}
          </span>
          <span className="text-[12px] tnum" style={{ color: "var(--ink-2)" }}>
            traffic cost <b style={{ color: "var(--ink)" }}>{totals.trafficCost.toFixed(0)}</b>
            {Math.abs(costDelta) >= 0.5 && (
              <span style={{ color: costDelta < 0 ? "var(--ok)" : "var(--crit)" }}>
                {" "}{costDelta > 0 ? "+" : ""}{costDelta.toFixed(0)}
              </span>
            )}
          </span>
          <span className="text-[12px] tnum" style={{ color: "var(--ink-2)" }}>
            corridor <b style={{ color: "var(--ink)" }}>
              {Math.round(totals.corridorAdherence * 100)}%
            </b>
            <span style={{ color: "var(--ink-3)" }}>
              {" "}from {Math.round(basis.corridorAdherence * 100)}%
            </span>
          </span>
          {lengths.size > 0 && (
            // Said here rather than discovered after pressing Apply. A pin fixes WHERE a
            // block sits; the solver sizes it from the P90 of the work inside it, so
            // there is no field on a pin for a length and nothing to send. The window is
            // still worth pricing -- extending a possession is negotiated with
            // operations, not asked of CP-SAT.
            <span className="text-[11.5px]" style={{ color: "var(--warn)" }}>
              Lengths are priced here, not sent — the solver sizes a possession from the
              work in it.
            </span>
          )}
          {conflictedIds.size > 0 && (
            <Badge color="var(--crit)" bg="var(--crit-bg)">
              {conflictedIds.size} in conflict — not a valid plan
            </Badge>
          )}
          <div className="ml-auto flex items-center gap-2">
            <Button onClick={() => { setMoves(new Map()); setLengths(new Map()); }}
              disabled={solving}>Reset</Button>
            <Button variant="primary" onClick={apply}
              disabled={!apiUp || solving || conflictedIds.size > 0}
              title={conflictedIds.size
                ? "Resolve the conflicts first — the solver cannot honour an illegal pin"
                : "Hold these placements and re-optimise everything else"}>
              {solving ? "Re-solving…" : "Apply Scenario"}
            </Button>
          </div>
        </div>
      )}

      {note && (
        <div className="mb-4 card px-4 py-2.5 text-[12px] fade-in flex items-start gap-3"
          style={{ color: "var(--ink-2)" }}>
          <Badge color="var(--ok)" bg="var(--ok-bg)">SCENARIO APPLIED</Badge>
          <span className="tnum">{note}</span>
          <button onClick={() => setNote(null)} className="ml-auto sig shrink-0"
            style={{ color: "var(--ink-3)" }}>DISMISS</button>
        </div>
      )}

      <div className="mb-4">
        <MetricRow cols={4}>
          <Metric label="Blocks in Plan" value={String(plan.blocks.length)} />
          <Metric label="Traffic Cost" value={Math.round(totals.trafficCost).toLocaleString()}
            unit="wtd min" />
          <Metric label="Corridor Adherence"
            value={`${Math.round(totals.corridorAdherence * 100)}%`} tone="ok" />
          <Metric label="Conflicts" value={String(conflictedIds.size)}
            tone={conflictedIds.size ? "crit" : "ink"}
            compare={conflictedIds.size ? "illegal placements" : "all placements legal"} />
        </MetricRow>
      </div>

      <Card
        title={`Scenario Editor — ${dayLabel(day)}`}
        subtitle="Drag a block along the time axis, or nudge it from the panel below"
        pad={false}
      >
        <div className="flex items-center gap-1 px-3.5 pt-3 flex-wrap">
          {Array.from({ length: plan.meta.horizon_days }, (_, d) => (
            <button key={d} onClick={() => setDay(d)}
              className="rounded-[3px] px-2 py-[4px] text-[11px] tnum border transition-colors"
              style={{
                borderColor: d === day ? "var(--rail)" : "transparent",
                background: d === day ? "var(--rail-bg)" : "transparent",
                color: d === day ? "var(--rail)" : "var(--ink-3)",
              }}>
              {dayLabel(d)}
            </button>
          ))}
          <span className="w-px h-4 mx-1.5" style={{ background: "var(--line-2)" }} />
          {(["BOTH", "DN", "UP"] as const).map((l) => (
            <button key={l} onClick={() => setLine(l)}
              className="rounded-[3px] px-2 py-[4px] text-[11px] border transition-colors"
              style={{
                borderColor: line === l ? "var(--rail)" : "transparent",
                background: line === l ? "var(--rail-bg)" : "transparent",
                color: line === l ? "var(--rail)" : "var(--ink-3)",
              }}>
              {l === "BOTH" ? "Both lines" : `${l} line`}
            </button>
          ))}
          <span className="ml-auto tnum text-[11px]" style={{ color: "var(--ink-3)" }}>
            drag a block to test a move
          </span>
        </div>

        <div className="px-3 pt-2 pb-3">
          <TimeDistanceChart
            sections={plan.sections} stations={plan.stations} paths={plan.paths}
            trains={plan.trains}
            corridors={plan.corridors} blocks={plan.blocks} day={day} line={line}
            onSelect={setSelected} selectedId={selected?.id ?? null}
            moves={moves} lengths={lengths} onMove={onMove}
            conflictedIds={conflictedIds} draggable
          />
        </div>
      </Card>

      {selected && (
        <div className="mt-4">
          <WhatIfPanel
            block={selected} data={plan} blocks={plan.blocks} moves={moves}
            lengths={lengths} onResize={onResize}
            index={pathIndex} taskById={taskById} onMove={onMove}
            onReset={onReset} onClose={() => setSelected(null)}
          />
        </div>
      )}

      <p className="text-[10.5px] mt-4 leading-relaxed max-w-3xl" style={{ color: "var(--ink-3)" }}>
        Re-pricing uses the detention weights and regulation overhead the solver optimised
        against, carried in the plan rather than retyped in the browser. Risk carried
        forward assumes an exponential hazard around the Cox expectation — an order of
        magnitude while dragging, not a substitute for the nightly re-solve.
      </p>
    </>
  );
}
