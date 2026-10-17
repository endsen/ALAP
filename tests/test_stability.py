"""Measured stability is a time-series invariant, not a target-value comparison."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from alap.domain.rules import DomainError
from alap.domain.stability import check_stable

NOW = datetime(2026, 10, 18, tzinfo=UTC)
CONDITION = {
    "resource_id": "temp",
    "quantity": "temperature",
    "unit": "K",
    "target": 295.0,
    "tolerance": 0.1,
    "max_slope_per_s": 0.01,
    "min_duration_s": 2,
    "max_age_s": 1,
}


def samples():
    return [
        {
            "resource_id": "temp",
            "quantity": "temperature",
            "unit": "K",
            "value": 295.0,
            "quality": "GOOD",
            "observed_at": (NOW - timedelta(seconds=i)).isoformat(),
        }
        for i in [2, 1, 0]
    ]


def test_complete_fresh_window():
    check_stable(CONDITION, samples(), NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_id", "other"),
        ("quantity", "field"),
        ("unit", "C"),
        ("quality", "BAD"),
        ("value", True),
        ("value", float("nan")),
        ("value", float("inf")),
        ("value", 296),
        ("observed_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("observed_at", "2026-10-18T00:00:00"),
    ],
)
def test_wrong_observed_values_are_rejected(field, value):
    values = samples()
    values[-1][field] = value
    with pytest.raises(DomainError):
        check_stable(CONDITION, values, NOW)


@pytest.mark.parametrize("change", ["short", "stale", "gap", "slope", "duplicate"])
def test_window_guards(change):
    values = samples()
    now = NOW
    condition = deepcopy(CONDITION)
    if change == "short":
        values = values[1:]
    elif change == "stale":
        now += timedelta(seconds=2)
    elif change == "gap":
        values.pop(1)
    elif change == "slope":
        values[-1]["value"] = 295.05
    else:
        values[-1]["observed_at"] = values[-2]["observed_at"]
    with pytest.raises(DomainError):
        check_stable(condition, values, now)
