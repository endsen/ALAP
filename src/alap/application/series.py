"""Bounded, checksum-verified IV preview; raw acquisition remains the download authority."""

import io

import h5py
import numpy as np

from alap.application.experiments import require
from alap.application.resource_ports import DatasetReader


def dataset_series(reader: DatasetReader, actor, identity, limit=2000):
    manifest, content = reader.read(actor, identity)
    with h5py.File(io.BytesIO(content), "r") as data:
        require(
            "current_A" in data and "voltage_V" in data,
            "PREVIEW_UNAVAILABLE",
            "IV channels required",
        )
        x, y = data["current_A"][:], data["voltage_V"][:]
    require(
        x.ndim == y.ndim == 1
        and len(x) == len(y)
        and 2 <= len(x) <= 100001
        and np.isfinite(x).all()
        and np.isfinite(y).all(),
        "PREVIEW_UNAVAILABLE",
        "Finite IV series required",
    )
    indices = np.linspace(0, len(x) - 1, min(limit, len(x)), dtype=int)
    # Recheck authorization after parsing too; no file location crosses this boundary.
    current, _ = reader.read(actor, identity)
    require(
        current["checksum_sha256"] == manifest["checksum_sha256"], "DATASET_CHANGED", "Reload data"
    )
    return {
        "dataset_id": identity,
        "x_label": "电流",
        "x_unit": "A",
        "y_label": "电压",
        "y_unit": "V",
        "points": [[float(x[i]), float(y[i])] for i in indices],
        "total_points": len(x),
        "downsampled": len(indices) < len(x),
        "checksum_sha256": manifest["checksum_sha256"],
    }
