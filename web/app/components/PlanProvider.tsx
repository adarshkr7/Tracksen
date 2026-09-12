"use client";

/**
 * One fetch of the plan, shared by every screen.
 *
 * The plan is ~700 KB and every page needs some slice of it, so it is loaded once here
 * and read from context. Derived views the pages ask for repeatedly — task lookup,
 * criticality bands, department rollups — are memoised alongside it rather than
 * recomputed per screen.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { health } from "../lib/api";
import { Block, Dept, PlanData, Task } from "../lib/plan";

export type Band = "critical" | "high" | "medium" | "low";

export function band(criticality: number | null): Band {
  const c = criticality ?? 0;
  if (c >= 70) return "critical";
  if (c >= 45) return "high";
  if (c >= 20) return "medium";
  return "low";
}

export const BAND_LABEL: Record<Band, string> = {
  critical: "Critical", high: "High", medium: "Medium", low: "Low",
};
export const BAND_COLOR: Record<Band, string> = {
  critical: "var(--crit)", high: "var(--warn)",
  medium: "var(--info)", low: "var(--ok)",
};

interface Ctx {
  plan: PlanData | null;
  error: string | null;
  loading: boolean;
  apiUp: boolean;
  /** Applies a solver response, unless it describes a different network. */
  setPlan: (p: PlanData) => void;
  /** Set when a response was refused for describing a different network. */
  topologyMismatch: string | null;
  clearMismatch: () => void;
  /** Task lookup by id. */
  taskById: Map<string, Task>;
  /** Day a task is scheduled on in the weekly plan, if it is. */
  scheduledDay: Map<string, number>;
  /** Tasks ranked by criticality, highest first. */
  ranked: Task[];
  counts: {
    tasks: number;
    scheduled: number;
    deferred: number;
    critical: number;
    overdue: number;
    blocks: number;
    clubbed: number;
    byDept: Record<Dept, number>;
  };
}

const PlanCtx = createContext<Ctx | null>(null);

export function usePlan(): Ctx {
  const c = useContext(PlanCtx);
  if (!c) throw new Error("usePlan must be used inside PlanProvider");
  return c;
}

export default function PlanProvider({ children }: { children: React.ReactNode }) {
  const [plan, setPlanState] = useState<PlanData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiUp, setApiUp] = useState(false);
  const [topologyMismatch, setTopologyMismatch] = useState<string | null>(null);

  useEffect(() => {
    fetch("/plan.json")
      .then((r) => {
        if (!r.ok) throw new Error(`plan.json ${r.status}`);
        return r.json();
      })
      .then((d: PlanData) => setPlanState(d))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));

    health().then((h) => setApiUp(Boolean(h?.ok)));
  }, []);

  /**
   * Adopt a solver response only if it is the same network.
   *
   * The service builds its planning session once and reuses it, so a process left
   * running across a change to the topology keeps serving the old division. Swapping
   * the whole plan on that response would silently move the user to a different
   * railway -- which is worse than refusing, because nothing on screen would say so.
   */
  const setPlan = useCallback((p: PlanData) => {
    setPlanState((prev) => {
      if (!prev) return p;
      const before = prev.sections.map((s) => s.id).join("|");
      const after = p.sections.map((s) => s.id).join("|");
      if (before !== after) {
        setTopologyMismatch(
          `The solver returned a plan for a different network (${p.stations[0]?.code}` +
          `–${p.stations[p.stations.length - 1]?.code}, ${p.sections.length} sections) ` +
          `than the one loaded (${prev.stations[0]?.code}` +
          `–${prev.stations[prev.stations.length - 1]?.code}, ${prev.sections.length}). ` +
          "The service is holding a stale planning session — restart scripts/serve.py.",
        );
        return prev;
      }
      setTopologyMismatch(null);
      return p;
    });
  }, []);

  const clearMismatch = useCallback(() => setTopologyMismatch(null), []);

  const derived = useMemo(() => {
    const taskById = new Map<string, Task>();
    const scheduledDay = new Map<string, number>();
    const byDept = { ENGG: 0, "S&T": 0, TRD: 0 } as Record<Dept, number>;

    if (!plan) {
      return {
        taskById, scheduledDay, ranked: [] as Task[],
        counts: {
          tasks: 0, scheduled: 0, deferred: 0, critical: 0, overdue: 0,
          blocks: 0, clubbed: 0, byDept,
        },
      };
    }

    for (const t of plan.tasks) {
      taskById.set(t.id, t);
      byDept[t.dept] = (byDept[t.dept] ?? 0) + 1;
    }
    for (const b of plan.blocks) for (const t of b.tasks) scheduledDay.set(t, b.day);

    const ranked = [...plan.tasks].sort(
      (a, b) => (b.criticality ?? 0) - (a.criticality ?? 0),
    );

    return {
      taskById,
      scheduledDay,
      ranked,
      counts: {
        tasks: plan.tasks.length,
        scheduled: plan.metrics.optimised.tasks_scheduled,
        deferred: plan.metrics.optimised.tasks_unscheduled,
        critical: plan.tasks.filter((t) => band(t.criticality) === "critical").length,
        // due_day is relative to the horizon start, so anything at or before 0 is late.
        overdue: plan.tasks.filter((t) => t.due_day <= 0).length,
        blocks: plan.blocks.length,
        clubbed: plan.blocks.filter((b: Block) => b.depts.length > 1).length,
        byDept,
      },
    };
  }, [plan]);

  return (
    <PlanCtx.Provider
      value={{ plan, error, loading, apiUp, setPlan, topologyMismatch,
               clearMismatch, ...derived }}>
      {children}
    </PlanCtx.Provider>
  );
}
