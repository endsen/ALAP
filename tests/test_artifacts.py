"""Storage must not replace an acquisition or expose partial uploads."""

import os

import pytest

from alap.adapters.storage.hdf5 import Hdf5Store
from alap.domain.rules import DomainError


@pytest.fixture
def artifact():
    return {"current_A": [0, 1], "voltage_V": [0, 0.1]}


def test_immutable_storage_retry_and_mismatch(tmp_path, artifact):
    store = Hdf5Store(tmp_path)
    key = store.key("dataset")
    checksum = store.put(key, artifact, {"command_id": "one"})
    original = (tmp_path / key).read_bytes()
    assert store.put(key, artifact, {"command_id": "one"}) == checksum
    with pytest.raises(DomainError, match="ARTIFACT_INVALID"):
        store.put(key, artifact, {"command_id": "two"})
    assert (tmp_path / key).read_bytes() == original
    assert not list(tmp_path.glob(".upload-*"))


def test_interrupted_before_publish_leaves_no_visible_object(tmp_path, artifact, monkeypatch):
    store = Hdf5Store(tmp_path)
    key = store.key("dataset")

    def fail(*args):
        raise OSError("interrupted link")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail)
        with pytest.raises(OSError):
            store.put(key, artifact, {})
    assert list(tmp_path.iterdir()) == []
    store.put(key, artifact, {})


@pytest.mark.parametrize("key", ["../escape.h5", "/tmp/escape.h5", "x" * 64 + ".h5"])
def test_storage_keys_cannot_escape_root(tmp_path, key):
    with pytest.raises(DomainError, match="INVALID_STORAGE_KEY"):
        Hdf5Store(tmp_path).read(key, "a" * 64)


def test_symlink_object_rejected(tmp_path, artifact):
    store = Hdf5Store(tmp_path)
    key = store.key("dataset")
    (tmp_path / key).symlink_to("/etc/passwd")
    with pytest.raises(DomainError, match="INVALID_STORAGE_KEY"):
        store.put(key, artifact, {})
