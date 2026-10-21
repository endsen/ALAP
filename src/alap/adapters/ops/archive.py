"""Authenticated streaming backup envelopes and strict regular-file tar archives."""

import hashlib
import hmac
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHUNK = 1024 * 1024
PAYLOADS = {"postgres", "nats", "gateway", "artifacts", "secrets"}


def private_write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_key(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("A private regular key file is required")
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("Expected a 256-bit backup key")
    return key


def derive(key, purpose):
    return hmac.digest(key, b"alap.backup.v1:" + purpose, "sha256")


def encrypt_stream(source, path, key):
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(derive(key, b"encryption")), modes.GCM(nonce)).encryptor()
    digest = hashlib.sha256()
    size = 0
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        while block := source.read(CHUNK):
            encrypted = cipher.update(block)
            output.write(encrypted)
            digest.update(encrypted)
            size += len(encrypted)
        final = cipher.finalize()
        output.write(final)
        digest.update(final)
        size += len(final)
        output.flush()
        os.fsync(output.fileno())
    return {
        "nonce": nonce.hex(),
        "tag": cipher.tag.hex(),
        "sha256": digest.hexdigest(),
        "size": size,
    }


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write_manifest(directory, manifest, key):
    # The manifest is the final completion marker. Incomplete directories cannot restore.
    value = {
        "manifest": manifest,
        "hmac": hmac.digest(derive(key, b"manifest"), canonical(manifest), "sha256").hex(),
    }
    private_write(Path(directory) / "manifest.json", canonical(value))


def verify_bundle(directory, key):
    directory = Path(directory)
    path = directory / "manifest.json"
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid backup manifest")
    value = json.loads(path.read_bytes())
    manifest = value["manifest"]
    expected = hmac.digest(derive(key, b"manifest"), canonical(manifest), "sha256").hex()
    if not hmac.compare_digest(expected, value["hmac"]):
        raise ValueError("Backup authentication failed")
    if manifest.get("format") != 1 or set(manifest.get("entries", {})) != PAYLOADS:
        raise ValueError("Unsupported or incomplete backup")
    for name, entry in manifest["entries"].items():
        path = directory / (name + ".aes")
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != entry["size"]:
            raise ValueError("Backup payload size/type mismatch")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("Backup payload checksum mismatch")
    return manifest


def decrypt_verified(source, target, entry, key):
    # Authenticate before callers may extract. Partial plaintext is private and deleted on failure.
    cipher = Cipher(
        algorithms.AES(derive(key, b"encryption")),
        modes.GCM(bytes.fromhex(entry["nonce"]), bytes.fromhex(entry["tag"])),
    ).decryptor()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output, Path(source).open("rb") as stream:
            while block := stream.read(CHUNK):
                output.write(cipher.update(block))
            output.write(cipher.finalize())
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


def write_tar(root, stream):
    root = Path(root)
    with tarfile.open(fileobj=stream, mode="w|") as archive:
        for path in sorted(root.rglob("*")):
            info = path.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError("Backup forbids links and special files")
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)


def extract_tar(stream, root):
    root = Path(root)
    if any(root.iterdir()):
        raise ValueError("Restore target must be empty")
    seen = set()
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or item.name != name.as_posix()
                or item.name in seen
                or not (item.isdir() or item.isfile())
            ):
                raise ValueError("Unsafe archive member")
            seen.add(item.name)
            # Never restore ownership or privilege bits from an archive.
            archive.extract(item, root, filter="data")
