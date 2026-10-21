"""Backup authenticity, confidentiality, incomplete snapshots and extraction boundaries."""

import io
import json
import os
import tarfile

import pytest
from cryptography.exceptions import InvalidTag

from alap.adapters.ops.archive import (
    PAYLOADS,
    decrypt_verified,
    encrypt_stream,
    extract_tar,
    private_write,
    read_key,
    verify_bundle,
    write_manifest,
    write_tar,
)
from alap.adapters.ops.locking import maintenance_lock


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    key = os.urandom(32)
    entries = {
        name: encrypt_stream(io.BytesIO(b"private credential payload"), root / (name + ".aes"), key)
        for name in PAYLOADS
    }
    write_manifest(root, {"format": 1, "entries": entries}, key)
    return root, key


def test_encryption_roundtrip_and_private_material(bundle, tmp_path):
    root, key = bundle
    manifest = verify_bundle(root, key)
    target = tmp_path / "plain"
    decrypt_verified(root / "secrets.aes", target, manifest["entries"]["secrets"], key)
    assert target.read_bytes() == b"private credential payload"
    assert b"private credential" not in (root / "secrets.aes").read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert (root / "manifest.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["wrong_key", "manifest", "payload", "missing", "link"])
def test_invalid_backup_rejected_before_restore(bundle, tmp_path, failure):
    root, key = bundle
    if failure == "wrong_key":
        key = os.urandom(32)
    elif failure == "manifest":
        value = json.loads((root / "manifest.json").read_text())
        value["manifest"]["format"] = 99
        (root / "manifest.json").write_text(json.dumps(value))
    elif failure == "payload":
        path = root / "postgres.aes"
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    elif failure == "missing":
        (root / "artifacts.aes").unlink()
    else:
        target = root / "gateway.aes"
        other = tmp_path / "outside"
        target.rename(other)
        target.symlink_to(other)
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_bundle(root, key)


def test_failed_authentication_never_leaves_plaintext(bundle, tmp_path):
    root, key = bundle
    entry = verify_bundle(root, key)["entries"]["secrets"] | {"tag": "00" * 16}
    target = tmp_path / "untrusted"
    with pytest.raises(InvalidTag):
        decrypt_verified(root / "secrets.aes", target, entry, key)
    assert not target.exists()


@pytest.mark.parametrize("kind", ["parent", "absolute", "symlink", "hardlink", "fifo", "duplicate"])
def test_archive_escape_and_special_files_rejected(tmp_path, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        name = {"parent": "../outside", "absolute": "/outside"}.get(kind, "entry")
        item = tarfile.TarInfo(name)
        item.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "fifo": tarfile.FIFOTYPE,
        }.get(kind, tarfile.REGTYPE)
        item.linkname = "../../outside"
        archive.addfile(item, io.BytesIO())
        if kind == "duplicate":
            archive.addfile(item, io.BytesIO())
    buffer.seek(0)
    with pytest.raises(ValueError):
        extract_tar(buffer, tmp_path)
    assert not (tmp_path.parent / "outside").exists()


def test_normal_tree_roundtrip_and_no_overwrite(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "nested").mkdir(parents=True)
    (source / "nested/state").write_text("consistent snapshot")
    target.mkdir()
    buffer = io.BytesIO()
    write_tar(source, buffer)
    buffer.seek(0)
    extract_tar(buffer, target)
    assert (target / "nested/state").read_text() == "consistent snapshot"
    buffer.seek(0)
    with pytest.raises(ValueError):
        extract_tar(buffer, target)
    (source / "link").symlink_to(source / "nested/state")
    with pytest.raises(ValueError):
        write_tar(source, io.BytesIO())


def test_key_permissions_and_exclusive_maintenance(tmp_path):
    key = tmp_path / "key"
    private_write(key, os.urandom(32))
    assert len(read_key(key)) == 32
    with pytest.raises(FileExistsError):
        private_write(key, b"must not replace")
    key.chmod(0o644)
    with pytest.raises(ValueError):
        read_key(key)
    lock = tmp_path / "fresh-runtime" / "lock"
    with maintenance_lock(lock):
        with pytest.raises(ValueError):
            with maintenance_lock(lock):
                pass
