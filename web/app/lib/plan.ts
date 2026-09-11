/** Shape of `out/plan.json`, as emitted by scripts/run_pipeline.py. */

export type Dept = "ENGG" | "S&T" | "TRD";
export type LineName = "UP" | "DN";

export interface Station { code: string; name: string; km: number }
export interface Section { id: string; a: string; b: string; km0: number; km1: number }

export interface Block {
  id: string;
  sec: number;          // index into sections[]
  line: LineName;
  day: number;
  s: number;            // start, minutes from horizon start
  e: number;            // end
  tasks: string[];
  depts: Dept[];
  types: string[];
  corridor: boolean;
  traffic: number;
  crit: number;
  why: string[];
  cancellation_risk?: number | null;
}

export interface Task {
  id: string;
  dept: Dept;
  type: string;
  section: string;
  line: LineName;
  km: number;
  severity: number;
  due_day: number;
  criticality: number | null;
  p50: number | null;
  p90: number | null;
  demanded: number;
  cancellation_risk: number | null;
  attribution: Record<string, number>;
  machine: string;
  night_work_allowed: boolean;
  /** Cox expectation of days to failure — prices the cost of deferring. */
  e_days: number | null;
  p_fail: number | null;
}

export interface Metrics {
  label: string;
  risk_retired_per_block_hour: number;
  tasks_scheduled: number;
  tasks_unscheduled: number;
  blocks_used: number;
  block_hours: number;
  criticality_retired: number;
  clubbing_ratio: number;
  clubbed_blocks: number;
  line_closures_saved: number;
  traffic_cost: number;
  traffic_cost_per_task: number;
  corridor_adherence: number;
  block_utilisation: number;
  overdue_task_days: number;
  expected_cancellations: number;
  unplanned_failures: number;
  critical_unplanned_failures: number;
}

/** [sectionIdx, line(0=UP,1=DN), classIdx, enterMin, exitMin, probability] */
export type PathRow = [number, number, number, number, number, number];
/** [sectionIdx, day, startMin, endMin] */
export type CorridorRow = [number, number, number, number];

export interface FoldScore {
  metric: string;
  mean: number;
  std: number;
  folds: number[];
  note: string;
}

export interface Validation {
  folds: number;
  seed: number;
  criticality: FoldScore[];
  duration: FoldScore[];
  cancellation: FoldScore[];
}

export interface MonthlyPlan {
  days: number;
  corridorMinutes: number;
  slotsTotal: number;
  slotsUsed: number;
  blocks: Block[];
  metrics: Metrics;
  extendedTasks: string[];
  backlogByDay: number[];
  solver: Record<string, number | string>;
}

export interface PlanData {
  meta: {
    plan_id?: string;
    revision?: number;
    content_hash?: string;
    state?: string;
    horizon_days: number;
    tasks: number;
    seed: number;
    weights: Record<string, number>;
    solver: Record<string, number | string>;
    /** Present on re-solve responses: placements the planner fixed. */
    pinned?: { block_id: string; start_min: number }[];
    /** Pins the solver refused, each with the reason. */
    rejectedPins?: string[];
  };
  model_checks: Record<string, Record<string, number>>;
  /** Present when the pipeline was run with --validate. All held-out. */
  validation: Validation | null;
  metrics: { baseline: Metrics; optimised: Metrics };
  stations: Station[];
  sections: Section[];
  corridors: CorridorRow[];
  trainClasses: string[];
  paths: PathRow[];
  blocks: Block[];
  baselineBlocks: Block[];
  tasks: Task[];
  /** Pricing constants, mirrored from the solver so client re-pricing matches. */
  detentionWeights: number[];
  regulationOverheadMin: number;
  maxBlocksPerDeptPerDay: number;
  machinePositioningMin: number;
  /** Present when the pipeline was run with --monthly. */
  monthly: MonthlyPlan | null;
}

export const DEPT_COLOR: Record<Dept, string> = {
  ENGG: "var(--engg)",
  "S&T": "var(--snt)",
  TRD: "var(--trd)",
};

export const DEPT_FULL: Record<Dept, string> = {
  ENGG: "Engineering (P.Way)",
  "S&T": "Signal & Telecom",
  TRD: "Traction Distribution",
};

export const DEPT_SYSTEM: Record<Dept, string> = {
  ENGG: "TMS",
  "S&T": "SMMS",
  TRD: "TDMS",
};

/** Muted enough that train paths stay behind the blocks, distinct enough to read. */
export const CLASS_COLOR = ["var(--accent)", "#6f6e69", "#9b988f", "#c2bfb4"];
export const CLASS_WIDTH = [1.4, 1.0, 0.8, 0.6];

export const MIN_PER_DAY = 1440;

export function hhmm(minuteOfDay: number): string {
  const m = ((minuteOfDay % MIN_PER_DAY) + MIN_PER_DAY) % MIN_PER_DAY;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export function dayLabel(day: number): string {
  return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day % 7];
}

export function fmt(n: number, digits = 0): string {
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
