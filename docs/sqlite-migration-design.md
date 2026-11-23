# Design note: libSQL → stdlib SQLite (persistence profile v4)

Status: implemented on `claude/sqlite-profile-v4`. Supersedes the direction of
Deep-Sixed/historian#17, which stays open and unmerged.

## Goal

Replace the `libsql==0.1.11` driver with Python's standard-library `sqlite3`.
The package then has no runtime dependency. The trust boundary stays the same: one
service process (UID 10000) owns the database file, callers reach it only through
the Unix socket, and every operation is authorised by the caller's `SO_PEERCRED`
kernel UID against `service.CAPABILITIES`, `service.ALLOWED` and `access.py`.

Out of scope: schema changes, changes to the Persistence v1 catalog or harness,
socket protocol changes, Python API renames, and any release or tag. The release
blocker in `history-sanitization.md` still applies.

## What the earlier attempt did, and why it stalled

`codex/sqlite3-only` (Deep-Sixed/historian#17, one commit, 46 files) passed CI on
2026-09-13 and was never merged. No comment, review or note records why. Comparing
it with `main` shows these problems. Each one is reason enough to hold a merge.

1. **The profile lineage restarted, and its digest depended on the runtime.**
   #17 introduced `sqlite-linux-peercred-service-v1` at **version 1** instead of
   superseding v3. It also built `deployment_model` from `platform.python_version()`
   and `sqlite3.sqlite_version` at import time. The profile digest therefore changed
   from machine to machine:
   - the core job (setup-python on Ubuntu) computed a different digest from the
     proof container;
   - the 3.13 matrix leg computed yet another;
   - `prepare-release.py` validated whatever digest its own interpreter produced.

   The profile no longer declared a certified deployment. It described whatever
   happened to run.
2. **Python import paths broke.** It renamed `historian.libsql_store` to
   `historian.sqlite_store` with no shim. Every API client and `cases/build_queue.py`
   broke, the evidence artifact names changed, and the PR touched 46 files. That made
   it hard to review and liable to conflict with concurrent work.
3. **Migration meant opening the old file in place.** The plan was to open the live
   libSQL file with the new driver. There was no tool and no dry run, and nothing
   checked row counts or content. The libSQL → sqlite3 check was a one-off manual
   experiment, not a reproducible CI job. Rollback assumed a backup made beforehand.
4. **The wire protocol changed without saying so.** The socket reports
   `type(exc).__name__`. Constraint failures changed from `ValueError` (libSQL) to
   `IntegrityError`, and the tests were edited to match. Clients see a different
   error string.
5. **CI has drifted since.** `ubuntu-latest` now resolves to Ubuntu 26.04, which has
   no setup-python build of 3.14.5. Every job would fail at setup. #18 pins
   `ubuntu-24.04`, but #17 predates that.

Kept from #17:
- the strict PV17 mapping, which requires `sqlite3.IntegrityError`, `SQLITE_CONSTRAINT_CHECK`
  and the exact constraint message;
- its evidence that the schema is unchanged;
- the installed-wheel assertion that `libsql` is absent.

## SQL compatibility (verified, not assumed)

A file written by libSQL 0.1.11 (embedded SQLite 3.45.1) was read with stdlib sqlite3.
It is an ordinary SQLite format-3 file with the WAL header bytes (`0x02 0x02`). Its
`sqlite_master` is byte-identical to the reference schema that sqlite3 builds from
`schema.sql` and `application.sql` (88 objects). The rest of the code base depends on
the following features, all of which stdlib sqlite3 provides:

| Feature | Where | Check |
|---|---|---|
| `PRAGMA foreign_keys=ON`, composite FKs | `connect`, schema | probes PV01–PV03, PV09, PV18, PV19 |
| Named `CHECK` constraints | `assertion_origin_binding` | PV17; error code `SQLITE_CONSTRAINT_CHECK` |
| `BEFORE` triggers with `RAISE(ABORT)` | seal, immutability, gold | PV05, PV06, PV10, PV15 |
| `json_valid`, `json_extract` | evidence, app_object | built in since SQLite 3.38 |
| `PRAGMA journal_mode=WAL`, `synchronous=FULL` | schema, `connect` | `test_runtime_and_storage_pragmas` |
| `BEGIN IMMEDIATE` with explicit commit/rollback | `transaction()` | PV13 |
| `VACUUM INTO ?` | backup/restore | `test_backup_restore_*` |
| Online backup API | migration | `test_sqlite_migration.py` |

The two drivers differ in three ways:
- **Exception classes.** libSQL raised `ValueError` for every constraint failure.
  sqlite3 raises `sqlite3.IntegrityError` and carries `sqlite_errorcode`.
- **`executescript`.** In sqlite3 it commits any pending transaction first. The
  existing callers (`_create_schema`, `upgrade_schema`) already run it outside a
  transaction or open their own `BEGIN IMMEDIATE` inside the script, so nothing changes.
- **Sidecar files on read-only opens.** sqlite3 creates `-wal` and `-shm` even for
  `mode=ro` opens of a WAL database. The migration therefore reads with
  `immutable=1` and refuses a source with a non-empty WAL.

## Decisions

### 1. The driver change stays inside the service

- `repository.connect()` uses `sqlite3.connect(path, isolation_level=None)`. The
  pragmas are unchanged.
- In `service.Handler`:
  - PV17 is earned only by `sqlite3.IntegrityError` with `SQLITE_CONSTRAINT_CHECK`
    and the exact message `CHECK constraint failed: assertion_origin_binding`.
  - Any other `sqlite3.IntegrityError` goes out on the wire as `ValueError`, as it did
    under v3. The protocol is unchanged and gains no detail.
- `serve()` checks the runtime floor (SQLite ≥ 3.38, which has built-in JSON) and
  fails closed below it.
- The package path stays `historian.libsql_store` for now, so the Python API, the
  case-queue tool, the evidence artifact names and the test file names do not change.
  The name is now historical: its docstring says so, and the docs call the backend
  SQLite. A mechanical rename is a separate follow-up PR, once this one has merged.

### 2. Profile v4 supersedes v3; v3 itself does not change

- Name `sqlite-linux-peercred-service-v1`, **version 4**. The `-v1` suffix follows
  the existing convention: it names the service and contract generation (v3 was
  `…-service-v1` at version 3). The version number continues the v3 lineage.
- `backend_family="SQLite"`. `deployment_model` names a **fixed certified runtime**:
  Python 3.14.5 and stdlib `sqlite3` linked to SQLite 3.46.1, as shipped in
  `python:3.14.5-slim`. These are string constants, so the digest is the same on
  every machine. `CERTIFIED_RUNTIME` is exported for the checks below.
- Every other field, including the threat model and the `access.py` matrix, is
  carried over unchanged. The digest changes because the backend and deployment
  fields changed.
- Evidence cannot be relabelled:
  - The container proof suite asserts that the running Python and SQLite match
    `CERTIFIED_RUNTIME` and records the runtime in every report.
  - `prepare-release.py` rejects a report whose runtime differs.
  - `historian profile` prints the running versions and whether they match.
- The v3 document stays and is marked superseded, with its digest
  `ce6b23be…124b` preserved for audit. `docs/sqlite-profile-v4.md` is new.

### 3. Migration: `historian migrate` (dry run by default, never in place)

`historian migrate --source OLD --destination NEW [--apply]` runs as UID 10000 with
the service stopped. In order:

1. Take the service's exclusive `storage_lock` on both paths. A running service on
   either path fails the command.
2. Preconditions, each failing closed:
   - both parent directories are owner-private;
   - the source is a regular file, not a symlink, with the SQLite format-3 header.
     This rejects libSQL-encrypted files.
   - no libSQL embedded-replica metadata (`OLD-info`) is present;
   - `OLD-wal` is absent or empty. A non-empty WAL means the old service did not
     shut down cleanly; stop it cleanly, or run the old release's `historian backup`,
     and migrate that backup instead.
   - the destination and its `-wal`/`-shm` do not exist, and the destination is
     not the same file as the source (resolved path or inode).
3. Hash the source file and open it read-only and immutable
   (`file:…?mode=ro&immutable=1`). Then check it:
   - the schema matches exactly (v3 and v4 share it; older schemas must first be
     upgraded with the old release);
   - `integrity_check` and `foreign_key_check` pass;
   - an inventory records each table's row count and a SHA-256 over its rows in
     total column order. The order does not depend on rowid, which `VACUUM` may
     renumber.
4. Copy with the sqlite3 online backup API into a new temporary file
   (`O_EXCL`, 0600) in the destination directory. Set WAL, close it, and reopen it
   through the same `connect()` the service uses. Then verify the copy:
   - the schema matches exactly;
   - the integrity and FK checks pass;
   - the inventory equals the source's;
   - the journal mode is `wal`.
   Finally fsync the file.
5. Hash the source again and require the same bytes. This proves the source was
   not touched.
6. **Dry run (the default):** delete the temporary file and print a JSON report.
   **`--apply`:** move the file into place with `link()`, which never overwrites,
   fsync the directory, and write `NEW.migration.json` (0600) recording:
   - the hashes;
   - the inventory;
   - the source and target profile names, versions and digests;
   - the runtime versions.

   Any failure removes the temporary file. Nothing is ever written to `OLD`.

### 4. Rollback

The source is never modified, so rollback is:
1. stop the v4 service;
2. point the unit back at the retained v3 environment (wheel with libsql 0.1.11)
   and the original database path;
3. start it.

Writes accepted after the cutover exist only in the new file. To carry them back,
run `historian migrate` in the other direction: SQLite file to new path, then
start v3 on that path. The CI compatibility job proves that libSQL 0.1.11 can
validate, read and append to a file produced by the migration. Keep the cutover
window short and check the new service before releasing callers. Never merge two
files that were written independently.

### 5. CI

- All jobs are pinned to `ubuntu-24.04`, the same change as #18, so the two merge
  cleanly.
- The profile job is renamed "SQLite Linux peer-credential profile (v4)". The
  Dockerfile installs `.[dev]`, and the suite asserts the certified runtime.
- New job "libSQL v3 → SQLite v4 migration compatibility" (`scripts/ci-migration-compat.sh`).
  It is the only place libsql 0.1.11 is installed:
  1. Check out the last v3 commit (`36fe35a`) and use its own code and libSQL to
     write a populated v3 database. This covers every core table, the sealed
     publications and the application objects.
  2. Migrate it with v4: first a dry run, then `--apply`.
  3. Run the v4 service checks on the result.
  4. Reopen the result with v3 code and libSQL: check it, read it, append to it.
     This proves the rollback carry-back path.
- `ci-package.sh` asserts that `libsql` is not installed.

### 6. Docs revised together

`sqlite-profile-v4.md` (new); `libsql-profile-v3.md` (marked superseded);
`persistence-v1.md`, `application-persistence.md`, `release-operations.md`,
`migration.md`, `RUNBOOK.md`, `README.md`, `RELEASE-NOTES.md` (an unreleased
section), `GATE-MAPPING.md`, and the three frozen-doc banners.

## Test plan

- Core suite and `scripts/public_release_guard.py` on Python 3.13 and 3.14.5.
- New core tests in `tests/test_sqlite_migration.py`:
  - the dry run leaves no files behind;
  - `--apply` produces a verified copy and leaves the source bytes unchanged;
  - refusals: an existing destination, the same file or a hard link, a non-empty
    WAL, an embedded-replica sidecar, a non-SQLite file, a schema mismatch, a held
    service lock, and a copy whose inventory does not match;
  - PV17 error-mapping unit tests (CHECK versus FK versus trigger failures).
- Deployment proof as root against real UIDs. It needs every one of:
  - 43/43 shared probes;
  - 124 supplemental boundary checks;
  - the full application capability-denial matrix;
  - the runtime assertion.
- The migration compatibility job described above.

## Risks and open questions

- **The certified SQLite version comes from the base image.** A rebuilt
  `python:3.14.5-slim` with a different `libsqlite3` fails the runtime assertion
  closed instead of silently producing evidence. Pinning the base image by digest
  would make this reproducible. That is left as an owner decision.
- **The package name is still libSQL.** Until the follow-up rename,
  `historian.libsql_store` holds the SQLite backend. This is deliberate, to keep
  this diff reviewable and the API stable.
- **Version skew.** libSQL 0.1.11 embeds SQLite 3.45.1; the certified runtime is
  3.46.1. The schema uses no feature newer than 3.38, and the compatibility job
  covers both directions.
