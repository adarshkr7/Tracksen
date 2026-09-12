"use client";

import { useMemo, useState } from "react";
import { Branch, RouteInfo, Section, Station, Task } from "../lib/plan";
import { Band, BAND_COLOR, BAND_LABEL, band } from "./PlanProvider";
import { DEPT_COLOR, DEPT_NAME } from "./ui";

/**
 * The corridor in plan view — the schematic a P.Way officer already reads.
 *
 * Drawn as track rather than as a chart: two rails with sleepers, station ticks at their
 * real chainage, and every pending job pinned at the kilometre it actually sits at. UP
 * line work is placed above the formation and DN below, matching how a section diagram
 * is laid out.
 *
 * Branch lines are drawn as diverging stubs at their junctions. That is not decoration:
 * the Barauni line coming in over Rajendra Setu at Hathidah is *why* the Mokama–Hathidah
 * stretch is busy and maintenance-hungry, and a diagram that omitted it could not explain
 * the traffic and turnout density it shows.
 *
 * Horizontal position is real chainage, so the clustering a viewer sees is the
 * clustering the solver sees — which is the whole basis of clubbing.
 */

const VB_W = 1200;
const VB_H = 440;
const M = { left: 26, right: 26, top: 14 };
const RAIL_Y = 215;           // centre of the formation
const GAUGE = 9;              // spacing between the two rails
const LANE = 21;              // vertical step between stacked markers
const LANES = 5;              // how many rows of work stack above / below
// How far each branch is drawn out from the formation, as a fraction of the room on its
// side. Branches are perpendicular, so this is the only thing keeping two of them apart
// when their junctions are close together.
//
// One entry per modelled branch, in route order:
//   Sasaram, Hajipur, Patna-Gaya, Islampur, Rajgir, Barauni, Kiul-Gaya, Jamalpur
//
// Alternating long and short along each side does the work. In chainage order, south is
// Sasaram, Patna-Gaya, Islampur, Rajgir, Kiul-Gaya; north is Hajipur, Barauni, Jamalpur.
// Barauni and Jamalpur leave junctions ten kilometres apart -- forty pixels here -- so
// one is drawn short and the other long, and their labels sit at different depths rather
// than on top of each other.
//
// The number is not the branch's length. Length is stated on the label, where it can be
// read, rather than encoded in a geometry that already has a different job.
const BRANCH_REACH = [1.0, 1.0, 0.72, 1.0, 0.68, 0.62, 1.0, 1.0];

interface Props {
  stations: Station[];
  sections: Section[];
  tasks: Task[];
  scheduledDay: Map<string, number>;
  branches?: Branch[];
  /** Modelled routes. The second is drawn as a real diverging line, not a stub. */
  routes?: RouteInfo[];
  onSelect?: (t: Task) => void;
  selectedId?: string | null;
}

export default function NetworkDiagram({
  stations, sections, tasks, scheduledDay, branches = [], routes = [],
  onSelect, selectedId,
}: Props) {
  const [hover, setHover] = useState<{ t: Task; x: number; y: number } | null>(null);

  const maxKm = stations.length ? stations[stations.length - 1].km : 100;
  const plotW = VB_W - M.left - M.right;
  const x = (km: number) => M.left + (km / maxKm) * plotW;

  const kmOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const st of stations) m.set(st.code, st.km);
    return m;
  }, [stations]);

  const branchSectionIds = useMemo(
    () => new Set(sections.filter((s) => s.route && s.route !== "MAIN").map((s) => s.id)),
    [sections],
  );

  /** Stack markers that would otherwise sit on top of each other at the same km. */
  const placed = useMemo(() => {
    const up: { t: Task; px: number; lane: number }[] = [];
    const dn: { t: Task; px: number; lane: number }[] = [];
    const lastAt: Record<string, number[]> = { UP: [], DN: [] };

    for (const t of [...tasks].sort((a, b) => a.km - b.km)) {
      if (branchSectionIds.has(t.section)) continue;   // drawn on the branch
      const px = x(t.km);
      const track = lastAt[t.line];
      let lane = 0;
      while (lane < LANES && track[lane] !== undefined && px - track[lane] < 11) lane += 1;
      if (lane >= LANES) lane = LANES - 1;
      track[lane] = px;
      (t.line === "UP" ? up : dn).push({ t, px, lane });
    }
    return { up, dn };
  }, [tasks, maxKm, branchSectionIds]);

  const markerY = (line: "UP" | "DN", lane: number) =>
    line === "UP"
      ? RAIL_Y - GAUGE - 16 - lane * LANE
      : RAIL_Y + GAUGE + 16 + lane * LANE;

  /** Only main-line sections belong on the main scale. */
  const mainSections = useMemo(
    () => sections.filter((s) => (s.route ?? "MAIN") === "MAIN"),
    [sections],
  );

  const sectionRoute = useMemo(() => {
    const m = new Map<string, string>();
    for (const sec of sections) m.set(sec.id, sec.route ?? "MAIN");
    return m;
  }, [sections]);

  /**
   * Every modelled branch, as a real line with its own chainage.
   *
   * Drawn perpendicular to the formation, above or below it according to which side the
   * branch actually leaves on, at a depth chosen to keep neighbouring branches' labels
   * off each other.
   */
  const branchGeoms = useMemo(() => {
    const usedSide: Record<string, number> = {};

    return routes
      .filter((r) => r.id !== "MAIN")
      .map((route, idx) => {
        const jn = route.stations[0].code;
        const jnKm = kmOf.get(jn);
        if (jnKm === undefined) return null;

        const meta = branches.find(
          (b) => b.junction === jn && route.name.includes(b.name));
        const north = meta ? meta.side === "N" : true;
        const key = `${jn}:${north}`;
        const fan = (usedSide[key] = (usedSide[key] ?? 0) + 1) - 1;

        const x0 = x(jnKm);
        const dirY = north ? -1 : 1;
        const y0 = RAIL_Y + dirY * GAUGE;
        const len = route.lengthKm || 1;

        // Perpendicular, like a section diagram. A branch leaves the main line at the
        // junction and is drawn straight out from it -- the angle carries no meaning on
        // a schematic, so leaning it only invites the reader to infer a direction the
        // drawing is not claiming.
        //
        // What the length carries instead is separation. Two branches leaving junctions
        // a few kilometres apart on the same side -- Barauni at Hathidah and Jamalpur at
        // Kiul are ten km apart, forty pixels here -- would otherwise print their labels
        // on top of each other. Staggering the reach stacks them at different depths.
        const room = north
          ? RAIL_Y - GAUGE - 34
          // The station names and chainage occupy the foot of the frame, so a southward
          // branch has less room and must stop short of them rather than over them.
          : VB_H - 76 - (RAIL_Y + GAUGE);
        const reach = room * (BRANCH_REACH[idx % BRANCH_REACH.length] - fan * 0.08);

        const at = (km: number) => {
          const t = Math.max(0, Math.min(1, km / len));
          return { px: x0, py: y0 + dirY * reach * t };
        };
        return { route, at, north, label: meta?.name ?? route.name, note: meta?.note ?? "" };
      })
      .filter(Boolean) as {
        route: RouteInfo;
        at: (km: number) => { px: number; py: number };
        north: boolean; label: string; note: string;
      }[];
  }, [routes, branches, kmOf, maxKm]);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full h-auto select-none"
        role="img" aria-label="Railway corridor schematic with pending maintenance">

        {/* ---- section bands, alternating so the divisions read ---- */}
        {mainSections.map((sec, i) => (
          <rect key={sec.id}
            x={x(sec.km0)} width={x(sec.km1) - x(sec.km0)}
            y={M.top} height={VB_H - M.top - 40}
            fill={i % 2 ? "var(--surface-2)" : "transparent"} />
        ))}

        {/* ---- lane guides ---- */}
        {Array.from({ length: LANES - 1 }, (_, i) => i + 1).map((l) => (
          <g key={l} opacity={0.45}>
            <line x1={M.left} x2={VB_W - M.right}
              y1={markerY("UP", l)} y2={markerY("UP", l)}
              stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" />
            <line x1={M.left} x2={VB_W - M.right}
              y1={markerY("DN", l)} y2={markerY("DN", l)}
              stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" />
          </g>
        ))}

        {/* ---- the formation: sleepers, then two rails ---- */}
        {Array.from({ length: Math.floor(plotW / 11) }, (_, i) => {
          const px = M.left + i * 11 + 5;
          return (
            <line key={i} x1={px} x2={px}
              y1={RAIL_Y - GAUGE - 3} y2={RAIL_Y + GAUGE + 3}
              stroke="var(--line-3)" strokeWidth={2} opacity={0.55} />
          );
        })}
        <line x1={M.left} x2={VB_W - M.right} y1={RAIL_Y - GAUGE} y2={RAIL_Y - GAUGE}
          stroke="var(--chrome-3)" strokeWidth={2.6} strokeLinecap="round" />
        <line x1={M.left} x2={VB_W - M.right} y1={RAIL_Y + GAUGE} y2={RAIL_Y + GAUGE}
          stroke="var(--chrome-3)" strokeWidth={2.6} strokeLinecap="round" />

        <text x={M.left} y={RAIL_Y - GAUGE - 6} fontSize={9.5} fontWeight={600}
          fill="var(--ink-3)" letterSpacing="0.08em">UP</text>
        <text x={M.left} y={RAIL_Y + GAUGE + 13} fontSize={9.5} fontWeight={600}
          fill="var(--ink-3)" letterSpacing="0.08em">DN</text>

        {/* ---- stations; junctions get a heavier mark ---- */}
        {stations.map((st) => {
          const isJn = Boolean(st.junction);
          return (
            <g key={st.code}>
              <line x1={x(st.km)} x2={x(st.km)}
                y1={RAIL_Y - GAUGE - (isJn ? 15 : 11)}
                y2={RAIL_Y + GAUGE + (isJn ? 15 : 11)}
                stroke="var(--chrome)" strokeWidth={isJn ? 2.8 : 2.2} />
              <circle cx={x(st.km)} cy={RAIL_Y} r={isJn ? 5.6 : 4.6}
                fill={isJn ? "var(--rail)" : "var(--surface)"}
                stroke={isJn ? "var(--rail-3)" : "var(--chrome)"} strokeWidth={2.2}>
                <title>{st.name}{st.junction ? ` — ${st.junction}` : ""}</title>
              </circle>
              <text x={x(st.km)} y={VB_H - 18} textAnchor="middle"
                fontSize={11} fontWeight={isJn ? 800 : 700}
                fill={isJn ? "var(--rail)" : "var(--ink)"}>{st.code}</text>
              <text x={x(st.km)} y={VB_H - 7} textAnchor="middle"
                fontSize={9} className="tnum" fill="var(--ink-3)">
                {st.km.toFixed(0)} km
              </text>
            </g>
          );
        })}

        {/* ---- section identifiers along the formation ---- */}
        {mainSections.map((sec) => {
          const mid = (x(sec.km0) + x(sec.km1)) / 2;
          if (x(sec.km1) - x(sec.km0) < 74) return null;
          return (
            <text key={sec.id} x={mid} y={RAIL_Y + 4} textAnchor="middle"
              fontSize={8.5} fontWeight={600} fill="var(--ink-3)"
              letterSpacing="0.05em">
              {sec.id}
            </text>
          );
        })}

        {/* ---- modelled branches, as real diverging lines ---- */}
        {branchGeoms.map(({ route, at, north, label, note }) => {
          const pts = Array.from({ length: 34 }, (_, i) => at((route.lengthKm * i) / 33));
          const d = pts.map((p, i) => `${i ? "L" : "M"} ${p.px} ${p.py}`).join(" ");
          const branchTasks = tasks.filter(
            (t) => sectionRoute.get(t.section) === route.id);
          const end = at(route.lengthKm);

          return (
            <g key={route.id}>
              <path d={d} fill="none" stroke="var(--chrome-3)" strokeWidth={4.4}
                strokeLinecap="round" opacity={0.24} />
              <path d={d} fill="none" stroke="var(--chrome-3)" strokeWidth={1.9}
                strokeLinecap="round" />

              {/* Terminus and label, centred on the line rather than offset to its
                  right: the branches are vertical now, so a right-hand label would run
                  into whichever branch comes next along the formation. */}
              <circle cx={end.px} cy={end.py} r={4} fill="var(--rail)"
                stroke="var(--rail-3)" strokeWidth={1.6} />
              <text x={end.px} y={end.py + (north ? -13 : 15)} textAnchor="middle"
                fontSize={9.5} fontWeight={700} fill="var(--rail)">
                {label.toUpperCase()}
                <tspan x={end.px} dy={9.5} fontSize={7.5} fontWeight={500}
                  fill="var(--ink-3)">
                  {route.lengthKm.toFixed(0)} km{note ? ` · ${note}` : ""}
                </tspan>
              </text>

              {/* intermediate stations */}
              {route.stations.slice(1, -1).map((st) => {
                const p = at(st.km);
                return (
                  <g key={`${route.id}-${st.code}`}>
                    <circle cx={p.px} cy={p.py} r={3} fill="var(--surface)"
                      stroke="var(--chrome)" strokeWidth={1.8}>
                      <title>{st.name} — {route.name} km {st.km}</title>
                    </circle>
                    <text x={p.px + 5.5} y={p.py + 3} fontSize={7.5} fontWeight={600}
                      fill="var(--ink-3)">{st.code}</text>
                  </g>
                );
              })}

              {/* work on this branch */}
              {branchTasks.map((t) => {
                const b = band(t.criticality);
                const p = at(t.km);
                const scheduled = scheduledDay.has(t.id);
                const active = selectedId === t.id;
                const size = b === "critical" ? 8 : 6.5;
                const off = t.line === "UP" ? -8 : 8;
                return (
                  <g key={t.id}
                    onMouseEnter={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onSelect?.(t)}
                    style={{ cursor: "pointer" }}>
                    <rect x={p.px + off - size / 2} y={p.py - size / 2}
                      width={size} height={size}
                      transform={`rotate(45 ${p.px + off} ${p.py})`}
                      fill={scheduled ? BAND_COLOR[b] : "var(--surface)"}
                      stroke={BAND_COLOR[b]} strokeWidth={active ? 2.4 : 1.5} />
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* ---- pending work, pinned at its chainage ---- */}
        {[...placed.up.map((p) => ({ ...p, line: "UP" as const })),
          ...placed.dn.map((p) => ({ ...p, line: "DN" as const }))].map(
          ({ t, px, lane, line }) => {
            const b = band(t.criticality);
            const y = markerY(line, lane);
            const active = selectedId === t.id;
            const scheduled = scheduledDay.has(t.id);
            const size = b === "critical" ? 9 : 7.5;

            return (
              <g key={t.id}
                onMouseEnter={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect?.(t)}
                style={{ cursor: "pointer" }}>
                <line x1={px} x2={px} y1={y}
                  y2={line === "UP" ? RAIL_Y - GAUGE : RAIL_Y + GAUGE}
                  stroke={BAND_COLOR[b]} strokeWidth={active ? 1.6 : 0.9}
                  opacity={active ? 0.9 : 0.32} />
                <rect x={px - size / 2} y={y - size / 2} width={size} height={size}
                  transform={`rotate(45 ${px} ${y})`}
                  fill={scheduled ? BAND_COLOR[b] : "var(--surface)"}
                  stroke={BAND_COLOR[b]}
                  strokeWidth={active ? 2.4 : 1.6}
                  opacity={active ? 1 : 0.92} />
              </g>
            );
          })}
      </svg>

      {/* ---- legend ---- */}
      <div className="flex items-center gap-x-5 gap-y-1.5 flex-wrap px-1 pt-2 text-[10.5px]"
        style={{ color: "var(--ink-3)" }}>
        {(["critical", "high", "medium", "low"] as Band[]).map((b) => (
          <span key={b} className="inline-flex items-center gap-1.5">
            <i style={{
              width: 8, height: 8, background: BAND_COLOR[b],
              transform: "rotate(45deg)", display: "inline-block",
            }} />
            {BAND_LABEL[b]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <i style={{
            width: 8, height: 8, background: "var(--surface)",
            border: "1.5px solid var(--ink-3)", transform: "rotate(45deg)",
            display: "inline-block",
          }} />
          deferred (not in this plan)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i style={{
            width: 9, height: 9, borderRadius: "50%", background: "var(--rail)",
            display: "inline-block",
          }} />
          junction
        </span>
        <span className="ml-auto tnum">
          {tasks.length} pending jobs positioned by chainage
        </span>
      </div>

      {hover && (
        <div className="fixed z-40 pointer-events-none card fade-in px-3 py-2 text-[11.5px]"
          style={{
            left: Math.min(hover.x + 14,
              (typeof window !== "undefined" ? window.innerWidth : 900) - 290),
            top: hover.y + 14, maxWidth: 270, boxShadow: "0 4px 14px #16212e22",
          }}>
          <div className="font-semibold mb-1" style={{ color: "var(--ink)" }}>
            {hover.t.type}
          </div>
          <div className="tnum" style={{ color: "var(--ink-2)" }}>
            {hover.t.id} · {hover.t.section} · km {hover.t.km.toFixed(1)} · {hover.t.line}
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span style={{ color: DEPT_COLOR[hover.t.dept], fontWeight: 600 }}>
              {DEPT_NAME[hover.t.dept]}
            </span>
            <span className="tnum" style={{ color: BAND_COLOR[band(hover.t.criticality)] }}>
              criticality {hover.t.criticality?.toFixed(0)}
            </span>
          </div>
          <div className="mt-1 tnum" style={{ color: "var(--ink-3)" }}>
            {scheduledDay.has(hover.t.id)
              ? `scheduled day ${(scheduledDay.get(hover.t.id) ?? 0) + 1}`
              : "deferred beyond this horizon"}
          </div>
        </div>
      )}
    </div>
  );
}
