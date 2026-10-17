"""Pure observed-value window evaluation; target values are never treated as readback."""

from datetime import datetime
from math import isfinite

from alap.domain.rules import DomainError


def check_stable(condition: dict, samples: list[dict], now: datetime) -> None:
    if not samples or now.utcoffset() is None:
        raise DomainError("READBACK_MISSING", "Observed samples and aware clock required")
    previous = None
    for sample in samples:
        observed = datetime.fromisoformat(sample["observed_at"])
        value = sample["value"]
        if (
            observed.utcoffset() is None
            or observed > now
            or sample["quality"] != "GOOD"
            or sample["resource_id"] != condition["resource_id"]
            or sample["quantity"] != condition["quantity"]
            or sample["unit"] != condition["unit"]
            or type(value) not in (float, int)
            or not isfinite(value)
            or abs(value - condition["target"]) > condition["tolerance"]
        ):
            raise DomainError(
                "READBACK_INVALID", "Readback identity, quality, time or tolerance failed"
            )
        if previous:
            elapsed = (observed - previous[0]).total_seconds()
            if elapsed <= 0 or elapsed > condition["max_age_s"]:
                raise DomainError("READBACK_GAP", "Samples must be ordered with bounded gaps")
            if abs(value - previous[1]) / elapsed > condition["max_slope_per_s"]:
                raise DomainError("READBACK_UNSTABLE", "Observed slope exceeds limit")
        previous = observed, value
    first = datetime.fromisoformat(samples[0]["observed_at"])
    if (now - previous[0]).total_seconds() > condition["max_age_s"] or (
        previous[0] - first
    ).total_seconds() < condition["min_duration_s"]:
        raise DomainError("READBACK_STALE", "Fresh, complete observed window required")
