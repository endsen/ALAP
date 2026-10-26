"""Explicit simulation-only loss policy; never a hardware shutdown prescription."""

from dataclasses import dataclass

from alap.domain.rules import DomainError


@dataclass(frozen=True)
class SimulationLossPolicy:
    version: str
    timeout_s: float
    devices: dict

    def __post_init__(self):
        import math

        if not isinstance(self.version, str) or not self.version.strip():
            raise DomainError("EDGE_POLICY_INVALID", "Version required")
        if (
            type(self.timeout_s) not in (float, int)
            or not math.isfinite(self.timeout_s)
            or not 0.1 <= self.timeout_s <= 60
        ):
            raise DomainError("EDGE_POLICY_INVALID", "Simulation timeout must be 0.1..60 seconds")
        if self.devices != {
            "sim-smu": "zero_output",
            "sim-magnet": "hold",
            "sim-temp": "hold",
        }:
            raise DomainError(
                "EDGE_POLICY_INVALID", "Explicit device-specific simulation policy required"
            )
        # A frozen dataclass alone does not freeze its nested dictionary.
        from types import MappingProxyType

        object.__setattr__(self, "devices", MappingProxyType(dict(self.devices)))

    def document(self):
        return {"version": self.version, "timeout_s": self.timeout_s, "devices": dict(self.devices)}
