"""The two returns para 3.0 requires, and the ways they could quietly lie.

A return is a document somebody signs and sends upward. The failure that matters is not a
crash -- it is a return that renders cleanly, adds up, and describes a plan other than the
one it names. Two of those are possible here and both are tested: reporting the weekly
plan's blocks under monthly totals, and filling the deviation part with a model's forecast
where the DRM expects a record of what happened.
"""

from __future__ import annotations

import copy

import pytest

from samanvay.reports import RETURNS, monthly_gm_return, weekly_drm_return


@pytest.fixture(scope="module")
def payload(solved):
    return solved.payload


def test_the_weekly_return_carries_every_part_the_circular_names(payload):
    ret = weekly_drm_return(payload)
    headings = " ".join(p.heading.lower() for p in ret.parts)

    # para 3.0, in its own words
    assert "cancellation" in headings and "deviation" in headings
    assert "productivity of blocks given" in headings
    assert "overdue maintenance" in headings
    assert ret.authority == "Sr.DEN/Co-ord to DRM"


def test_the_return_says_it_is_a_recommendation_not_a_sanction(payload):
    """TRACKSEN never grants a block, and a document that looks like a sanction is the
    one place that distinction could be lost."""
    for renderer in ("to_text", "to_markdown"):
        body = getattr(weekly_drm_return(payload), renderer)()
        assert "Sanction rests with the competent authority" in body
        assert "not connected to any live railway system" in body


def test_deviation_is_not_answered_with_a_forecast(payload):
    """The DRM reads this part to learn which agreed blocks were not given.

    There is no execution feed, so the honest answer is that there is no answer. If a
    later change ever fills these rows from the cancellation model, this test should go
    red before the return reaches anybody.
    """
    part = next(p for p in weekly_drm_return(payload).parts
                if "cancellation" in p.heading.lower())
    agreed = dict(part.rows)["Blocks agreed and not given"]
    assert "no execution feed" in agreed
    assert "model prior" in " ".join(k for k, _ in part.rows)


def test_overdue_totals_match_the_plan_metrics(payload):
    part = next(p for p in weekly_drm_return(payload).parts
                if p.heading == "Overdue maintenance")
    reported = dict(part.rows)["Overdue task-days, total"].replace(",", "")
    assert int(reported) == payload["metrics"]["optimised"]["overdue_task_days"]


def test_the_monthly_return_reads_the_monthly_plan_not_the_weekly_one(payload):
    """The failure that does not throw.

    Both plans are in the same payload under different keys. A monthly return that reads
    `payload["blocks"]` renders perfectly and reports the wrong programme.
    """
    doc = copy.deepcopy(payload)

    # Day 29 exists only in the monthly plan: the weekly horizon is a handful of days, so
    # "programmed day 29" can be rendered from the monthly blocks and from nothing else.
    # The task list is trimmed to the five so the overdue table cannot fill up with others
    # and hide the difference.
    chosen = sorted(doc["tasks"], key=lambda t: t["due_day"])[:5]
    doc["tasks"] = chosen
    doc["monthly"] = {
        "days": 30,
        "corridorMinutes": 240,
        "slotsTotal": 900,
        "slotsUsed": 2,
        "blocks": [
            {"id": "M1", "sec": 0, "line": "UP", "day": 29,
             "tasks": [t["id"] for t in chosen],
             "depts": ["ENGG"], "types": ["TRAFFIC"], "corridor": True,
             "traffic": 0.0, "crit": 1.0, "why": []},
        ],
        "metrics": dict(doc["metrics"]["optimised"], overdue_task_days=4242),
        "extendedTasks": [t["id"] for t in chosen[:3]],
        "backlogByDay": [200] * 29 + [57],
        "solver": {},
    }

    ret = monthly_gm_return(doc)
    overdue = next(p for p in ret.parts if p.heading == "Overdue maintenance")
    assert dict(overdue.rows)["Overdue task-days, total"] == "4,242"

    body = ret.to_text()
    assert "programmed day 29" in body, (
        "the monthly return is describing blocks from some other plan"
    )
    assert ret.authority == "PCE to GM"


def test_the_extended_block_list_is_broken_down_by_department(payload):
    doc = copy.deepcopy(payload)
    doc["monthly"] = {
        "days": 30, "corridorMinutes": 240, "slotsTotal": 900, "slotsUsed": 0,
        "blocks": [], "metrics": doc["metrics"]["optimised"],
        "extendedTasks": [t["id"] for t in doc["tasks"][:6]],
        "backlogByDay": [10, 9], "solver": {},
    }
    part = next(p for p in monthly_gm_return(doc).parts
                if "extended" in p.heading.lower())
    rows = dict(part.rows)
    assert rows["Tasks that cannot fit one corridor"] == "6"
    by_dept = sum(int(v) for k, v in rows.items() if k.startswith("of which"))
    assert by_dept == 6


def test_a_missing_monthly_horizon_is_refused_by_name(payload):
    doc = copy.deepcopy(payload)
    doc["monthly"] = None
    with pytest.raises(ValueError) as exc:
        monthly_gm_return(doc)
    assert "--monthly" in str(exc.value)


def test_both_returns_are_registered(payload):
    assert set(RETURNS) == {"weekly", "monthly"}
    assert RETURNS["weekly"] is weekly_drm_return
