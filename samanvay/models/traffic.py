"""The traffic cost surface: what an hour of this section is worth to operations.

Coaching traffic is deterministic -- it comes straight off the working timetable.
Goods is a forecast and carries a probability below one. So the cost of withdrawing a
section at a given hour is an *expectation* over the paths that would be affected,
weighted by what each class costs to detain.

This module answers two questions:

    cost_of_block(section, line, start, end)  -> expected weighted detention minutes
    consequence(section, line)                -> how much a failure here would hurt

The first prices a candidate placement. The second feeds the criticality score, and
is the reason a rail flaw under a premier path outranks the same flaw on a quiet loop.
"""

from __future__ import annotations

from collections import defaultdict

from ..domain import MINUTES_PER_DAY, Line, TrainClass, TrainPath

# A train that has to be regulated round a block does not lose only the minutes of
# overlap -- it loses the stop, the restart and the path behind it.
REGULATION_OVERHEAD_MIN = 10


class TrafficModel:
    """Indexes timetable and forecast paths, and prices windows against them."""

    def __init__(self, paths: list[TrainPath], horizon_days: int):
        self.horizon_days = horizon_days
        self._by_key: dict[tuple[str, Line, int], list[TrainPath]] = defaultdict(list)
        for p in paths:
            self._by_key[(p.section_id, p.line, p.day)].append(p)
        for v in self._by_key.values():
            v.sort(key=lambda p: p.enter_min)

        self._consequence_cache: dict[tuple[str, Line], float] = {}
        self._max_consequence = self._compute_consequence_scale()

    # ------------------------------------------------------------------ #
    # Pricing a candidate window
    # ------------------------------------------------------------------ #

    def paths_in_window(self, section_id: str, line: Line, start_min: int,
                        end_min: int) -> list[TrainPath]:
        """Every path whose occupation of this section overlaps the window."""
        hits: list[TrainPath] = []
        first_day = start_min // MINUTES_PER_DAY
        last_day = (end_min - 1) // MINUTES_PER_DAY
        for day in range(first_day, last_day + 1):
            for p in self._by_key.get((section_id, line, day), ()):
                if p.enter_min < end_min and start_min < p.exit_min:
                    hits.append(p)
        return hits

    def cost_of_block(self, section_id: str, line: Line, start_min: int,
                      end_min: int) -> float:
        """Expected weighted detention minutes caused by holding this window."""
        total = 0.0
        for p in self.paths_in_window(section_id, line, start_min, end_min):
            overlap = min(end_min, p.exit_min) - max(start_min, p.enter_min)
            if overlap <= 0:
                continue
            total += p.probability * p.train_class.detention_weight * (
                overlap + REGULATION_OVERHEAD_MIN
            )
        return round(total, 2)

    def trains_affected(self, section_id: str, line: Line, start_min: int,
                        end_min: int) -> int:
        """Head count, for reporting. Expected, so it is fractional in truth."""
        return len(self.paths_in_window(section_id, line, start_min, end_min))

    def fouls_premier(self, section_id: str, line: Line, start_min: int,
                      end_min: int) -> bool:
        """Whether this window would stand in front of a premier path.

        Rajdhani, Vande Bharat, Shatabdi and Duronto paths are protected: a division
        does not ask for a block across one and would not be given it. Pricing that as
        merely expensive is not the same thing -- a large enough saving elsewhere would
        buy it -- so windows that foul one are withheld from the solver entirely rather
        than offered at a high price.
        """
        return bool(self.premier_in_window(section_id, line, start_min, end_min))

    def premier_in_window(self, section_id: str, line: Line, start_min: int,
                          end_min: int) -> list[TrainPath]:
        """The protected paths a window would stand in front of.

        Returned rather than merely counted so a refusal can name the train. "Rejected:
        fouls a premier path" tells a planner nothing they can act on; "would stand in
        front of 12309 Rajdhani at 19:15" tells them where to drag it instead.
        """
        return [
            p for p in self.paths_in_window(section_id, line, start_min, end_min)
            if p.train_class is TrainClass.PREMIER
        ]

    # ------------------------------------------------------------------ #
    # The surface, for display and for coarse monthly planning
    # ------------------------------------------------------------------ #

    def hourly_surface(self, section_id: str, line: Line, day: int) -> list[float]:
        """24 values: the cost of taking a one-hour block starting at each hour."""
        base = day * MINUTES_PER_DAY
        return [
            self.cost_of_block(section_id, line, base + h * 60, base + (h + 1) * 60)
            for h in range(24)
        ]

    def cheapest_hours(self, section_id: str, line: Line, day: int,
                       k: int = 3) -> list[int]:
        surface = self.hourly_surface(section_id, line, day)
        return sorted(range(24), key=lambda h: surface[h])[:k]

    # ------------------------------------------------------------------ #
    # Consequence, for the criticality score
    # ------------------------------------------------------------------ #

    def _raw_consequence(self, section_id: str, line: Line) -> float:
        """Weighted daily traffic over this section -- the exposure of an asset here.

        Averaged across the horizon so that a single busy day does not dominate.
        """
        key = (section_id, line)
        if key in self._consequence_cache:
            return self._consequence_cache[key]

        total = 0.0
        for day in range(self.horizon_days):
            for p in self._by_key.get((section_id, line, day), ()):
                total += p.probability * p.train_class.detention_weight
        value = total / max(1, self.horizon_days)
        self._consequence_cache[key] = value
        return value

    def _compute_consequence_scale(self) -> float:
        keys = {(sid, line) for (sid, line, _) in self._by_key}
        if not keys:
            return 1.0
        return max(self._raw_consequence(sid, line) for sid, line in keys) or 1.0

    def consequence(self, section_id: str, line: Line) -> float:
        """Normalised to [0, 1] across the sections actually in this network."""
        return min(1.0, self._raw_consequence(section_id, line) / self._max_consequence)

    def premier_share(self, section_id: str, line: Line) -> float:
        """Fraction of weighted traffic that is premier -- used in explanations."""
        total = 0.0
        premier = 0.0
        for day in range(self.horizon_days):
            for p in self._by_key.get((section_id, line, day), ()):
                w = p.probability * p.train_class.detention_weight
                total += w
                if p.train_class.value == "PREMIER":
                    premier += w
        return premier / total if total else 0.0
