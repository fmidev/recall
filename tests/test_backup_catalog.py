import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "backup_catalog", Path(__file__).resolve().parents[1] / "scripts/backup_catalog.py"
)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".backup-test-", dir=Path.cwd()
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "automatic"
        self.directory.mkdir(mode=0o700)

    def command(self, command, **kwargs):
        if "pg_dump" in command:
            kwargs["stdout"].write(b"PGDMP test archive")
            kwargs["stdout"].flush()
        else:
            self.assertEqual(kwargs["stdin"].read(), b"PGDMP test archive")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    def seed(self, day):
        name = f"recall-auto-202601{day:02d}T000000000000Z-{'a' * 32}.dump"
        archive = self.directory / name
        archive.write_bytes(b"old")
        archive.with_name(name + ".sha256").write_text(
            f"{hashlib.sha256(b'old').hexdigest()}  {name}\n"
        )
        return archive

    def partials(self):
        return list(self.directory.glob("*.partial"))

    def test_invalid_retention(self):
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    catalog.main(
                        ["--directory", str(self.directory), "--retain", value]
                    )
                self.assertEqual(error.exception.code, 2)
        with self.assertRaises(catalog.BackupError):
            catalog.backup(self.directory, retain=0)

    def test_success_checksum_permissions_and_commands(self):
        with patch.object(catalog.subprocess, "run", side_effect=self.command) as run:
            result = catalog.backup(self.directory, container="current-db")
        self.assertTrue(catalog.ARCHIVE_PATTERN.fullmatch(result.name))
        self.assertEqual(result.read_bytes(), b"PGDMP test archive")
        sidecar = result.with_name(result.name + ".sha256")
        self.assertEqual(
            sidecar.read_text(),
            f"{hashlib.sha256(result.read_bytes()).hexdigest()}  {result.name}\n",
        )
        for path in (result, sidecar, self.directory / catalog.LOCK_NAME):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "podman",
                "exec",
                "current-db",
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "recalldb",
                "-Fc",
                "--no-owner",
            ],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "podman",
                "exec",
                "-i",
                "current-db",
                "pg_restore",
                "--list",
            ],
        )
        self.assertFalse(self.partials())

    def test_dump_failure_preserves_older_files_and_reports_failure(self):
        old = self.seed(1)

        def failure(command, **kwargs):
            self.command(command, **kwargs)
            return subprocess.CompletedProcess(
                command, 125, b"", b"container is stopped"
            )

        stderr, stdout = io.StringIO(), io.StringIO()
        with (
            patch.object(catalog.subprocess, "run", side_effect=failure),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(stdout),
        ):
            result = catalog.main(["--directory", str(self.directory), "--retain", "1"])
        self.assertEqual(result, 1)
        self.assertIn("pg_dump failed", stderr.getvalue())
        self.assertIn("container is stopped", stderr.getvalue())
        self.assertFalse(stdout.getvalue())
        self.assertTrue(old.exists())
        self.assertTrue(old.with_name(old.name + ".sha256").exists())
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertFalse(self.partials())

    def test_archive_validation_failure_does_not_publish_or_prune(self):
        old = self.seed(1)

        def failure(command, **kwargs):
            if "pg_restore" in command:
                return subprocess.CompletedProcess(command, 1, b"", b"invalid archive")
            return self.command(command, **kwargs)

        with patch.object(catalog.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(catalog.BackupError, "pg_restore failed"):
                catalog.backup(self.directory, retain=1)
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertFalse(self.partials())

    def test_checksum_failure_does_not_publish_or_prune(self):
        old = self.seed(1)
        with (
            patch.object(catalog.subprocess, "run", side_effect=self.command),
            patch.object(catalog, "checksum", side_effect=OSError("read error")),
        ):
            with self.assertRaisesRegex(OSError, "read error"):
                catalog.backup(self.directory, retain=1)
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertFalse(self.partials())

    def test_sidecar_publication_failure_does_not_publish_or_prune(self):
        old = self.seed(1)
        stderr = io.StringIO()
        with (
            patch.object(catalog.subprocess, "run", side_effect=self.command),
            patch.object(catalog.os, "link", side_effect=OSError("disk full")),
            contextlib.redirect_stderr(stderr),
        ):
            result = catalog.main(["--directory", str(self.directory), "--retain", "1"])
        self.assertEqual(result, 1)
        self.assertIn("disk full", stderr.getvalue())
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertEqual(len(list(self.directory.glob("*.sha256"))), 1)
        self.assertFalse(self.partials())

    def test_archive_publication_failure_removes_only_own_sidecar(self):
        old = self.seed(1)
        original_link = catalog.os.link
        calls = 0

        def fail_archive(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("archive publication failed")
            return original_link(*args, **kwargs)

        with (
            patch.object(catalog.subprocess, "run", side_effect=self.command),
            patch.object(catalog.os, "link", side_effect=fail_archive),
        ):
            with self.assertRaisesRegex(OSError, "archive publication failed"):
                catalog.backup(self.directory, retain=1)
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertEqual(len(list(self.directory.glob("*.sha256"))), 1)
        self.assertFalse(self.partials())

    def test_malformed_checksum_prevents_pruning(self):
        old = self.seed(1)
        old.with_name(old.name + ".sha256").write_text("invalid\n")
        with patch.object(catalog.subprocess, "run") as run:
            with self.assertRaisesRegex(catalog.BackupError, "invalid checksum"):
                catalog.backup(self.directory, retain=1)
            run.assert_not_called()
        self.assertTrue(old.exists())

    def test_retention_only_removes_owned_pairs(self):
        older = [self.seed(day) for day in range(1, 5)]
        manual = self.directory / "recovery.dump"
        manual.write_bytes(b"manual")
        outside = self.root / older[0].name
        outside.write_bytes(b"outside")
        orphan = self.seed(5)
        orphan.with_name(orphan.name + ".sha256").unlink()
        unrelated_link = self.directory / "manual.dump"
        unrelated_link.symlink_to(outside)
        with patch.object(catalog.subprocess, "run", side_effect=self.command):
            result = catalog.backup(self.directory, retain=3)
        self.assertTrue(result.exists())
        self.assertFalse(older[0].exists())
        self.assertFalse(older[1].exists())
        for removed in older[:2]:
            self.assertFalse(removed.with_name(removed.name + ".sha256").exists())
        for kept in older[2:] + [manual, outside, orphan]:
            self.assertTrue(kept.exists())
        self.assertTrue(unrelated_link.is_symlink())

    def test_default_retention_keeps_thirty(self):
        for day in range(1, 32):
            self.seed(day)
        with patch.object(catalog.subprocess, "run", side_effect=self.command):
            catalog.backup(self.directory)
        self.assertEqual(len(list(self.directory.glob("*.dump"))), 30)
        self.assertEqual(len(list(self.directory.glob("*.sha256"))), 30)

    def test_lock_busy_does_not_run_commands(self):
        with (
            catalog.private_directory(self.directory) as directory,
            catalog.backup_lock(directory),
            patch.object(catalog.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(catalog.BackupError, "lock is busy"):
                catalog.backup(self.directory)
        run.assert_not_called()

    def test_rejects_symlink_directory_and_ancestor(self):
        link = self.root / "link"
        link.symlink_to(self.directory, target_is_directory=True)
        for directory in (link, link / "nested"):
            with (
                self.subTest(directory=directory),
                patch.object(catalog.subprocess, "run") as run,
            ):
                with self.assertRaises(OSError):
                    catalog.backup(directory)
                run.assert_not_called()
        self.assertFalse((self.directory / "nested").exists())

    def test_rejects_owned_archive_checksum_and_lock_symlinks(self):
        outside = self.root / "outside"
        outside.write_bytes(b"do not touch")
        for entry_type in ("archive", "checksum", "lock"):
            with self.subTest(entry_type=entry_type):
                archive = self.seed(1)
                sidecar = archive.with_name(archive.name + ".sha256")
                target = {
                    "archive": archive,
                    "checksum": sidecar,
                    "lock": self.directory / catalog.LOCK_NAME,
                }[entry_type]
                target.unlink(missing_ok=True)
                target.symlink_to(outside)
                with patch.object(catalog.subprocess, "run") as run:
                    with self.assertRaises((OSError, catalog.BackupError)):
                        catalog.backup(self.directory, retain=1)
                    run.assert_not_called()
                self.assertEqual(outside.read_bytes(), b"do not touch")
                target.unlink()
                archive.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)

    def test_refuses_public_directory(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(catalog.BackupError, "private"):
            catalog.backup(self.directory)

    def test_creates_private_directory(self):
        directory = self.directory / "new" / "automatic"
        with patch.object(catalog.subprocess, "run", side_effect=self.command):
            catalog.backup(directory)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
