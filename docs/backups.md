# Daily catalog backups

`scripts/backup_catalog.py` uses only Python's standard library (Linux/POSIX).
It backs up **recalldb**, not the separate Terracotta database, radar objects,
container volumes, roles, configuration, or secrets. It never reads `.env` or
`secrets.py`. No password is passed in a command or written by the script.

## One backup

Use a dedicated `automatic` subdirectory under your localized Documents folder
(`Documents/recall-backups/automatic`, or `Asiakirjat/recall-backups/automatic`).
Existing manual recovery dumps belong outside this directory and are never
included in automatic retention.

```sh
/absolute/path/to/python3 /absolute/path/to/recall/scripts/backup_catalog.py \
  --podman /absolute/path/to/podman \
  --container recall_db_1 \
  --directory /absolute/path/to/Documents/recall-backups/automatic \
  --retain 30
```

`--directory` is required; defaults are `--retain 30`, `--podman podman`, and
`--container recall_db_1`. Set the container to the **current** database
container, not a stale name. Existing output directories must be user-owned and
private (`chmod 700`); missing directories are created with mode 700. Directory
symlinks (including ancestors) are rejected.

The script runs `podman exec CONTAINER pg_dump -U postgres -d recalldb -Fc
--no-owner`, then validates the archive with `podman exec -i CONTAINER
pg_restore --list`. It computes a SHA-256 sidecar, fsyncs output, and publishes
complete files without overwriting existing names. Archive and sidecar have
mode 600. Names are `recall-auto-YYYYMMDDTHHMMSSffffffZ-UUID.dump` (UTC), with
a matching `.dump.sha256`. A filesystem lock rejects concurrent runs.

Only after validation and checksum publication does retention remove the oldest
strictly named archive/sidecar pairs, keeping 30 including the new backup.
Ordering uses filename timestamps, not modification times; the fresh backup is
always kept even after a clock adjustment. Manual names, unpaired dumps, and
files outside the directory are never pruned. Tool-named symlinks, hard links,
nonregular files, or malformed sidecars cause a visible failure. Do not rename
manual dumps into this tool's reserved naming format.

Failures return nonzero and write to stderr, with no success message. Failed
dump/validation/checksum operations clean only their own unfinished output and
never prune older backups. A later filesystem/pruning failure may leave a valid
new backup or partially completed retention; it still reports failure. Abrupt
termination can leave private partial files or an orphan checksum; these are
not counted/pruned automatically. The empty lock file normally remains; locking
is kernel-managed, so do not delete it while a backup could be running.

## Install the user timer (explicit opt-in)

The repository templates are **not installed or enabled automatically**.
Copy `deploy/systemd/recall-backup.service` and `.timer` to
`~/.config/systemd/user/`. Replace all placeholders in the installed service:

| Placeholder | Installation value |
| --- | --- |
| `@PYTHON@` | Absolute Python 3 executable path |
| `@BACKUP_SCRIPT@` | Absolute repository/script path |
| `@PODMAN@` | Absolute Podman executable path |
| `@DB_CONTAINER@` | Current database container name |
| `@BACKUP_DIRECTORY@` | Absolute dedicated automatic directory |

Alternatively, put a drop-in at
`~/.config/systemd/user/recall-backup.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart="/absolute/path/to/python3" "/absolute/path/to/recall/scripts/backup_catalog.py" --podman "/absolute/path/to/podman" --container "recall_db_1" --directory "/absolute/path/to/Documents/recall-backups/automatic" --retain 30
```

Paths are quoted for spaces. These are systemd command lines, **not shell**:
do not use `~` or shell substitutions; escape literal `%` as `%%` and literal
`$` as `$$` when needed. Run as the same user that owns the rootless containers.
Review installed paths, then:

```sh
systemctl --user daemon-reload
systemctl --user start recall-backup.service
journalctl --user -u recall-backup.service -n 50 --no-pager
# Enable scheduling only after the first backup succeeds:
systemctl --user enable --now recall-backup.timer
systemctl --user list-timers recall-backup.timer
```

The timer uses `OnCalendar=daily` (local midnight) and `Persistent=true` (one
catch-up trigger for missed runs). The laptop must be on and the user systemd
manager running. Normal user timers depend on login/session lifecycle; lingering
can change that lifecycle but is not enabled here. Suspend/power-off prevents
execution; catch-up does not guarantee the database is ready. No service starts
the database or other application services, and a stopped/missing container
fails visibly in the journal. A failed run is not automatically retried until
the next daily trigger; after starting the database yourself, run the service
again. Inspect failures with `systemctl --user status recall-backup.service`
and the journal. Disable scheduling with
`systemctl --user disable --now recall-backup.timer`.

## Verify and practice restoring

In the backup directory, run `sha256sum -c EXACT_ARCHIVE.dump.sha256`.
Listing a custom archive verifies its table of contents, **not a full restore**.
Regularly restore into an isolated, disposable PostgreSQL instance with
compatible PostgreSQL/PostGIS versions and required extensions. Never target the
production database for a test. Example with an already running, separately
provisioned test container named `recall-restore-test`:

```sh
podman exec recall-restore-test createdb -U postgres recall_restore_check
podman exec -i recall-restore-test pg_restore -U postgres \
  -d recall_restore_check --no-owner --no-privileges --exit-on-error \
  < /absolute/path/to/automatic/EXACT_ARCHIVE.dump
podman exec recall-restore-test psql -U postgres -d recall_restore_check \
  -c 'SELECT count(*) FROM public.event;'
```

Use a fresh test database; verify expected events/tags and application behavior,
not only command exit status. RECALL's application tables use the `public` schema;
`recalldb` is the production database name, not a schema. The script does not create a restore environment.
Retain a known-good manual recovery dump separately.

These local backups are **not offsite backups** and do not protect against laptop
loss, disk failure, or compromise of this user account. Arrange separately
protected/offsite copies. The private directory must not have untrusted writers;
keep it on a local filesystem supporting flock, hard links, and fsync.

## Tests (no database or Podman calls)

From the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_backup_catalog.py' -v
```

Tests mock subprocesses and create/clean private temporary directories inside
the repository, never system temporary directories.
