"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  Block,
  CLASS_COLOR,
  CLASS_WIDTH,
  CorridorRow,
  DEPT_COLOR,
  LineName,
  MIN_PER_DAY,
  PathRow,
  Section,
  Station,
  hhmm,
} from "../lib/plan";
import { snap } from "../lib/whatif";

/**
 * The time–distance chart: time across, chainage down.
 *
 * This is the artefact railway operating staff already read every day. Train paths
 * are the diagonals; a block is a rectangle, because a block closes a whole section
 * for a stretch of time.
 *
 * Blocks are draggable along the time axis. Dragging is deliberately constrained to
 * horizontal movement — the work is at a fixed kilometre, so a block can move in time
 * but never to another section. Use the day stepper in the panel to move it further.
 */

const VB_W = 1180;
const VB_H = 520;
const M = { top: 18, right: 18, bottom: 34, left: 58 };
const PLOT_W = VB_W - M.left - M.right;
const PLOT_H = VB_H - M.top - M.bottom;

interface Props {
  sections: Section[];
  stations: Station[];
  paths: PathRow[];
  corridors: CorridorRow[];
  blocks: Block[];
  day: number;
  line: LineName | "BOTH";
  onSelect?: (b: Block | null) => void;
  selectedId?: string | null;
  /** Proposed starts, keyed by block id. Absent means the block sits where planned. */
  moves?: Map<string, number>;
  onMove?: (blockId: string, startMin: number) => void;
  conflictedIds?: Set<string>;
  draggable?: boolean;
}

export default function TimeDistanceChart({
  sections, stations, paths, corridors, blocks, day, line,
  onSelect, selectedId, moves, onMove, conflictedIds, draggable = false,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ id: string; grabOffsetMin: number } | null>(null);
  const [hover, setHover] = useState<Block | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);

  const maxKm = stations.length ? stations[stations.length - 1].km : 100;
  const both = line === "BOTH";
  const lineIdx = line === "UP" ? 0 : 1;

  const x = (minOfDay: number) => M.left + (minOfDay / MIN_PER_DAY) * PLOT_W;
  const y = (km: number) => M.top + (km / maxKm) * PLOT_H;

  const dayStart = day * MIN_PER_DAY;
  const startOf = useCallback(
    (b: Block) => moves?.get(b.id) ?? b.s,
    [moves],
  );

  const visiblePaths = useMemo(
    () =>
      paths.filter(
        (p) => (both || p[1] === lineIdx) && p[4] > dayStart && p[3] < dayStart + MIN_PER_DAY,
      ),
    [paths, lineIdx, both, dayStart],
  );

  const visibleBlocks = useMemo(
    () =>
      blocks.filter((b) => {
        if (!both && b.line !== line) return false;
        return Math.floor(startOf(b) / MIN_PER_DAY) === day;
      }),
    [blocks, line, both, day, startOf],
  );

  // Blocks whose original position was this day but have been dragged away — drawn
  // as a ghost so the planner can see what they changed.
  const ghosts = useMemo(
    () =>
      blocks.filter((b) => {
        const s = startOf(b);
        if (s === b.s) return false;
        if (!both && b.line !== line) return false;
        return Math.floor(b.s / MIN_PER_DAY) === day;
      }),
    [blocks, line, both, day, startOf],
  );

  const visibleCorridors = useMemo(
    () => corridors.filter((c) => c[1] === day),
    [corridors, day],
  );

  const active = hover ?? blocks.find((b) => b.id === selectedId) ?? null;

  /* ---------------- drag ---------------- */

  const clientToMin = useCallback((clientX: number): number => {
    const svg = svgRef.current;
    if (!svg) return 0;
    const r = svg.getBoundingClientRect();
    const vbX = ((clientX - r.left) / r.width) * VB_W;
    return ((vbX - M.left) / PLOT_W) * MIN_PER_DAY;
  }, []);

  const onPointerDown = (e: React.PointerEvent, b: Block) => {
    if (!draggable || !onMove) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragRef.current = {
      id: b.id,
      grabOffsetMin: clientToMin(e.clientX) - (startOf(b) - dayStart),
    };
    setDragging(b.id);
    onSelect?.(b);
  };

  const onPointerMove = (e: React.PointerEvent, b: Block) => {
    const d = dragRef.current;
    if (!d || d.id !== b.id || !onMove) return;
    const duration = b.e - b.s;
    const raw = clientToMin(e.clientX) - d.grabOffsetMin;
    const clamped = Math.max(0, Math.min(MIN_PER_DAY - duration, raw));
    onMove(b.id, dayStart + snap(clamped));
  };

  const endDrag = (e: React.PointerEvent) => {
    (e.target as Element).releasePointerCapture?.(e.pointerId);
    dragRef.current = null;
    setDragging(null);
  };

  /* ---------------- geometry helper ---------------- */

  const bandOf = (b: Block) => {
    const sec = sections[b.sec];
    const top = y(sec.km0);
    const full = y(sec.km1) - top;
    return {
      by: both && b.line === "DN" ? top + full / 2 : top,
      bh: both ? full / 2 : full,
    };
  };

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="w-full h-auto select-none"
        role="img"
        aria-label={`Time-distance chart, ${line} line, day ${day + 1}`}
      >
        {visibleCorridors.map((c, i) => {
          const sec = sections[c[0]];
          if (!sec) return null;
          return (
            <rect
              key={`corr-${i}`}
              className="corridor-band"
              x={x(c[2] - dayStart)}
              width={x(c[3] - dayStart) - x(c[2] - dayStart)}
              y={y(sec.km0)}
              height={y(sec.km1) - y(sec.km0)}
            />
          );
        })}

        {stations.map((st) => (
          <g key={st.code}>
            <line
              x1={M.left} x2={VB_W - M.right} y1={y(st.km)} y2={y(st.km)}
              stroke="var(--line)" strokeWidth={1}
            />
            <text
              x={M.left - 8} y={y(st.km) + 3.5} textAnchor="end"
              fontSize={10.5} fill="var(--ink-3)" className="tnum"
            >
              {st.code}
            </text>
          </g>
        ))}

        {Array.from({ length: 13 }, (_, i) => i * 2).map((h) => (
          <g key={h}>
            <line
              x1={x(h * 60)} x2={x(h * 60)} y1={M.top} y2={M.top + PLOT_H}
              stroke="var(--line)" strokeWidth={h % 6 === 0 ? 1 : 0.5}
              opacity={h % 6 === 0 ? 1 : 0.6}
            />
            <text
              x={x(h * 60)} y={VB_H - M.bottom + 16} textAnchor="middle"
              fontSize={10} fill="var(--ink-3)" className="tnum"
            >
              {String(h).padStart(2, "0")}
            </text>
          </g>
        ))}

        <g className="train-paths">
          {visiblePaths.map((p, i) => {
            const sec = sections[p[0]];
            if (!sec) return null;
            const up = p[1] === 0;
            return (
              <line
                key={i}
                x1={x(p[3] - dayStart)} y1={y(up ? sec.km0 : sec.km1)}
                x2={x(p[4] - dayStart)} y2={y(up ? sec.km1 : sec.km0)}
                stroke={CLASS_COLOR[p[2]]}
                strokeWidth={CLASS_WIDTH[p[2]]}
                strokeOpacity={p[5]}
                strokeLinecap="round"
              />
            );
          })}
        </g>

        {/* ---- ghosts: where a moved block used to sit ---- */}
        {ghosts.map((b) => {
          const { by, bh } = bandOf(b);
          const bx = x(b.s - dayStart);
          const bw = Math.max(3, x(b.e - dayStart) - bx);
          return (
            <rect
              key={`ghost-${b.id}`}
              x={bx} y={by} width={bw} height={bh}
              fill="none" stroke="var(--ink-3)" strokeWidth={1}
              strokeDasharray="3 3" opacity={0.7} rx={2}
            />
          );
        })}

        {/* ---- blocks ---- */}
        {visibleBlocks.map((b) => {
          const sec = sections[b.sec];
          if (!sec) return null;
          const clubbed = b.depts.length > 1;
          const conflicted = conflictedIds?.has(b.id) ?? false;
          const color = conflicted
            ? "var(--danger)"
            : clubbed ? "var(--club)" : DEPT_COLOR[b.depts[0]];
          const isActive = active?.id === b.id;
          const s = startOf(b);
          const bx = x(s - dayStart);
          const bw = Math.max(3, x(s + (b.e - b.s) - dayStart) - bx);
          const { by, bh } = bandOf(b);

          return (
            <g
              key={b.id}
              onMouseEnter={() => !dragging && setHover(b)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(b)}
              onPointerDown={(e) => onPointerDown(e, b)}
              onPointerMove={(e) => onPointerMove(e, b)}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              style={{
                cursor: draggable ? (dragging === b.id ? "grabbing" : "grab") : "pointer",
                touchAction: "none",
              }}
            >
              <rect
                className={`block-fill${clubbed ? " clubbed" : ""}${isActive ? " active" : ""}`}
                x={bx} y={by} width={bw} height={bh}
                fill={color} stroke={color}
                strokeWidth={conflicted ? 2 : isActive ? 2 : clubbed ? 1.5 : 1}
                strokeDasharray={conflicted ? "4 2" : undefined}
                rx={2}
              />
              {clubbed && bw > 22 && bh > 14 && (
                <text
                  x={bx + bw / 2} y={by + bh / 2 + 3.5} textAnchor="middle"
                  fontSize={9.5} fontWeight={600} fill="var(--surface)"
                  style={{ pointerEvents: "none" }}
                >
                  {b.depts.length}
                </text>
              )}
            </g>
          );
        })}

        <rect
          x={M.left} y={M.top} width={PLOT_W} height={PLOT_H}
          fill="none" stroke="var(--line-2)" strokeWidth={1}
        />
      </svg>

      {active && !dragging && (() => {
        const sec = sections[active.sec];
        const s = startOf(active);
        const { by, bh } = bandOf(active);
        const left = Math.min(Math.max((x(s - dayStart) / VB_W) * 100, 2), 68);
        const top = ((by + bh) / VB_H) * 100;
        return (
          <div
            className="absolute z-10 pointer-events-none fade-in rounded-lg border
                       px-3 py-2 shadow-sm text-[11.5px] leading-relaxed"
            style={{
              left: `${left}%`, top: `calc(${top}% + 8px)`,
              maxWidth: "min(320px, 42%)",
              background: "var(--surface)", borderColor: "var(--line-2)",
              color: "var(--ink-2)",
            }}
          >
            <div className="flex items-baseline justify-between gap-3 mb-1">
              <span style={{ color: "var(--ink)" }} className="font-medium">
                {sec.a}–{sec.b} · {active.line}
              </span>
              <span className="tnum" style={{ color: "var(--ink-3)" }}>
                {hhmm(s)}–{hhmm(s + (active.e - active.s))}
              </span>
            </div>
            <div className="flex flex-wrap gap-1 mb-1.5">
              {active.depts.map((d) => (
                <span key={d} className="rounded px-1.5 py-px text-[10px] font-medium"
                  style={{ background: DEPT_COLOR[d], color: "#fff" }}>
                  {d}
                </span>
              ))}
              {active.corridor && (
                <span className="rounded px-1.5 py-px text-[10px]"
                  style={{ background: "var(--accent-bg)", color: "var(--accent)" }}>
                  corridor
                </span>
              )}
            </div>
            <div className="tnum">
              criticality {active.crit.toFixed(0)} · {active.tasks.length} task
              {active.tasks.length > 1 ? "s" : ""}
              {draggable && " · drag to move"}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
