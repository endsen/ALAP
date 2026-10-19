"""D10 bounded previews and authorization recheck."""

import io

import h5py
import numpy as np
import pytest

from alap.application.series import dataset_series
from alap.domain.rules import DomainError


class Reader:
    def __init__(self, x, y, changed=False):
        stream = io.BytesIO()
        with h5py.File(stream, "w") as file:
            file["current_A"] = x
            file["voltage_V"] = y
        self.content = stream.getvalue()
        self.calls = 0
        self.changed = changed

    def read(self, actor, identity):
        self.calls += 1
        return {"checksum_sha256": str(self.calls if self.changed else 1)}, self.content


def test_preview_bounded_and_endpoints_preserved():
    reader = Reader(np.arange(10001), np.arange(10001) * 2)
    result = dataset_series(reader, "actor", "dataset")
    assert len(result["points"]) == 2000
    assert result["points"][0] == [0, 0]
    assert result["points"][-1] == [10000, 20000]
    assert result["downsampled"] and result["total_points"] == 10001
    assert reader.calls == 2


@pytest.mark.parametrize(
    "x,y", [([0, 1], [0, float("nan")]), ([0], [1]), ([0, 1], [0, 1, 2]), ([[0, 1]], [[0, 1]])]
)
def test_invalid_preview_rejected(x, y):
    with pytest.raises(DomainError, match="Finite IV"):
        dataset_series(Reader(x, y), "actor", "dataset")


def test_preview_changed_during_read_rejected():
    with pytest.raises(DomainError, match="Reload data"):
        dataset_series(Reader([0, 1], [0, 1], changed=True), "actor", "dataset")
