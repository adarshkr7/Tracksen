"use client";

import { Block, DEPT_COLOR, MIN_PER_DAY, PlanData, Task, dayLabel } from "../lib/plan";
import {
  Conflict,
  PathIndex,
  deferralRisk,
  findConflicts,
  isInsideCorridor,
  priceWindow,
} from "../lib/whatif";

/**
 * What moving this block would actually cost.
 *
 * Three questions, answered on every drag: how many paths does the new window take,
 * how much risk does waiting carry forward, and does the move break a rule. The third
 * is a refusal — the panel will not let a conflicting move be kept.
 */

interface Props {
  block: Block;
  data: PlanData;
  blocks: Block[];
  moves: Map<string, number>;
  index: PathIndex;
  taskById: Map<string, Task>;
  onMove: (blockId: string, startMin: number) => void;
  onReset: (blockId: string) => void;
  onClose: () => void;
}

export default function WhatIfPanel({
  block, data, blocks, moves, index, taskById, onMove, onReset, onClose,
}: Props) {
  const duration = block.e - block.s;
  const proposed = moves.get(block.id) ?? block.s;
  const moved = proposed !== block.s;
  const lineIdx = block.line === "UP" ? 0 : 1;
  const w = data.detentionWeights;
  const oh = data.regulationOverheadMin;

  const before = priceWindow(index, block.sec, lineIdx, block.s, block.e, w, oh);
  const after = priceWindow(index, block.sec, lineIdx, proposed, proposed + duration, w, oh);

  const beforeDay = Math.floor(block.s / MIN_PER_DAY);
  const afterDay = Math.floor(proposed / MIN_PER_DAY);
  const beforeCorridor = isInsideCorridor(data.corridors, block.sec, beforeDay, block.s, block.e);
  const afterCorridor = isInsideCorridor(
    data.corridors, block.sec, afterDay, proposed, proposed + duration,
  );

  const risk = deferralRisk(block, proposed, taskById);
  const conflicts: Conflict[] = moved
    ? findConflicts(block, proposed, data, blocks, moves, taskById)
    : [];

  const shiftDay = (delta: number) => {
    const next = proposed + delta * MIN_PER_DAY;
    if (next < 0 || next + duration > data.meta.horizon_days * MIN_PER_DAY) return;
    onMove(block.id, next);
  };

  const nudge = (delta: number) => onMove(block.id, proposed + delta);

  const sec = data.sections[block.sec];
  const costDelta = after.cost - before.cost;

  return (
    <section className="rounded-xl border fade-in"
      style={{ borderColor: "var(--line-2)", background: "var(--surface)" }}>

      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b flex-wrap"
        style={{ borderColor: "var(--line)" }}>
        <div className="flex items-baseline gap-2.5 flex-wrap">
          <span className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
            What-if · {sec.a}–{sec.b}
          </span>
          <span className="text-[11.5px] tnum" style={{ color: "var(--ink-3)" }}>
            {block.line} · {duration} min · {block.tasks.length} task
            {block.tasks.length > 1 ? "s" : ""}
          </span>
          {block.depts.map((d) => (
            <span key={d} className="rounded px-1.5 py-px text-[10px] font-medium"
              style={{ background: DEPT_COLOR[d], color: "#fff" }}>
              {d}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {moved && (
            <button onClick={() => onReset(block.id)}
              className="text-[11.5px] rounded-md px-2 py-1 border"
              style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}>
              Reset
            </button>
          )}
          <button onClick={onClose} className="text-[11.5px]"
            style={{ color: "var(--ink-3)" }}>
            close
          </button>
        </div>
      </div>

      {/* ---- controls ---- */}
      <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b"
        style={{ borderColor: "var(--line)" }}>
        <span className="text-[11px] uppercase tracking-wide mr-1"
          style={{ color: "var(--ink-3)", letterSpacing: "0.05em" }}>
          Move
        </span>
        {[
          { label: "−1 day", fn: () => shiftDay(-1) },
          { label: "−1 h", fn: () => nudge(-60) },
          { label: "−15 m", fn: () => nudge(-15) },
          { label: "+15 m", fn: () => nudge(15) },
          { label: "+1 h", fn: () => nudge(60) },
          { label: "+1 day", fn: () => shiftDay(1) },
        ].map((b) => (
          <button key={b.label} onClick={b.fn}
            className="rounded-md px-2 py-1 text-[11.5px] border transition-colors tnum"
            style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}>
            {b.label}
          </button>
        ))}
        <span className="text-[11px] ml-auto" style={{ color: "var(--ink-3)" }}>
          or drag the block on the chart
        </span>
      </div>

      {/* ---- comparison ---- */}
      <div className="grid gap-px sm:grid-cols-3"
        style={{ background: "var(--line)" }}>

        <Cell label="Window">
          <Row a={`${dayLabel(beforeDay)} ${clock(block.s)}`}
            b={moved ? `${dayLabel(afterDay)} ${clock(proposed)}` : null} />
          <div className="text-[11px] mt-1.5" style={{ color: "var(--ink-3)" }}>
            {afterCorridor ? "inside mandated corridor" : "outside corridor"}
            {beforeCorridor !== afterCorridor && (
              <span style={{ color: afterCorridor ? "var(--accent)" : "var(--danger)" }}>
                {afterCorridor ? " — gained" : " — lost"}
              </span>
            )}
          </div>
        </Cell>

        <Cell label="Traffic cost">
          <div className="flex items-baseline gap-2">
            <span className="text-[19px] leading-none tnum font-medium"
              style={{ color: "var(--ink)" }}>
              {after.cost.toFixed(0)}
            </span>
            {moved && Math.abs(costDelta) >= 0.5 && (
              <span className="text-[11.5px] tnum font-medium"
                style={{ color: costDelta < 0 ? "var(--accent)" : "var(--danger)" }}>
                {costDelta > 0 ? "+" : ""}{costDelta.toFixed(0)}
              </span>
            )}
          </div>
          <div className="text-[11px] mt-1.5 tnum" style={{ color: "var(--ink-3)" }}>
            {moved && `was ${before.cost.toFixed(0)} · `}
            {after.trains} paths affected
            {after.byClass[0] > 0 && (
              <span style={{ color: "var(--accent)" }}> · {after.byClass[0]} premier</span>
            )}
          </div>
        </Cell>

        <Cell label="Risk carried forward">
          {risk.deltaDays > 0 ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-[19px] leading-none tnum font-medium"
                  style={{ color: "var(--danger)" }}>
                  +{(risk.addedFailureProbability * 100).toFixed(0)}%
                </span>
                <span className="text-[11.5px] tnum" style={{ color: "var(--ink-3)" }}>
                  over {risk.deltaDays}d
                </span>
              </div>
              <div className="text-[11px] mt-1.5 truncate" style={{ color: "var(--ink-3)" }}>
                {risk.worstTask
                  ? `worst: ${risk.worstTask.type} (${(risk.worstTask.p * 100).toFixed(0)}%)`
                  : "—"}
              </div>
            </>
          ) : (
            <>
              <span className="text-[19px] leading-none tnum font-medium"
                style={{ color: "var(--ink)" }}>
                {risk.deltaDays < 0 ? "earlier" : "none"}
              </span>
              <div className="text-[11px] mt-1.5" style={{ color: "var(--ink-3)" }}>
                {risk.deltaDays < 0
                  ? `brought forward ${-risk.deltaDays}d`
                  : "same day — no added exposure"}
              </div>
            </>
          )}
        </Cell>
      </div>

      {/* ---- blockers ---- */}
      {conflicts.length > 0 && (
        <div className="px-4 py-3 border-t" style={{ borderColor: "var(--line)" }}>
          <div className="text-[11px] uppercase tracking-wide mb-1.5"
            style={{ color: "var(--danger)", letterSpacing: "0.05em" }}>
            {conflicts.length} constraint{conflicts.length > 1 ? "s" : ""} broken
          </div>
          {conflicts.map((c, i) => (
            <div key={i} className="text-[11.5px] flex gap-2 py-0.5"
              style={{ color: "var(--ink-2)" }}>
              <span className="shrink-0 rounded px-1.5 text-[10px] self-start mt-px"
                style={{ background: "var(--danger-bg)", color: "var(--danger)" }}>
                {c.kind}
              </span>
              <span>{c.detail}</span>
            </div>
          ))}
        </div>
      )}

      {/* ---- the work itself ---- */}
      <div className="px-4 py-3 border-t" style={{ borderColor: "var(--line)" }}>
        {block.tasks.map((tid) => {
          const t = taskById.get(tid);
          if (!t) return null;
          return (
            <div key={tid} className="flex items-start gap-2.5 py-1 text-[12px]">
              <span className="rounded px-1.5 py-px text-[10px] font-medium shrink-0
                               w-11 text-center mt-px"
                style={{ background: DEPT_COLOR[t.dept], color: "#fff" }}>
                {t.dept}
              </span>
              <div className="min-w-0">
                <div style={{ color: "var(--ink)" }}>{t.type}</div>
                <div className="text-[11px] tnum mt-0.5" style={{ color: "var(--ink-3)" }}>
                  {t.id} · km {t.km.toFixed(1)} · criticality {t.criticality?.toFixed(0)}
                  {t.e_days != null && ` · expected failure in ${t.e_days.toFixed(0)}d`}
                  {t.machine !== "NONE" && ` · ${t.machine}`}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3" style={{ background: "var(--surface)" }}>
      <div className="text-[10.5px] uppercase tracking-wide mb-1.5"
        style={{ color: "var(--ink-3)", letterSpacing: "0.05em" }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function Row({ a, b }: { a: string; b: string | null }) {
  return (
    <div className="flex items-baseline gap-2 flex-wrap">
      <span className="tnum text-[14px]"
        style={{
          color: b ? "var(--ink-3)" : "var(--ink)",
          textDecoration: b ? "line-through" : undefined,
        }}>
        {a}
      </span>
      {b && (
        <span className="tnum text-[14px] font-medium" style={{ color: "var(--ink)" }}>
          {b}
        </span>
      )}
    </div>
  );
}

function clock(minute: number): string {
  const m = ((minute % MIN_PER_DAY) + MIN_PER_DAY) % MIN_PER_DAY;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
