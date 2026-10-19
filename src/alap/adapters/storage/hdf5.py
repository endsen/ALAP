"""Local immutable HDF5 objects. Write/flush/fsync precedes metadata publication."""

import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

import h5py
import numpy as np

from alap.domain.rules import DomainError


class Hdf5Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, dataset_id):
        return hashlib.sha256(dataset_id.encode()).hexdigest() + ".h5"

    def _path(self, key):
        if (
            len(key) != 67
            or key[-3:] != ".h5"
            or any(c not in "0123456789abcdef" for c in key[:64])
        ):
            raise DomainError("INVALID_STORAGE_KEY", "Only generated object keys are accepted")
        path = self.root / key
        if path.is_symlink():
            raise DomainError("INVALID_STORAGE_KEY", "Symlink objects are forbidden")
        return path

    @contextmanager
    def _open(self, key):
        descriptor = os.open(self._path(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DomainError("ARTIFACT_INVALID", "Object must be a regular file")
            yield stream

    def put(self, key, artifact, metadata):
        target = self._path(key)
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        os.close(fd)
        try:
            with h5py.File(temporary, "w") as output:
                output.attrs["acquisition"] = json.dumps(metadata, sort_keys=True)
                for name in ("current_A", "voltage_V"):
                    output.create_dataset(
                        name, data=np.asarray(artifact[name], dtype="<f8"), track_times=False
                    )
                output.flush()
            with open(temporary, "rb") as stream:
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)  # Atomic, refuses to replace an existing object.
            except FileExistsError:
                pass  # Retry must verify the original object, never overwrite it.
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return self.verify(key, artifact, metadata)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def verify(self, key, artifact, metadata):
        try:
            # Verify one open file description; HDF5 cannot substitute a different object mid-read.
            with self._open(key) as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                stream.seek(0)
                with h5py.File(stream, "r") as source:
                    if set(source) != {"current_A", "voltage_V"}:
                        raise ValueError("unexpected dataset layout")
                    if json.loads(source.attrs["acquisition"]) != metadata:
                        raise ValueError("acquisition identity differs")
                    for name in ("current_A", "voltage_V"):
                        values = source[name][:]
                        expected = np.asarray(artifact[name], dtype="<f8")
                        if values.shape != expected.shape or not np.array_equal(values, expected):
                            raise ValueError("acquisition samples differ")
            return checksum
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError(
                "ARTIFACT_INVALID", "Missing, damaged or mismatched HDF5 object"
            ) from exc

    def read(self, key, checksum):
        try:
            with self._open(key) as stream:
                content = stream.read()
        except OSError as exc:
            raise DomainError("ARTIFACT_INVALID", "Committed object unavailable") from exc
        if hashlib.sha256(content).hexdigest() != checksum:
            raise DomainError("ARTIFACT_INVALID", "Checksum differs from committed manifest")
        return content
