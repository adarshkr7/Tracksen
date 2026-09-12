/** Shape of `out/plan.json`, as emitted by scripts/run_pipeline.py. */

export type Dept = "ENGG" | "S&T" | "TRD";
export type LineName = "UP" | "DN";

export interface Station {
  code: string; name: string; km: number;
  /** Set when the station is a junction; describes what joins there. */
  junction?: string | null;
}

/** A line joining or leaving the corridor at a junction. */
export interface Branch {
  junction: string; name: string; side: "N" | "S" | string; note: string;
  modelled?: boolean;
}
export interface Section {
  id: string; a: string; b: string; km0: number; km1: number;
  /** Which route the section belongs to; chainage is measured per route. */
  route?: string;
}

/** A route: the main line, or a modelled branch with its own chainage origin. */
export interface RouteInfo {
  id: string; name: string; lengthKm: number; stations: Station[];
}

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

/** [sectionIdx, line(0=UP,1=DN), classIdx, enterMin, exitMin, probability, trainIdx] */
export type PathRow = [number, number, number, number, number, number, number];

/**
 * [trainNo, name, provenance] — the roster the paths index into.
 *
 * Identity is interned rather than repeated on every path: one train occupies dozens of
 * sections, and carrying its number and name on each would be most of plan.json.
 */
export type TrainRow = [string, string, number];

/**
 * How a train came to be in the plan. Shown on the path tooltip, because the three are
 * not equally trustworthy and the chart should not let a forecast read as a booking.
 */
export const PROVENANCE = [
  {
    label: "Booked service",
    note: "Real train; times approximate, not from the WTT",
    color: "var(--ok)",
  },
  {
    label: "Representative service",
    note: "Stands in for stopping traffic; number not individually verified",
    color: "var(--info)",
  },
  {
    label: "Forecast path",
    note: "Goods is not booked — this path carries the chance it runs at all",
    color: "var(--ink-3)",
  },
  {
    label: "Imported from NTES",
    note: "Number, time and running days as published — not an estimate",
    color: "var(--ok)",
  },
  {
    label: "Published open data",
    note: "Booked time as published, of that dataset's vintage — not an estimate",
    color: "var(--ok)",
  },
] as const;
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
  branches?: Branch[];
  routes?: RouteInfo[];
  sections: Section[];
  corridors: CorridorRow[];
  trainClasses: string[];
  /** Which coaching timetable is in force, and whether its times are published. */
  timetable?: { file: string; imported: boolean; services: number };
  trains: TrainRow[];
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

/** Short form for dense tables and chart legends. */
export const DEPT_NAME: Record<Dept, string> = {
  ENGG: "Engineering", "S&T": "S&T", TRD: "Traction",
};

/** The block each department takes when it occupies a section. */
export const DEPT_BLOCK: Record<Dept, string> = {
  ENGG: "Traffic block", "S&T": "Disconnection", TRD: "Power block",
};

export const DEPT_SYSTEM: Record<Dept, string> = {
  ENGG: "TMS",
  "S&T": "SMMS",
  TRD: "TDMS",
};

/** Muted enough that train paths stay behind the blocks, distinct enough to read. */
export const CLASS_COLOR = ["var(--rail)", "#42566b", "#8496a8", "#b9c4cf"];

/**
 * Hairlines. Around 250 trains cross the main line on a working day, and at any width
 * that reads comfortably on its own they merge into a wash in the busy hours — you
 * cannot see a block through them, let alone pick one out. Drawn thin, the chart stays
 * legible and an individual path is recovered by hovering it instead.
 */
export const CLASS_WIDTH = [0.9, 0.65, 0.5, 0.35];
export const CLASS_LABEL = ["Premier", "Mail / Express", "Passenger", "Goods"];

export const MIN_PER_DAY = 1440;

/** Roles the approval route recognises; the backend enforces what each may do. */
export const ROLES = [
  "JE", "Sr.DEN", "Sr.DSTE", "Sr.DEE/TrD", "Sr.DOM", "DRM", "Viewer",
] as const;

/** Which department each head may concur for — mirrors CONCURRENCE_AUTHORITY. */
export const ROLE_DEPARTMENT: Record<string, Dept | undefined> = {
  "Sr.DEN": "ENGG", "Sr.DSTE": "S&T", "Sr.DEE/TrD": "TRD",
};

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
