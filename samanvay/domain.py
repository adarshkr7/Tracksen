"""Unified Task Model and the section topology it is keyed against.

Everything in SAMANVAY hangs off one idea: a maintenance task from any of the three
departmental systems is written in the same coordinates -- (section, line, chainage).
Once that holds, "is this S&T fault near that OHE job?" is arithmetic rather than a
phone call between two JEs, and clubbing becomes something a solver can find.

Time is carried as integer minutes from the start of the planning horizon. CP-SAT
wants integers, and keeping one representation end-to-end avoids a whole class of
timezone and rounding bugs. Use `Horizon` to move between minutes and wall clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


# --------------------------------------------------------------------------- #
# Departments and the systems they plan in
# --------------------------------------------------------------------------- #

class Department(str, Enum):
    """The three departments contending for the same block sections."""

    ENGINEERING = "ENGG"   # P.Way   -- plans in TMS
    SIGNAL = "S&T"         # Signal & Telecom -- plans in SMMS
    TRACTION = "TRD"       # Traction Distribution -- plans in TDMS

    @property
    def source_system(self) -> str:
        return {"ENGG": "TMS", "S&T": "SMMS", "TRD": "TDMS"}[self.value]


class BlockType(str, Enum):
    """What is actually withdrawn from service.

    These are not interchangeable. A disconnection takes signalling out of service
    but leaves the line; a power block de-energises the OHE. The nesting rules in
    the optimiser depend on telling them apart.
    """

    TRAFFIC = "TRAFFIC"            # line handed over to Engineering
    DISCONNECTION = "DISCONN"      # signalling withdrawn from service
    POWER = "POWER"                # OHE de-energised


class Line(str, Enum):
    UP = "UP"
    DN = "DN"


class AssetClass(str, Enum):
    RAIL = "RAIL"
    WELD = "WELD"
    TURNOUT = "TURNOUT"
    POINT_MACHINE = "POINT_MACHINE"
    TRACK_CIRCUIT = "TRACK_CIRCUIT"
    AXLE_COUNTER = "AXLE_COUNTER"
    OHE_MAST = "OHE_MAST"
    CONTACT_WIRE = "CONTACT_WIRE"
    INSULATOR = "INSULATOR"
    ISOLATOR = "ISOLATOR"

    @property
    def department(self) -> Department:
        return _ASSET_DEPT[self]


_ASSET_DEPT = {
    AssetClass.RAIL: Department.ENGINEERING,
    AssetClass.WELD: Department.ENGINEERING,
    AssetClass.TURNOUT: Department.ENGINEERING,
    AssetClass.POINT_MACHINE: Department.SIGNAL,
    AssetClass.TRACK_CIRCUIT: Department.SIGNAL,
    AssetClass.AXLE_COUNTER: Department.SIGNAL,
    AssetClass.OHE_MAST: Department.TRACTION,
    AssetClass.CONTACT_WIRE: Department.TRACTION,
    AssetClass.INSULATOR: Department.TRACTION,
    AssetClass.ISOLATOR: Department.TRACTION,
}


class MachineType(str, Enum):
    """Plant that must be positioned, and cannot be in two places at once."""

    NONE = "NONE"
    TAMPER = "TAMPER"          # track tamping machine
    BCM = "BCM"                # ballast cleaning machine
    UTV = "UTV"                # utility vehicle
    TOWER_WAGON = "TOWER_WAGON"  # OHE work
    RAIL_CUM_ROAD = "RCRV"


# --------------------------------------------------------------------------- #
# Topology
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Station:
    code: str
    name: str
    km: float


@dataclass(frozen=True)
class BlockSection:
    """The unit of exclusivity: one section, one line, one occupant at a time."""

    id: str
    from_station: str
    to_station: str
    km_start: float
    km_end: float

    @property
    def length_km(self) -> float:
        return round(self.km_end - self.km_start, 3)

    def contains(self, chainage_km: float) -> bool:
        return self.km_start <= chainage_km <= self.km_end


@dataclass(frozen=True)
class Asset:
    """A physical thing at a kilometre, owned by exactly one department."""

    id: str
    asset_class: AssetClass
    section_id: str
    line: Line
    chainage_km: float
    age_years: float
    gmt: float                 # gross million tonnes per annum over this asset
    curvature_deg: float       # 0.0 on straight track
    gradient_permille: float

    @property
    def department(self) -> Department:
        return self.asset_class.department


# --------------------------------------------------------------------------- #
# The Unified Task Model
# --------------------------------------------------------------------------- #

@dataclass
class MaintenanceTask:
    """One pending job, normalised out of TMS / SMMS / TDMS.

    `demanded_duration_min` is what the department asked for -- typically a round
    figure. `true_duration_min` is what the work will actually take; it exists only
    in simulation and is never visible to the planner or the models. The duration
    model's job is to recover a useful estimate of it from the features.
    """

    id: str
    source_system: str              # TMS | SMMS | TDMS
    department: Department
    asset_id: str
    asset_class: AssetClass
    section_id: str
    line: Line
    chainage_km: float

    task_type: str                  # human-readable work description
    block_type: BlockType
    defect_severity: int            # 1 (routine) .. 5 (imminent failure)
    is_defect: bool                 # True = reactive defect, False = periodic schedule

    raised_day: int                 # day index from horizon start (may be negative)
    due_day: int                    # statutory / target completion day
    demanded_duration_min: int      # what the department demanded

    gang_size: int
    machine: MachineType
    quantity: float                 # metres, count, or spans -- unit varies by task_type
    night_work_allowed: bool

    # Simulation ground truth -- never fed to a model or shown to a planner.
    true_duration_min: int = 0
    true_days_to_failure: float = 9_999.0

    # Populated by the model layer.
    criticality: float | None = None
    p50_duration_min: int | None = None
    p90_duration_min: int | None = None
    cancellation_risk: float | None = None
    attribution: dict[str, float] = field(default_factory=dict)

    def days_overdue(self, today: int = 0) -> int:
        """Positive when past the due date. Negative means still in hand."""
        return today - self.due_day

    @property
    def requires_power_block(self) -> bool:
        return self.block_type is BlockType.POWER or self.asset_class in (
            AssetClass.OHE_MAST,
            AssetClass.CONTACT_WIRE,
            AssetClass.INSULATOR,
            AssetClass.ISOLATOR,
        )

    @property
    def requires_disconnection(self) -> bool:
        return self.block_type is BlockType.DISCONNECTION


# --------------------------------------------------------------------------- #
# Traffic
# --------------------------------------------------------------------------- #

class TrainClass(str, Enum):
    """Ordered loosely by the cost of delaying one."""

    PREMIER = "PREMIER"      # Rajdhani / Vande Bharat / Shatabdi
    MAIL_EXP = "MAIL_EXP"
    PASSENGER = "PASSENGER"
    GOODS = "GOODS"

    @property
    def detention_weight(self) -> float:
        """Relative cost of one detained minute, premier traffic as the datum."""
        return {"PREMIER": 4.0, "MAIL_EXP": 2.5, "PASSENGER": 1.5, "GOODS": 1.0}[self.value]


@dataclass(frozen=True)
class TrainPath:
    """One train's occupation of one section, as read from the working timetable.

    Coaching paths are deterministic and come straight off the WTT. Goods paths are
    forecast, and carry a probability -- which is exactly why the traffic cost of an
    hour is an expectation rather than a count.
    """

    train_no: str
    train_class: TrainClass
    section_id: str
    line: Line
    day: int
    enter_min: int          # minutes from horizon start
    exit_min: int
    probability: float = 1.0   # < 1.0 for forecast goods paths


@dataclass(frozen=True)
class CorridorWindow:
    """The pre-defined maintenance corridor in the master chart.

    Blocks placed inside it are cheap by construction -- the paths were already kept
    clear. Placement outside is permitted but priced accordingly.
    """

    section_id: str
    day: int
    start_min: int
    end_min: int


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

@dataclass
class ScheduledBlock:
    """A recommended block. Not a sanctioned one -- that decision stays with a person."""

    id: str
    section_id: str
    line: Line
    day: int
    start_min: int
    end_min: int
    task_ids: list[str]
    departments: list[Department]
    block_types: list[BlockType]
    inside_corridor: bool
    traffic_cost: float
    criticality_retired: float
    reasons: list[str] = field(default_factory=list)

    @property
    def duration_min(self) -> int:
        return self.end_min - self.start_min

    @property
    def is_clubbed(self) -> bool:
        return len(set(self.departments)) > 1


@dataclass
class Plan:
    """A full horizon of recommended blocks, plus what could not be fitted."""

    blocks: list[ScheduledBlock]
    unscheduled_task_ids: list[str]
    horizon_days: int
    label: str = "plan"

    @property
    def clubbed_blocks(self) -> list[ScheduledBlock]:
        return [b for b in self.blocks if b.is_clubbed]


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #

MINUTES_PER_DAY = 24 * 60
SLOT_MIN = 15  # planning granularity for the weekly horizon


@dataclass(frozen=True)
class Horizon:
    """Maps integer minutes to wall clock, and back."""

    start_date: dt.date
    days: int

    @property
    def total_minutes(self) -> int:
        return self.days * MINUTES_PER_DAY

    def to_datetime(self, minute: int) -> dt.datetime:
        return dt.datetime.combine(self.start_date, dt.time()) + dt.timedelta(minutes=minute)

    def day_of(self, minute: int) -> int:
        return minute // MINUTES_PER_DAY

    def minute_of_day(self, minute: int) -> int:
        return minute % MINUTES_PER_DAY

    def hhmm(self, minute: int) -> str:
        mod = self.minute_of_day(minute)
        return f"{mod // 60:02d}:{mod % 60:02d}"

    def label(self, minute: int) -> str:
        d = self.to_datetime(minute)
        return d.strftime("%a %d %b %H:%M")


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open interval overlap. Touching intervals do not overlap."""
    return a_start < b_end and b_start < a_end


def group_by_section(tasks: Iterable[MaintenanceTask]) -> dict[str, list[MaintenanceTask]]:
    out: dict[str, list[MaintenanceTask]] = {}
    for t in tasks:
        out.setdefault(t.section_id, []).append(t)
    return out
