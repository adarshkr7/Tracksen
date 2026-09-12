"use client";

import { useCallback, useId, useMemo, useRef, useState } from "react";
import {
  Block,
  CLASS_COLOR,
  CLASS_LABEL,
  CLASS_WIDTH,
  CorridorRow,
  DEPT_COLOR,
  LineName,
  MIN_PER_DAY,
  PROVENANCE,
  PathRow,
  Section,
  Station,
  TrainRow,
  hhmm,
} from "../lib/plan";
import { snap } from "../lib/whatif";
import { ChainageZoomBar, useChainageZoom } from "./ChainageZoom";

/**
 * The time–distance chart: time across, chainage down.
 *
 * This is the artefact railway operating staff already read every day. Train paths
 * are the diagonals; a block is a rectangle, because a block closes a whole section
 * for a stretch of time.
 *
 * The chart draws ONE route — the main line by default — because chainage is measured
 * per route and a branch kilometre is not a main-line kilometre. A branch service still
 * appears here, but only for the part of its run that is on this road: the Vikramshila
 * off Jamalpur shows from Kiul westward, which is exactly the part a block has to be
 * planned around.
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

/** One continuous run of a train across this route, as drawn. */
interface TrainRun {
  key: string;
  train: number;          // index into trains[]
  cls: number;
  prob: number;
  points: string;
  from: string;
  to: string;
  enter: number;          // minutes from horizon start
  exit: number;
}

interface Props {
  sections: Section[];
  stations: Station[];
  paths: PathRow[];
  /** Roster the paths index into. Without it, paths draw but do not identify. */
  trains?: TrainRow[];
  corridors: CorridorRow[];
  blocks: Block[];
  day: number;
  line: LineName | "BOTH";
  /** Which route's chainage this chart is in. Sections off it are not drawn. */
  routeId?: string;
  onSelect?: (b: Block | null) => void;
  selectedId?: string | null;
  /** Proposed starts, keyed by block id. Absent means the block sits where planned. */
  moves?: Map<string, number>;
  onMove?: (blockId: string, startMin: number) => void;
  conflictedIds?: Set<string>;
  draggable?: boolean;
}

export default function TimeDistanceChart({
  sections, stations, paths, trains, corridors, blocks, day, line,
  routeId = "MAIN", onSelect, selectedId, moves, onMove, conflictedIds,
  draggable = false,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ id: string; grabOffsetMin: number } | null>(null);
  const [hover, setHover] = useState<Block | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [trainHover, setTrainHover] =
    useState<{ run: TrainRun; x: number; y: number } | null>(null);
  const clipId = useId();

  const maxKm = stations.length ? stations[stations.length - 1].km : 100;
  const both = line === "BOTH";
  const lineIdx = line === "UP" ? 0 : 1;

  // The time axis is always a whole day -- a chart that hid part of the day would hide
  // train paths a block has to be planned around. Zoom acts on chainage only.
  const zoom = useChainageZoom(sections, maxKm, routeId);
  const { km0: viewKm0, km1: viewKm1 } = zoom.view;
  const kmSpan = Math.max(1, viewKm1 - viewKm0);

  const x = (minOfDay: number) => M.left + (minOfDay / MIN_PER_DAY) * PLOT_W;
  const y = (km: number) => M.top + ((km - viewKm0) / kmSpan) * PLOT_H;

  /** Does this section have any chainage inside the window? */
  const secInView = useCallback(
    (i: number) => {
      const sec = sections[i];
      return Boolean(sec) && sec.km1 > viewKm0 && sec.km0 < viewKm1;
    },
    [sections, viewKm0, viewKm1],
  );

  const dayStart = day * MIN_PER_DAY;
  const startOf = useCallback(
    (b: Block) => moves?.get(b.id) ?? b.s,
    [moves],
  );

  /**
   * Section indices that belong on this chart.
   *
   * Branch sections carry their own chainage from their own junction, so section 30 of
   * the Gaya branch is 30 km from Kiul, not 30 km from Buxar. Drawing it against this
   * axis would put a Kiul–Gaya passenger train somewhere near Bihiya.
   */
  const onRoute = useMemo(() => {
    const keep = new Set<number>();
    const tagged = sections.some((s) => s.route);
    sections.forEach((s, i) => {
      if (!tagged || s.route === routeId) keep.add(i);
    });
    return keep;
  }, [sections, routeId]);

  /* ---------------- train paths, assembled per train ---------------- */

  /**
   * Paths arrive one section-occupation at a time. Drawing them as loose segments
   * makes every train anonymous and impossible to point at, so they are stitched back
   * into runs here. The join is free information: where a train stands at a station
   * the run goes flat, which is what a real chart shows.
   */
  const runs = useMemo<TrainRun[]>(() => {
    const byTrain = new Map<number, PathRow[]>();
    for (const p of paths) {
      if (!onRoute.has(p[0])) continue;
      if (!both && p[1] !== lineIdx) continue;
      if (p[4] <= dayStart || p[3] >= dayStart + MIN_PER_DAY) continue;
      const t = p[6] ?? -1;
      const bucket = byTrain.get(t);
      if (bucket) bucket.push(p);
      else byTrain.set(t, [p]);
    }

    const out: TrainRun[] = [];
    for (const [train, rows] of byTrain) {
      rows.sort((a, b) => a[3] - b[3]);

      let pts: number[][] = [];
      let first: PathRow | null = null;
      let prev: PathRow | null = null;
      let part = 0;

      const flush = () => {
        if (pts.length < 2 || !first || !prev) return;
        const fs = sections[first[0]];
        const ls = sections[prev[0]];
        out.push({
          key: `${train}-${part++}`,
          train,
          cls: first[2],
          prob: first[5],
          points: pts.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" "),
          from: first[1] === 0 ? fs.a : fs.b,
          to: prev[1] === 0 ? ls.b : ls.a,
          enter: first[3],
          exit: prev[4],
        });
        pts = [];
      };

      for (const p of rows) {
        const sec = sections[p[0]];
        const up = p[1] === 0;
        const y1 = y(up ? sec.km0 : sec.km1);
        const y2 = y(up ? sec.km1 : sec.km0);
        const x1 = x(p[3] - dayStart);
        const x2 = x(p[4] - dayStart);

        // A gap in chainage means the train left this road and came back. Two runs.
        const joins = pts.length > 0 && Math.abs(y1 - pts[pts.length - 1][1]) < 0.75;
        if (!joins) {
          flush();
          first = p;
          pts = [[x1, y1]];
        }
        pts.push([x2, y2]);
        prev = p;
      }
      flush();
    }
    return out;
  }, [paths, onRoute, both, lineIdx, dayStart, sections, maxKm, viewKm0, viewKm1]);

  const visibleBlocks = useMemo(
    () =>
      blocks.filter((b) => {
        if (!onRoute.has(b.sec) || !secInView(b.sec)) return false;
        if (!both && b.line !== line) return false;
        return Math.floor(startOf(b) / MIN_PER_DAY) === day;
      }),
    [blocks, line, both, day, startOf, onRoute, secInView],
  );

  // Blocks whose original position was this day but have been dragged away — drawn
  // as a ghost so the planner can see what they changed.
  const ghosts = useMemo(
    () =>
      blocks.filter((b) => {
        const s = startOf(b);
        if (s === b.s) return false;
        if (!onRoute.has(b.sec) || !secInView(b.sec)) return false;
        if (!both && b.line !== line) return false;
        return Math.floor(b.s / MIN_PER_DAY) === day;
      }),
    [blocks, line, both, day, startOf, onRoute, secInView],
  );

  const visibleCorridors = useMemo(
    () => corridors.filter((c) => c[1] === day && onRoute.has(c[0]) && secInView(c[0])),
    [corridors, day, onRoute, secInView],
  );

  // Only a block that is actually drawn may raise a tooltip. Searching all blocks
  // would park one off the frame for a selection on another day, or -- now that the
  // chainage axis can be windowed -- for a selection outside the zoom.
  const active = hover ?? visibleBlocks.find((b) => b.id === selectedId) ?? null;

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

  /* ---------------- train hover ---------------- */

  const trackTrain = (e: React.MouseEvent, run: TrainRun) => {
    if (dragging) return;
    const svg = svgRef.current;
    if (!svg) return;
    const r = svg.getBoundingClientRect();
    setTrainHover({
      run,
      x: ((e.clientX - r.left) / r.width) * 100,
      y: ((e.clientY - r.top) / r.height) * 100,
    });
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

  const hoveredTrain = trainHover?.run.train ?? -1;

  return (
    <div className="relative">
      <div className="pb-2">
        <ChainageZoomBar
          zoom={zoom}
          right={`${visibleBlocks.length} block${visibleBlocks.length === 1 ? "" : "s"} in view`}
        />
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="w-full h-auto select-none"
        role="img"
        aria-label={`Time-distance chart, ${line} line, day ${day + 1}`}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={M.left} y={M.top} width={PLOT_W} height={PLOT_H} />
          </clipPath>
        </defs>

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

        {stations
          .filter((st) => st.km >= viewKm0 - 1e-6 && st.km <= viewKm1 + 1e-6)
          .map((st) => (
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

        <g className="train-paths" clipPath={`url(#${clipId})`}>
          {runs.map((r) => {
            const on = r.train === hoveredTrain;
            return (
              <polyline
                key={r.key}
                points={r.points}
                fill="none"
                stroke={on ? "var(--rail)" : CLASS_COLOR[r.cls]}
                strokeWidth={on ? CLASS_WIDTH[r.cls] + 1.8 : CLASS_WIDTH[r.cls]}
                strokeOpacity={on ? 1 : r.prob * 0.85}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}
        </g>

        {/* Hit targets. A path is under two pixels wide; without these nothing could
            be pointed at. Drawn before the blocks so a block always wins the hover. */}
        {trains && (
          <g clipPath={`url(#${clipId})`}>
            {runs.map((r) => (
              <polyline
                key={`hit-${r.key}`}
                points={r.points}
                fill="none"
                stroke="transparent"
                strokeWidth={7}
                strokeLinecap="round"
                style={{ pointerEvents: "stroke", cursor: "crosshair" }}
                onMouseEnter={(e) => trackTrain(e, r)}
                onMouseMove={(e) => trackTrain(e, r)}
                onMouseLeave={() => setTrainHover(null)}
              />
            ))}
          </g>
        )}

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
              onMouseEnter={() => {
                if (dragging) return;
                setHover(b);
                setTrainHover(null);
              }}
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
          style={{ pointerEvents: "none" }}
        />
      </svg>

      {/* ---- train tooltip ---- */}
      {trains && trainHover && !active && !dragging && (() => {
        const { run } = trainHover;
        const [no, name, prov] = trains[run.train] ?? ["—", "", 2];
        const p = PROVENANCE[prov] ?? PROVENANCE[2];
        const left = Math.min(Math.max(trainHover.x, 2), 66);
        const below = trainHover.y < 55;
        return (
          <div
            className="absolute z-20 pointer-events-none fade-in rounded-lg border
                       px-3 py-2 shadow-sm text-[11.5px] leading-relaxed"
            style={{
              left: `${left}%`,
              [below ? "top" : "bottom"]:
                below ? `calc(${trainHover.y}% + 14px)` : `calc(${100 - trainHover.y}% + 14px)`,
              maxWidth: "min(300px, 40%)",
              background: "var(--surface)", borderColor: "var(--line-2)",
              color: "var(--ink-2)",
            }}
          >
            <div className="flex items-baseline gap-2 mb-0.5">
              <span className="tnum font-medium" style={{ color: "var(--ink)" }}>
                {no}
              </span>
              <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                {CLASS_LABEL[run.cls]}
              </span>
            </div>
            {name && (
              <div className="mb-1" style={{ color: "var(--ink)" }}>{name}</div>
            )}
            <div className="tnum mb-1.5">
              {run.from}–{run.to} · {hhmm(run.enter)}–{hhmm(run.exit)}
              {run.prob < 1 && ` · runs ${Math.round(run.prob * 100)}% of days`}
            </div>
            <div className="flex items-start gap-1.5 pt-1.5"
              style={{ borderTop: "1px solid var(--line)" }}>
              <i className="mt-[5px] shrink-0 rounded-full"
                style={{ width: 5, height: 5, background: p.color }} />
              <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                <b style={{ color: "var(--ink-2)", fontWeight: 500 }}>{p.label}</b>
                {" — "}{p.note}
              </span>
            </div>
          </div>
        );
      })()}

      {/* ---- block tooltip ---- */}
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
