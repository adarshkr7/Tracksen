"use client";

import { useMemo, useState } from "react";
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

/**
 * The time–distance chart: time across, chainage down.
 *
 * This is the artefact railway operating staff already read every day. Train paths
 * are the diagonals; a block is a rectangle, because a block closes a whole section
 * for a stretch of time. Everything else on the page is secondary to this.
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
}

export default function TimeDistanceChart({
  sections, stations, paths, corridors, blocks, day, line, onSelect, selectedId,
}: Props) {
  const [hover, setHover] = useState<Block | null>(null);

  const maxKm = stations.length ? stations[stations.length - 1].km : 100;
  const both = line === "BOTH";
  const lineIdx = line === "UP" ? 0 : 1;

  const x = (minOfDay: number) => M.left + (minOfDay / MIN_PER_DAY) * PLOT_W;
  const y = (km: number) => M.top + (km / maxKm) * PLOT_H;

  const dayStart = day * MIN_PER_DAY;

  // Only this day, only this line. Paths are per-section occupations, so the full
  // diagonal composes itself out of one short segment per section.
  const visiblePaths = useMemo(
    () =>
      paths.filter(
        (p) =>
          (both || p[1] === lineIdx) &&
          p[4] > dayStart &&
          p[3] < dayStart + MIN_PER_DAY,
      ),
    [paths, lineIdx, both, dayStart],
  );

  const visibleBlocks = useMemo(
    () => blocks.filter((b) => (both || b.line === line) && b.day === day),
    [blocks, line, both, day],
  );

  const visibleCorridors = useMemo(
    () => corridors.filter((c) => c[1] === day),
    [corridors, day],
  );

  const active = hover ?? blocks.find((b) => b.id === selectedId) ?? null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="w-full h-auto select-none"
        role="img"
        aria-label={`Time-distance chart, ${line} line, day ${day + 1}`}
      >
        {/* ---- corridor bands: the mandated maintenance window ---- */}
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

        {/* ---- section boundaries + station labels ---- */}
        {stations.map((st) => (
          <g key={st.code}>
            <line
              x1={M.left} x2={VB_W - M.right}
              y1={y(st.km)} y2={y(st.km)}
              stroke="var(--line)" strokeWidth={1}
            />
            <text
              x={M.left - 8} y={y(st.km) + 3.5}
              textAnchor="end" fontSize={10.5}
              fill="var(--ink-3)" className="tnum"
            >
              {st.code}
            </text>
          </g>
        ))}

        {/* ---- hour gridlines ---- */}
        {Array.from({ length: 13 }, (_, i) => i * 2).map((h) => (
          <g key={h}>
            <line
              x1={x(h * 60)} x2={x(h * 60)}
              y1={M.top} y2={M.top + PLOT_H}
              stroke="var(--line)" strokeWidth={h % 6 === 0 ? 1 : 0.5}
              opacity={h % 6 === 0 ? 1 : 0.6}
            />
            <text
              x={x(h * 60)} y={VB_H - M.bottom + 16}
              textAnchor="middle" fontSize={10}
              fill="var(--ink-3)" className="tnum"
            >
              {String(h).padStart(2, "0")}
            </text>
          </g>
        ))}

        {/* ---- train paths ---- */}
        <g className="train-paths">
          {visiblePaths.map((p, i) => {
            const sec = sections[p[0]];
            if (!sec) return null;
            const t0 = p[3] - dayStart;
            const t1 = p[4] - dayStart;
            // UP runs km0 -> km1; DN runs the other way.
            const up = p[1] === 0;
            const kmA = up ? sec.km0 : sec.km1;
            const kmB = up ? sec.km1 : sec.km0;
            return (
              <line
                key={i}
                x1={x(t0)} y1={y(kmA)}
                x2={x(t1)} y2={y(kmB)}
                stroke={CLASS_COLOR[p[2]]}
                strokeWidth={CLASS_WIDTH[p[2]]}
                strokeOpacity={p[5]}
                strokeLinecap="round"
              />
            );
          })}
        </g>

        {/* ---- blocks ---- */}
        {visibleBlocks.map((b) => {
          const sec = sections[b.sec];
          if (!sec) return null;
          const clubbed = b.depts.length > 1;
          const color = clubbed ? "var(--club)" : DEPT_COLOR[b.depts[0]];
          const isActive = active?.id === b.id;
          const bx = x(b.s - dayStart);
          const bw = Math.max(3, x(b.e - dayStart) - bx);
          const top = y(sec.km0);
          const full = y(sec.km1) - top;
          const by = both && b.line === "DN" ? top + full / 2 : top;
          const bh = both ? full / 2 : full;

          return (
            <g
              key={b.id}
              onMouseEnter={() => setHover(b)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(b)}
              style={{ cursor: "pointer" }}
            >
              <rect
                className={`block-fill${clubbed ? " clubbed" : ""}${isActive ? " active" : ""}`}
                x={bx} y={by} width={bw} height={bh}
                fill={color}
                stroke={color}
                strokeWidth={isActive ? 2 : clubbed ? 1.5 : 1}
                rx={2}
              />
              {clubbed && bw > 22 && bh > 14 && (
                <text
                  x={bx + bw / 2} y={by + bh / 2 + 3.5}
                  textAnchor="middle" fontSize={9.5} fontWeight={600}
                  fill="var(--surface)" style={{ pointerEvents: "none" }}
                >
                  {b.depts.length}
                </text>
              )}
            </g>
          );
        })}

        {/* ---- frame ---- */}
        <rect
          x={M.left} y={M.top} width={PLOT_W} height={PLOT_H}
          fill="none" stroke="var(--line-2)" strokeWidth={1}
        />
      </svg>

      {/* ---- tooltip ---- */}
      {active && (() => {
        const sec = sections[active.sec];
        const bx = x(active.s - dayStart);
        const by = both && active.line === "DN" ? y(sec.km1)
          : y(sec.km0) + (y(sec.km1) - y(sec.km0)) * (both ? 0.5 : 1);
        const left = Math.min(Math.max((bx / VB_W) * 100, 2), 68);
        const top = (by / VB_H) * 100;
        return (
          <div
            className="absolute z-10 pointer-events-none fade-in rounded-lg border
                       px-3 py-2 shadow-sm text-[11.5px] leading-relaxed"
            style={{
              left: `${left}%`,
              top: `calc(${top}% + 8px)`,
              maxWidth: "min(320px, 42%)",
              background: "var(--surface)",
              borderColor: "var(--line-2)",
              color: "var(--ink-2)",
            }}
          >
            <div className="flex items-baseline justify-between gap-3 mb-1">
              <span style={{ color: "var(--ink)" }} className="font-medium">
                {sec.a}–{sec.b} · {active.line}
              </span>
              <span className="tnum" style={{ color: "var(--ink-3)" }}>
                {hhmm(active.s)}–{hhmm(active.e)}
              </span>
            </div>
            <div className="flex flex-wrap gap-1 mb-1.5">
              {active.depts.map((d) => (
                <span
                  key={d}
                  className="rounded px-1.5 py-px text-[10px] font-medium"
                  style={{ background: DEPT_COLOR[d], color: "#fff" }}
                >
                  {d}
                </span>
              ))}
              {active.corridor && (
                <span
                  className="rounded px-1.5 py-px text-[10px]"
                  style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
                >
                  corridor
                </span>
              )}
            </div>
            <div className="tnum">
              criticality {active.crit.toFixed(0)} · traffic {active.traffic.toFixed(0)} wtd min
              · {active.tasks.length} task{active.tasks.length > 1 ? "s" : ""}
            </div>
            {active.why[0] && (
              <div className="mt-1" style={{ color: "var(--ink-3)" }}>
                {active.why[0]}
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
