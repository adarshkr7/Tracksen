/**
 * What-if: re-price a block the moment a planner moves it.
 *
 * Everything here mirrors the Python that produced the plan — `TrafficModel.cost_of_block`
 * and the hard constraints in `optimizer/cpsat.py`. The constants come down the wire in
 * plan.json rather than being retyped, because a client that prices windows differently
 * from the solver would quietly tell the planner a move is cheap when the optimiser
 * believed it expensive.
 */

import { Block, CorridorRow, MIN_PER_DAY, PathRow, PlanData, Task } from "./plan";

export interface Pricing {
  cost: number;              // expected weighted detention minutes
  trains: number;            // paths intersected
  byClass: number[];         // paths intersected, per train class
}

/** Paths bucketed by (section, line) so a drag re-prices in microseconds. */
export type PathIndex = Map<string, PathRow[]>;

export function buildPathIndex(paths: PathRow[]): PathIndex {
  const idx: PathIndex = new Map();
  for (const p of paths) {
    const k = `${p[0]}:${p[1]}`;
    const arr = idx.get(k);
    if (arr) arr.push(p);
    else idx.set(k, [p]);
  }
  return idx;
}

export function priceWindow(
  index: PathIndex,
  sec: number,
  lineIdx: number,
  startMin: number,
  endMin: number,
  detentionWeights: number[],
  overheadMin: number,
): Pricing {
  const rows = index.get(`${sec}:${lineIdx}`) ?? [];
  let cost = 0;
  let trains = 0;
  const byClass = [0, 0, 0, 0];

  for (const p of rows) {
    const enter = p[3];
    const exit = p[4];
    if (enter >= endMin || startMin >= exit) continue;
    const overlap = Math.min(endMin, exit) - Math.max(startMin, enter);
    if (overlap <= 0) continue;
    cost += p[5] * (detentionWeights[p[2]] ?? 1) * (overlap + overheadMin);
    trains += 1;
    byClass[p[2]] += 1;
  }
  return { cost: Math.round(cost * 10) / 10, trains, byClass };
}

export function isInsideCorridor(
  corridors: CorridorRow[],
  sec: number,
  day: number,
  startMin: number,
  endMin: number,
): boolean {
  for (const c of corridors) {
    if (c[0] === sec && c[1] === day && startMin >= c[2] && endMin <= c[3]) return true;
  }
  return false;
}

/* ------------------------------------------------------------------ */
/* Proposed moves                                                      */
/* ------------------------------------------------------------------ */

export interface Move {
  blockId: string;
  startMin: number;    // absolute minutes from horizon start
}

export interface Conflict {
  kind: "line" | "machine" | "staff" | "night" | "horizon";
  detail: string;
}

/**
 * The hard rules, checked in the same order the solver would.
 *
 * These are refusals, not preferences: a plan that breaks one of them is not a worse
 * plan, it is not a plan. The panel shows them as blockers and leaves the move
 * un-applied.
 */
/** No block has been resized. Shared so callers need not each mint an empty map. */
export const NO_LENGTHS: ReadonlyMap<string, number> = new Map();

/**
 * How long a block is held under the current scenario.
 *
 * A possession has two dimensions a planner can argue about -- when it starts and how
 * long the line is given up for -- and until now only the first was modelled here. The
 * second is the one operations actually negotiates.
 */
export function durationOf(
  b: Block, lengths: ReadonlyMap<string, number> = NO_LENGTHS,
): number {
  return lengths.get(b.id) ?? b.e - b.s;
}

export function findConflicts(
  block: Block,
  proposedStart: number,
  data: PlanData,
  allBlocks: Block[],
  moves: Map<string, number>,
  taskById: Map<string, Task>,
  lengths: ReadonlyMap<string, number> = NO_LENGTHS,
): Conflict[] {
  const out: Conflict[] = [];
  const duration = durationOf(block, lengths);
  const proposedEnd = proposedStart + duration;
  const day = Math.floor(proposedStart / MIN_PER_DAY);
  const horizonEnd = data.meta.horizon_days * MIN_PER_DAY;

  if (proposedStart < 0 || proposedEnd > horizonEnd) {
    out.push({ kind: "horizon", detail: "Falls outside the planning horizon" });
    return out;
  }

  const effective = (b: Block) => {
    const s = moves.get(b.id) ?? b.s;
    return { s, e: s + durationOf(b, lengths) };
  };

  // Line exclusivity: one occupant per block section and line.
  for (const other of allBlocks) {
    if (other.id === block.id) continue;
    if (other.sec !== block.sec || other.line !== block.line) continue;
    const o = effective(other);
    if (proposedStart < o.e && o.s < proposedEnd) {
      out.push({
        kind: "line",
        detail: `Overlaps block ${other.id} on the same line (${fmtClock(o.s)}–${fmtClock(o.e)})`,
      });
    }
  }

  // Plant cannot be in two places at once, network-wide, plus positioning time.
  const machines = new Set(
    block.tasks.map((t) => taskById.get(t)?.machine).filter((m) => m && m !== "NONE"),
  );
  if (machines.size) {
    const buffer = data.machinePositioningMin ?? 90;
    for (const other of allBlocks) {
      if (other.id === block.id) continue;
      const otherMachines = new Set(
        other.tasks.map((t) => taskById.get(t)?.machine).filter((m) => m && m !== "NONE"),
      );
      const shared = [...machines].filter((m) => otherMachines.has(m));
      if (!shared.length) continue;
      const o = effective(other);
      if (proposedStart < o.e + buffer && o.s < proposedEnd + buffer) {
        out.push({
          kind: "machine",
          detail: `${shared.join(", ")} also needed by block ${other.id} within the ${buffer}-minute positioning window`,
        });
      }
    }
  }

  // A department can only mount so many blocks in a day.
  const cap = data.maxBlocksPerDeptPerDay ?? 6;
  for (const dept of block.depts) {
    let count = 0;
    for (const other of allBlocks) {
      if (other.id === block.id) continue;
      if (!other.depts.includes(dept)) continue;
      const o = effective(other);
      if (Math.floor(o.s / MIN_PER_DAY) === day) count += 1;
    }
    if (count >= cap) {
      out.push({
        kind: "staff",
        detail: `${dept} already has ${count} blocks on day ${day + 1} (limit ${cap})`,
      });
    }
  }

  // Night working is not permitted for every kind of work.
  const dayStart = 6 * 60;
  const dayEnd = 18 * 60;
  const modStart = proposedStart % MIN_PER_DAY;
  for (const tid of block.tasks) {
    const t = taskById.get(tid);
    if (!t || t.night_work_allowed !== false) continue;
    if (modStart < dayStart || modStart + duration > dayEnd) {
      out.push({
        kind: "night",
        detail: `${t.type} (${tid}) cannot be worked outside 06:00–18:00`,
      });
      break;
    }
  }

  return out;
}

/* ------------------------------------------------------------------ */
/* The cost of waiting                                                 */
/* ------------------------------------------------------------------ */

export interface DeferralRisk {
  deltaDays: number;
  addedFailureProbability: number;   // summed across the block's tasks
  worstTask: { id: string; type: string; p: number } | null;
}

/**
 * Risk carried forward by deferring a block.
 *
 * Under an exponential hazard with mean E[days to failure], the chance an asset that
 * has survived to now fails during the next Δ days is 1 − exp(−Δ / E). That memoryless
 * assumption is an approximation of the Cox model that produced E, not a re-derivation
 * of it — it is here to give the planner an honest order of magnitude while dragging,
 * not to replace the nightly re-solve.
 */
export function deferralRisk(
  block: Block,
  proposedStart: number,
  taskById: Map<string, Task>,
): DeferralRisk {
  const deltaDays =
    Math.floor(proposedStart / MIN_PER_DAY) - Math.floor(block.s / MIN_PER_DAY);

  let added = 0;
  let worst: DeferralRisk["worstTask"] = null;

  if (deltaDays > 0) {
    for (const tid of block.tasks) {
      const t = taskById.get(tid);
      if (!t?.e_days || t.e_days <= 0) continue;
      const p = 1 - Math.exp(-deltaDays / t.e_days);
      added += p;
      if (!worst || p > worst.p) worst = { id: t.id, type: t.type, p };
    }
  }

  return { deltaDays, addedFailureProbability: added, worstTask: worst };
}

/* ------------------------------------------------------------------ */
/* Plan-level totals under the current set of moves                    */
/* ------------------------------------------------------------------ */

export interface PlanTotals {
  trafficCost: number;
  corridorBlocks: number;
  corridorAdherence: number;
  conflicted: number;
}

export function planTotals(
  blocks: Block[],
  moves: Map<string, number>,
  data: PlanData,
  index: PathIndex,
  conflictedIds: Set<string>,
  lengths: ReadonlyMap<string, number> = NO_LENGTHS,
): PlanTotals {
  // No literal fallback for the weights. A hardcoded [4, 2.5, 1.5, 1] here was a second
  // copy of the solver's pricing, and it went stale the moment premier detention was
  // repriced — the same drift the server side was just fixed for, moved to the client.
  // What-if exists to show what a move would cost the solver; pricing it off numbers the
  // solver is not using makes it confidently wrong, which is worse than blank.
  const weights = data.detentionWeights;
  const overhead = data.regulationOverheadMin ?? 10;
  if (!weights?.length) {
    throw new Error(
      "plan.json carries no detentionWeights — what-if cannot price a move without " +
      "the solver's own weights. Regenerate it with scripts/run_pipeline.py.",
    );
  }

  let trafficCost = 0;
  let corridorBlocks = 0;

  for (const b of blocks) {
    const s = moves.get(b.id) ?? b.s;
    const e = s + durationOf(b, lengths);
    const day = Math.floor(s / MIN_PER_DAY);
    const lineIdx = b.line === "UP" ? 0 : 1;
    trafficCost += priceWindow(index, b.sec, lineIdx, s, e, weights, overhead).cost;
    if (isInsideCorridor(data.corridors, b.sec, day, s, e)) corridorBlocks += 1;
  }

  return {
    trafficCost: Math.round(trafficCost * 10) / 10,
    corridorBlocks,
    corridorAdherence: blocks.length ? corridorBlocks / blocks.length : 0,
    conflicted: conflictedIds.size,
  };
}

export function fmtClock(minute: number): string {
  const m = ((minute % MIN_PER_DAY) + MIN_PER_DAY) % MIN_PER_DAY;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export const SLOT_MIN = 15;

export function snap(minute: number): number {
  return Math.round(minute / SLOT_MIN) * SLOT_MIN;
}
