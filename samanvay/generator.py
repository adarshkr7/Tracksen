"""Synthetic TMS / SMMS / TDMS feeds.

We hold no live railway operational data and this file does not pretend otherwise.
What it produces is a population of assets, defects and historical block records whose
*structure* matches the departmental systems and whose *distributions* are modelled on
published maintenance intervals and plausible failure behaviour.

Two quantities are ground truth and are deliberately kept out of every feature set:

    true_duration_min      what the work will actually take
    true_days_to_failure   when the asset would fail if left alone

The models are scored on how well they recover these from the observable features. On
deployment each generator here is replaced by its adapter and nothing above changes.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .domain import (
    Asset,
    AssetClass,
    BlockType,
    Department,
    Line,
    MachineType,
    MaintenanceTask,
)
from .network import SECTIONS, section_for_chainage

# --------------------------------------------------------------------------- #
# Work catalogue
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WorkSpec:
    """How one kind of job behaves: what it needs, and how long it really takes."""

    task_type: str
    asset_class: AssetClass
    block_type: BlockType
    base_min: int            # fixed set-up + clearance time
    # Marginal minutes per unit. Calibrated so one task is one block's worth of work,
    # not a whole campaign: a tamper makes roughly 500 m/h, a BCM 200 m/h. Getting
    # this wrong by an order of magnitude makes every job look like a mega block.
    per_unit_min: float
    qty_range: tuple[float, float]
    gang_range: tuple[int, int]
    machine: MachineType
    defect_prone: bool       # arises reactively as a defect, vs periodic schedule
    night_allowed: bool = True


WORK_CATALOGUE: list[WorkSpec] = [
    # ---- Engineering (TMS) ----
    WorkSpec("Rail flaw attention (USFD)", AssetClass.RAIL, BlockType.TRAFFIC,
             45, 6.0, (1, 4), (6, 12), MachineType.NONE, True),
    WorkSpec("Weld renewal", AssetClass.WELD, BlockType.TRAFFIC,
             40, 22.0, (1, 3), (6, 10), MachineType.NONE, True),
    WorkSpec("Rail renewal (short stretch)", AssetClass.RAIL, BlockType.TRAFFIC,
             60, 1.2, (20, 130), (12, 22), MachineType.RAIL_CUM_ROAD, False),
    WorkSpec("Through packing / tamping", AssetClass.RAIL, BlockType.TRAFFIC,
             55, 0.12, (300, 1200), (4, 8), MachineType.TAMPER, False, night_allowed=False),
    WorkSpec("Deep screening", AssetClass.RAIL, BlockType.TRAFFIC,
             90, 0.30, (120, 420), (10, 18), MachineType.BCM, False, night_allowed=False),
    WorkSpec("Turnout overhaul", AssetClass.TURNOUT, BlockType.TRAFFIC,
             70, 34.0, (1, 3), (8, 14), MachineType.UTV, False),

    # ---- Signal & Telecom (SMMS) ----
    WorkSpec("Point machine overhaul", AssetClass.POINT_MACHINE, BlockType.DISCONNECTION,
             50, 42.0, (1, 3), (3, 6), MachineType.NONE, True),
    WorkSpec("Track circuit tuning", AssetClass.TRACK_CIRCUIT, BlockType.DISCONNECTION,
             35, 26.0, (1, 4), (2, 4), MachineType.NONE, True),
    WorkSpec("Axle counter replacement", AssetClass.AXLE_COUNTER, BlockType.DISCONNECTION,
             40, 38.0, (1, 3), (2, 5), MachineType.NONE, True),
    WorkSpec("Signalling cable attention", AssetClass.TRACK_CIRCUIT, BlockType.DISCONNECTION,
             45, 0.45, (40, 260), (4, 8), MachineType.NONE, False),

    # ---- Traction Distribution (TDMS) ----
    WorkSpec("OHE mast / bracket attention", AssetClass.OHE_MAST, BlockType.POWER,
             45, 30.0, (1, 4), (4, 8), MachineType.TOWER_WAGON, True),
    WorkSpec("Contact wire renewal", AssetClass.CONTACT_WIRE, BlockType.POWER,
             65, 0.50, (60, 380), (6, 12), MachineType.TOWER_WAGON, False),
    WorkSpec("Insulator replacement", AssetClass.INSULATOR, BlockType.POWER,
             35, 19.0, (1, 6), (3, 6), MachineType.TOWER_WAGON, True),
    WorkSpec("Isolator servicing", AssetClass.ISOLATOR, BlockType.POWER,
             40, 27.0, (1, 3), (3, 5), MachineType.TOWER_WAGON, False),
]

SPEC_BY_TYPE = {w.task_type: w for w in WORK_CATALOGUE}

# Statutory / target interval in days, by work type. Overrun against these is what
# the optimiser is penalised for.
DUE_INTERVAL_DAYS = {
    "Rail flaw attention (USFD)": 7,
    "Weld renewal": 14,
    "Rail renewal (short stretch)": 60,
    "Through packing / tamping": 45,
    "Deep screening": 120,
    "Turnout overhaul": 90,
    "Point machine overhaul": 30,
    "Track circuit tuning": 21,
    "Axle counter replacement": 21,
    "Signalling cable attention": 60,
    "OHE mast / bracket attention": 30,
    "Contact wire renewal": 90,
    "Insulator replacement": 21,
    "Isolator servicing": 60,
}


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #

def generate_assets(rng: random.Random, per_km: float = 1.6) -> list[Asset]:
    """Populate the road with assets at plausible densities."""
    assets: list[Asset] = []
    counter = 0
    total_km = SECTIONS[-1].km_end

    n = int(total_km * per_km)
    classes = list(AssetClass)
    # Track assets outnumber signalling and OHE point assets along plain line.
    weights = [22, 18, 5, 7, 9, 5, 12, 9, 8, 5]

    for _ in range(n):
        km = round(rng.uniform(0.0, total_km), 3)
        sec = section_for_chainage(km)
        aclass = rng.choices(classes, weights=weights, k=1)[0]
        line = rng.choice([Line.UP, Line.DN])
        counter += 1
        assets.append(
            Asset(
                id=f"A{counter:05d}",
                asset_class=aclass,
                section_id=sec.id,
                line=line,
                chainage_km=km,
                age_years=round(rng.triangular(0.5, 38.0, 12.0), 1),
                gmt=round(rng.uniform(18.0, 62.0), 1),
                curvature_deg=round(max(0.0, rng.gauss(0.6, 1.1)), 2),
                gradient_permille=round(abs(rng.gauss(0.0, 3.2)), 2),
            )
        )
    return assets


# --------------------------------------------------------------------------- #
# Ground truth
# --------------------------------------------------------------------------- #

def _true_duration(rng: random.Random, spec: WorkSpec, quantity: float,
                   gang_size: int, night: bool, monsoon: bool) -> int:
    """What the job will actually take.

    Duration is driven by quantity and gang strength, then inflated by working at
    night and in the monsoon. The lognormal tail is the point: block over-run is not
    symmetric, which is why the scheduler reserves against P90 rather than the mean.
    """
    nominal_gang = (spec.gang_range[0] + spec.gang_range[1]) / 2.0
    gang_factor = (nominal_gang / max(1, gang_size)) ** 0.55

    base = spec.base_min + spec.per_unit_min * quantity
    base *= gang_factor
    if night:
        base *= 1.16          # lighting, reduced visibility
    if monsoon:
        base *= 1.13          # working conditions, material handling

    noise = rng.lognormvariate(0.0, 0.21)
    return int(max(20, round(base * noise)))


def _true_days_to_failure(rng: random.Random, asset: Asset, severity: int,
                          repeat_failures: int, is_defect: bool) -> float:
    """When this asset would fail if nobody attended to it.

    Severity dominates; age, tonnage, curvature and a history of repeat failures at
    the same kilometre all pull the date forward. Periodic (non-defect) work degrades
    far more slowly -- missing a tamping cycle is not the same as ignoring a rail flaw.
    """
    if not is_defect:
        scale = 240.0
    else:
        scale = {5: 9.0, 4: 26.0, 3: 62.0, 2: 130.0, 1: 260.0}[severity]

    stress = 1.0
    stress *= 1.0 + 0.016 * max(0.0, asset.age_years - 10.0)
    stress *= 1.0 + 0.009 * max(0.0, asset.gmt - 30.0)
    stress *= 1.0 + 0.11 * asset.curvature_deg
    stress *= 1.0 + 0.20 * repeat_failures

    return max(0.5, rng.expovariate(1.0) * scale / stress)


def _demanded_duration(rng: random.Random, true_min: int) -> int:
    """What the department writes on the block demand.

    Demands are round figures and systematically optimistic -- they are quoted against
    a good day with a full gang. Recovering the difference is the duration model's job.
    """
    biased = true_min * rng.uniform(0.74, 1.02)
    rounded = int(round(biased / 30.0) * 30)
    return max(30, min(rounded, 8 * 60))


def _is_monsoon(day_index: int, start_month: int = 9) -> bool:
    """Crude seasonal flag: June-September."""
    month = ((start_month - 1) + day_index // 30) % 12 + 1
    return month in (6, 7, 8, 9)


# --------------------------------------------------------------------------- #
# Task generation
# --------------------------------------------------------------------------- #

def _make_task(rng: random.Random, tid: str, asset: Asset, spec: WorkSpec,
               raised_day: int, repeat_failures: int, today: int = 0) -> MaintenanceTask:
    severity = (
        rng.choices([1, 2, 3, 4, 5], weights=[16, 26, 31, 19, 8], k=1)[0]
        if spec.defect_prone else
        rng.choices([1, 2, 3], weights=[55, 33, 12], k=1)[0]
    )
    quantity = round(rng.uniform(*spec.qty_range), 1)
    gang_size = rng.randint(*spec.gang_range)
    night = spec.night_allowed and rng.random() < 0.35
    monsoon = _is_monsoon(raised_day)

    true_min = _true_duration(rng, spec, quantity, gang_size, night, monsoon)
    due = raised_day + DUE_INTERVAL_DAYS[spec.task_type]

    return MaintenanceTask(
        id=tid,
        source_system=asset.department.source_system,
        department=asset.department,
        asset_id=asset.id,
        asset_class=asset.asset_class,
        section_id=asset.section_id,
        line=asset.line,
        chainage_km=asset.chainage_km,
        task_type=spec.task_type,
        block_type=spec.block_type,
        defect_severity=severity,
        is_defect=spec.defect_prone,
        raised_day=raised_day,
        due_day=due,
        demanded_duration_min=_demanded_duration(rng, true_min),
        gang_size=gang_size,
        machine=spec.machine,
        quantity=quantity,
        night_work_allowed=night,
        true_duration_min=true_min,
        true_days_to_failure=_true_days_to_failure(
            rng, asset, severity, repeat_failures, spec.defect_prone
        ),
    )


def _specs_for(asset: Asset) -> list[WorkSpec]:
    return [w for w in WORK_CATALOGUE if w.asset_class is asset.asset_class]


@dataclass
class HistoricalBlock:
    """A block that already ran. This is the training set for duration and cancellation."""

    task_type: str
    department: Department
    asset_class: AssetClass
    quantity: float
    gang_size: int
    machine: MachineType
    night_work: bool
    monsoon: bool
    demanded_duration_min: int
    defect_severity: int
    actual_duration_min: int
    was_cancelled: bool
    inside_corridor: bool
    section_id: str


@dataclass
class HistoricalDefect:
    """A past defect and what became of it -- the criticality training set.

    `failed_before_attention` is the label. `observed_days` is right-censored when the
    asset was attended before it failed, which is the normal case and the reason a
    plain regression on time-to-failure would be biased.
    """

    asset_class: AssetClass
    section_id: str
    chainage_km: float
    defect_severity: int
    is_defect: bool
    age_years: float
    gmt: float
    curvature_deg: float
    gradient_permille: float
    repeat_failures: int
    days_overdue_at_attention: int
    task_type: str
    failed_before_attention: bool
    observed_days: float
    censored: bool


@dataclass
class Dataset:
    assets: list[Asset]
    pending: list[MaintenanceTask]
    history_blocks: list[HistoricalBlock]
    history_defects: list[HistoricalDefect]
    repeat_failures: dict[tuple[str, int], int]


def generate_dataset(
    n_pending: int = 200,
    n_history_blocks: int = 900,
    n_history_defects: int = 1400,
    seed: int = 42,
) -> Dataset:
    """Produce the whole simulated estate: assets, a pending queue, and history."""
    rng = random.Random(seed)
    assets = generate_assets(rng)

    # How many times this kilometre has already given trouble.
    repeat_at_km: dict[tuple[str, int], int] = {}

    def repeats(asset: Asset) -> int:
        key = (asset.section_id, int(asset.chainage_km))
        return repeat_at_km.get(key, 0)

    def bump(asset: Asset) -> None:
        key = (asset.section_id, int(asset.chainage_km))
        repeat_at_km[key] = repeat_at_km.get(key, 0) + 1

    # ---- history: defects and their outcomes ----
    history_defects: list[HistoricalDefect] = []
    for _ in range(n_history_defects):
        asset = rng.choice(assets)
        specs = _specs_for(asset)
        if not specs:
            continue
        spec = rng.choice(specs)
        r = repeats(asset)
        severity = (
            rng.choices([1, 2, 3, 4, 5], weights=[16, 26, 31, 19, 8], k=1)[0]
            if spec.defect_prone else
            rng.choices([1, 2, 3], weights=[55, 33, 12], k=1)[0]
        )
        ttf = _true_days_to_failure(rng, asset, severity, r, spec.defect_prone)

        # When the defect actually received attention, historically.
        attention_delay = max(1.0, rng.lognormvariate(math.log(21.0), 0.85))
        overdue = int(attention_delay - DUE_INTERVAL_DAYS[spec.task_type])
        failed = ttf < attention_delay
        if failed:
            bump(asset)

        history_defects.append(
            HistoricalDefect(
                asset_class=asset.asset_class,
                section_id=asset.section_id,
                chainage_km=asset.chainage_km,
                defect_severity=severity,
                is_defect=spec.defect_prone,
                age_years=asset.age_years,
                gmt=asset.gmt,
                curvature_deg=asset.curvature_deg,
                gradient_permille=asset.gradient_permille,
                repeat_failures=r,
                days_overdue_at_attention=overdue,
                task_type=spec.task_type,
                failed_before_attention=failed,
                observed_days=min(ttf, attention_delay),
                censored=not failed,
            )
        )

    # ---- history: blocks that ran ----
    history_blocks: list[HistoricalBlock] = []
    for _ in range(n_history_blocks):
        asset = rng.choice(assets)
        specs = _specs_for(asset)
        if not specs:
            continue
        spec = rng.choice(specs)
        quantity = round(rng.uniform(*spec.qty_range), 1)
        gang = rng.randint(*spec.gang_range)
        night = spec.night_allowed and rng.random() < 0.35
        day = rng.randrange(0, 365)
        monsoon = _is_monsoon(day)
        severity = rng.randint(1, 5) if spec.defect_prone else rng.randint(1, 3)
        actual = _true_duration(rng, spec, quantity, gang, night, monsoon)
        inside_corridor = rng.random() < 0.62

        # Cancellation is driven by things the planner can see in advance: traffic
        # pressure outside the corridor, night working, monsoon, and machine-hungry
        # jobs whose plant may not turn up.
        p_cancel = 0.06
        if not inside_corridor:
            p_cancel += 0.11
        if night:
            p_cancel += 0.05
        if monsoon:
            p_cancel += 0.07
        if spec.machine is not MachineType.NONE:
            p_cancel += 0.06
        cancelled = rng.random() < min(0.6, p_cancel)

        history_blocks.append(
            HistoricalBlock(
                task_type=spec.task_type,
                department=asset.department,
                asset_class=asset.asset_class,
                quantity=quantity,
                gang_size=gang,
                machine=spec.machine,
                night_work=night,
                monsoon=monsoon,
                demanded_duration_min=_demanded_duration(rng, actual),
                defect_severity=severity,
                actual_duration_min=actual,
                was_cancelled=cancelled,
                inside_corridor=inside_corridor,
                section_id=asset.section_id,
            )
        )

    # ---- the pending queue we are asked to schedule ----
    pending: list[MaintenanceTask] = []
    tid = 0
    while len(pending) < n_pending:
        asset = rng.choice(assets)
        specs = _specs_for(asset)
        if not specs:
            continue
        spec = rng.choice(specs)
        tid += 1
        # Raised anywhere from seven weeks ago to today; some are already overdue,
        # which is exactly the backlog the system exists to work through.
        raised = -rng.randrange(0, 50)
        pending.append(
            _make_task(rng, f"T{tid:04d}", asset, spec, raised, repeats(asset))
        )

    return Dataset(
        assets=assets,
        pending=pending,
        history_blocks=history_blocks,
        history_defects=history_defects,
        repeat_failures=dict(repeat_at_km),
    )
