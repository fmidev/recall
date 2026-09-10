#!/usr/bin/env python3
"""Create validated, private PostgreSQL backups without starting any services."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid


ARCHIVE_PATTERN = re.compile(r"recall-auto-\d{8}T\d{12}Z-[0-9a-f]{32}\.dump")
LOCK_NAME = ".recall-backup.lock"


class BackupError(Exception):
    pass


def positive_integer(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "retention must be a positive integer"
        ) from exc
    if number < 1:
        raise argparse.ArgumentTypeError("retention must be a positive integer")
    return number


@contextmanager
def private_directory(path):
    """Walk with directory descriptors so even ancestor symlinks are rejected."""
    absolute = os.path.abspath(path)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(absolute).parts[1:]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise BackupError(
                "backup directory must be owned by the current user and private "
                "(chmod 700)"
            )
        yield descriptor
    finally:
        os.close(descriptor)


def require_regular(info, name):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
    ):
        raise BackupError(f"refusing unsafe backup entry: {name}")


@contextmanager
def backup_lock(directory):
    descriptor = os.open(
        LOCK_NAME,
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
        dir_fd=directory,
    )
    try:
        require_regular(os.fstat(descriptor), LOCK_NAME)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError(
                "another backup is running (backup lock is busy)"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def run_command(operation, command, **kwargs):
    result = subprocess.run(command, stderr=subprocess.PIPE, check=False, **kwargs)
    if result.returncode:
        details = result.stderr.decode("utf-8", errors="replace").strip()
        raise BackupError(
            f"{operation} failed "
            f"(exit {result.returncode}): {details or 'no diagnostic output'}"
        )


def checksum(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def owned_backups(directory):
    """Only complete, strictly named archive/checksum pairs qualify for pruning."""
    entries = set(os.listdir(directory))
    pairs = []
    for name in sorted(entries):
        archive = name.removesuffix(".sha256")
        if not ARCHIVE_PATTERN.fullmatch(archive):
            continue
        require_regular(os.stat(name, dir_fd=directory, follow_symlinks=False), name)
        if name != archive or name + ".sha256" not in entries:
            continue
        sidecar = name + ".sha256"
        descriptor = os.open(
            sidecar, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            require_regular(os.fstat(stream.fileno()), sidecar)
            contents = stream.read(512)
        if not re.fullmatch(
            rb"[0-9a-f]{64}  " + re.escape(name.encode("ascii")) + rb"\n", contents
        ):
            raise BackupError(f"invalid checksum sidecar: {sidecar}")
        pairs.append(name)
    return pairs


def prune(directory, retain, fresh):
    # Always retain this run's new archive, even if the system clock moved back.
    older = [name for name in owned_backups(directory) if name != fresh]
    for name in older[: max(0, len(older) - retain + 1)]:
        for entry in (name, name + ".sha256"):
            require_regular(
                os.stat(entry, dir_fd=directory, follow_symlinks=False), entry
            )
        os.unlink(name, dir_fd=directory)
        os.unlink(name + ".sha256", dir_fd=directory)
    os.fsync(directory)


def backup(directory, container="recall_db_1", retain=30, podman="podman"):
    if not isinstance(retain, int) or isinstance(retain, bool) or retain < 1:
        raise BackupError("retention must be a positive integer")
    if not container or container.startswith("-"):
        raise BackupError("container must be an explicit non-option container name")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"recall-auto-{timestamp}-{uuid.uuid4().hex}.dump"
    partial = "." + name + ".partial"
    sidecar = name + ".sha256"
    partial_checksum = "." + sidecar + ".partial"
    with private_directory(directory) as directory_fd, backup_lock(directory_fd):
        owned_backups(directory_fd)
        cleanup = set()
        try:
            descriptor = os.open(
                partial,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            cleanup.add(partial)
            with os.fdopen(descriptor, "w+b") as stream:
                os.fchmod(stream.fileno(), 0o600)
                run_command(
                    "pg_dump",
                    [
                        podman,
                        "exec",
                        container,
                        "pg_dump",
                        "-U",
                        "postgres",
                        "-d",
                        "recalldb",
                        "-Fc",
                        "--no-owner",
                    ],
                    stdout=stream,
                )
                if os.fstat(stream.fileno()).st_size == 0:
                    raise BackupError("pg_dump produced an empty archive")
                stream.seek(0)
                run_command(
                    "pg_restore",
                    [podman, "exec", "-i", container, "pg_restore", "--list"],
                    stdin=stream,
                    stdout=subprocess.DEVNULL,
                )
                digest = checksum(stream)
                os.fsync(stream.fileno())
            descriptor = os.open(
                partial_checksum,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            cleanup.add(partial_checksum)
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(f"{digest}  {name}\n")
                stream.flush()
                os.fsync(stream.fileno())
            # link() publishes complete files atomically and never overwrites.
            os.link(
                partial_checksum,
                sidecar,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            cleanup.add(sidecar)
            os.link(
                partial,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            cleanup.remove(sidecar)
            os.unlink(partial, dir_fd=directory_fd)
            cleanup.remove(partial)
            os.unlink(partial_checksum, dir_fd=directory_fd)
            cleanup.remove(partial_checksum)
            os.fsync(directory_fd)
            prune(directory_fd, retain, name)
        finally:
            for entry in cleanup:
                os.unlink(entry, dir_fd=directory_fd)
    return Path(os.path.abspath(directory)) / name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        required=True,
        help="dedicated private automatic backup directory",
    )
    parser.add_argument("--container", default="recall_db_1")
    parser.add_argument("--retain", type=positive_integer, default=30)
    parser.add_argument("--podman", default="podman", help="Podman executable path")
    args = parser.parse_args(argv)
    try:
        archive = backup(args.directory, args.container, args.retain, args.podman)
    except (BackupError, OSError, subprocess.SubprocessError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup validated and saved: {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
