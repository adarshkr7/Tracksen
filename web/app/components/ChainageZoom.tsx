"use client";

import { useCallback, useMemo, useState } from "react";
import { Section } from "../lib/plan";

/**
 * Zoom to a block section, shared by the schematic and the time–distance chart.
 *
 * Both charts put chainage on an axis — across on the schematic, down on the block
 * chart — so "zoom" means one thing on both: narrow the chainage domain to one block
 * section and redraw everything against it. Two hundred and eighty-one kilometres in
 * twelve hundred pixels is four kilometres to the pixel, which is fine for seeing where
 * work clusters and useless for reading a single section's detail.
 *
 * The window is a *section* rather than a free rectangle on purpose. A block section is
 * the unit the plan is actually made in — a block closes one, a corridor is granted on
 * one, and the section register lists them — so zooming to one asks the question the
 * planner already has. A free zoom would let you land halfway across a section boundary,
 * which answers nothing.
 *
 * The window carries a margin past the section on each side. Without it the section
 * fills the frame edge to edge and you lose the one thing you came to check: what sits
 * immediately either side of it.
 */

export interface KmWindow {
  km0: number;
  km1: number;
}

/** Sections on one route, in chainage order. Branch chainage is not main-line chainage. */
export function routeSections(sections: Section[], routeId = "MAIN"): Section[] {
  return sections
    .filter((s) => (s.route ?? "MAIN") === routeId)
    .slice()
    .sort((a, b) => a.km0 - b.km0);
}

/** A section plus enough of its neighbours to see what it abuts. */
export function windowFor(sec: Section, maxKm: number): KmWindow {
  const pad = Math.max(1.5, (sec.km1 - sec.km0) * 0.14);
  return {
    km0: Math.max(0, sec.km0 - pad),
    km1: Math.min(maxKm, sec.km1 + pad),
  };
}

export function useChainageZoom(sections: Section[], maxKm: number, routeId = "MAIN") {
  const list = useMemo(() => routeSections(sections, routeId), [sections, routeId]);
  const [secId, setSecId] = useState<string | null>(null);

  // A section that has gone away — the route changed, or a different plan loaded — must
  // not leave the chart zoomed to a window nothing is drawn in.
  const current = secId ? list.find((s) => s.id === secId) : undefined;

  const view = useMemo<KmWindow>(
    () => (current ? windowFor(current, maxKm) : { km0: 0, km1: maxKm }),
    [current, maxKm],
  );

  const step = useCallback(
    (d: -1 | 1) => {
      if (!list.length) return;
      setSecId((cur) => {
        const i = cur ? list.findIndex((s) => s.id === cur) : -1;
        const next = i < 0 ? (d > 0 ? 0 : list.length - 1) : i + d;
        if (next < 0 || next >= list.length) return cur;
        return list[next].id;
      });
    },
    [list],
  );

  const index = current ? list.findIndex((s) => s.id === current.id) : -1;

  return {
    list,
    view,
    secId: current ? current.id : null,
    setSecId,
    step,
    zoomed: Boolean(current),
    atFirst: index === 0,
    atLast: index === list.length - 1,
  };
}

export type ZoomState = ReturnType<typeof useChainageZoom>;

/** The control. Identical on both charts, because the gesture is identical. */
export function ChainageZoomBar({
  zoom, unit = "km", right,
}: {
  zoom: ZoomState;
  unit?: string;
  right?: React.ReactNode;
}) {
  const { list, view, secId, setSecId, step, zoomed, atFirst, atLast } = zoom;
  if (!list.length) return null;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="sig">Zoom</span>
      <button type="button" className="chip" onClick={() => step(-1)}
        disabled={zoomed && atFirst} aria-label="Previous section"
        title="Previous section">
        <Chevron dir="left" />
      </button>
      <select
        className="picker"
        value={secId ?? ""}
        aria-label="Zoom to a block section"
        onChange={(e) => setSecId(e.target.value || null)}
      >
        <option value="">Whole division · {list.length} sections</option>
        {list.map((s) => (
          <option key={s.id} value={s.id}>
            {s.a}–{s.b} · {s.km0.toFixed(0)}–{s.km1.toFixed(0)} {unit}
          </option>
        ))}
      </select>
      <button type="button" className="chip" onClick={() => step(1)}
        disabled={zoomed && atLast} aria-label="Next section" title="Next section">
        <Chevron dir="right" />
      </button>
      {zoomed && (
        <button type="button" className="chip" onClick={() => setSecId(null)}
          title="Back to the whole division">
          Reset
        </button>
      )}
      <span className="tnum text-[10.5px] ml-auto" style={{ color: "var(--ink-3)" }}>
        {right ?? `${unit} ${view.km0.toFixed(0)}–${view.km1.toFixed(0)}`}
      </span>
    </div>
  );
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden="true"
      style={{ display: "block" }}>
      <path d={dir === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}
        stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  );
}
