"""Verified copy of a stopped profile v3 (libSQL) database into a new profile v4 file.

Offline service-owner operation; never exposed through the caller socket. The source is
opened read-only and immutable and is never written: its bytes are hashed before and
after. The copy is built in a new temporary file, verified (exact schema, integrity,
foreign keys, per-table row counts and content digests, WAL), and only then linked into
place, which never overwrites. Without ``apply`` the verified copy is deleted (dry run).
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from historian.libsql_store.operations import private_parent, storage_lock
from historian.libsql_store.profile import PREVIOUS_PROFILE, SQLITE, running_runtime
from historian.libsql_store.repository import connect, validate_schema

SQLITE_HEADER = b"SQLite format 3\x00"
# libSQL embedded-replica metadata; such files are synchronized, not local-only.
REPLICA_SIDECARS = ("-info", "-client_wal_index")


class MigrationError(ValueError):
    pass


def _sidecar(path, suffix):
    return Path(str(path) + suffix)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_read_only(path):
    """Read without creating -wal/-shm sidecars or changing any byte of the source."""
    uri = f"file:{quote(str(Path(path).resolve()))}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    connection.execute("PRAGMA query_only=ON")
    return connection


def inventory(connection):
    """Row count and order-independent content digest for every table.

    Rows are ordered by all columns, not rowid, which VACUUM may renumber. Values are
    hashed with their SQLite storage class so 1, 1.0, '1' and x'31' stay distinct.
    """
    result = {}
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name").fetchall()]
    for table in tables:
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        quoted = ",".join(f'"{column}"' for column in columns)
        typed = ",".join(f'typeof("{column}"),"{column}"' for column in columns)
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(f'SELECT {typed} FROM "{table}" ORDER BY {quoted}'):
            values = [value.hex() if isinstance(value, bytes) else value for value in row]
            digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8") + b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def verify_database(connection):
    validate_schema(connection)
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise MigrationError("integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("foreign key check failed")
    return inventory(connection)


def _preflight(source, destination):
    source, destination = Path(source), Path(destination)
    private_parent(source)
    private_parent(destination)
    if source.is_symlink() or not source.is_file():
        raise MigrationError("source must be an existing regular file, not a symlink")
    with open(source, "rb") as stream:
        if stream.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise MigrationError("source is not a plain local SQLite-format file "
                                 "(encrypted or remote libSQL databases are unsupported)")
    for suffix in REPLICA_SIDECARS:
        if _sidecar(source, suffix).exists():
            raise MigrationError("source has libSQL replica metadata; only local "
                                 "unsynchronized databases are supported")
    wal = _sidecar(source, "-wal")
    if wal.exists() and wal.stat().st_size:
        raise MigrationError("source has an uncheckpointed WAL; stop the old service "
                             "cleanly or migrate a backup made by the old release")
    for candidate in (destination, _sidecar(destination, "-wal"),
                      _sidecar(destination, "-shm"), _sidecar(destination, ".migration.json")):
        if candidate.exists() or candidate.is_symlink():
            raise MigrationError("destination already exists; migrate into a new path")
    if source.resolve() == destination.resolve():
        raise MigrationError("source and destination must differ")


def _fsync_directory(path):
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def migrate(source, destination, apply=False):
    """Return a JSON-serializable report. Raises on any failed check."""
    source, destination = Path(source), Path(destination)
    _preflight(source, destination)
    with storage_lock(source), storage_lock(destination):
        _preflight(source, destination)  # re-check under the service locks
        source_stat = source.stat()
        before = file_sha256(source)
        reader = open_read_only(source)
        try:
            expected = verify_database(reader)
            fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.migrating-",
                                             dir=destination.parent)
            os.close(fd)
            temporary = Path(temporary)
            try:
                writer = sqlite3.connect(str(temporary), isolation_level=None)
                try:
                    reader.backup(writer)
                    mode = writer.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    if mode != "wal":
                        raise MigrationError("destination could not enter WAL mode")
                finally:
                    writer.close()
                check = connect(temporary)
                try:
                    observed = verify_database(check)
                    journal = check.execute("PRAGMA journal_mode").fetchone()[0]
                finally:
                    check.close()
                if observed != expected:
                    raise MigrationError("copied rows differ from the source")
                if journal != "wal":
                    raise MigrationError("destination is not in WAL mode")
                wal = _sidecar(temporary, "-wal")
                if wal.exists() and wal.stat().st_size:
                    raise MigrationError("destination WAL was not checkpointed")
                wal.unlink(missing_ok=True)
                _sidecar(temporary, "-shm").unlink(missing_ok=True)
                with open(temporary, "rb") as stream:
                    os.fsync(stream.fileno())
                copy_digest = file_sha256(temporary)
            except BaseException:
                temporary.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    _sidecar(temporary, suffix).unlink(missing_ok=True)
                raise
        finally:
            reader.close()
        after = file_sha256(source)
        if after != before or source.stat().st_mtime_ns != source_stat.st_mtime_ns:
            temporary.unlink(missing_ok=True)
            raise MigrationError("source changed during migration; nothing was written")
        report = {
            "ok": True,
            "operation": "migrate",
            "dry_run": not apply,
            "source": {"path": str(source), "sha256": before,
                       "profile": PREVIOUS_PROFILE},
            "destination": {"path": str(destination), "sha256": copy_digest,
                            "profile": {"name": SQLITE.name, "version": SQLITE.version,
                                        "digest": SQLITE.digest}},
            "runtime": running_runtime(),
            "tables": expected,
            "total_rows": sum(table["rows"] for table in expected.values()),
        }
        if not apply:
            temporary.unlink(missing_ok=True)
            return report
        try:
            os.link(temporary, destination)  # never replaces an existing path
        finally:
            temporary.unlink(missing_ok=True)
        _fsync_directory(destination.parent)
        record = _sidecar(destination, ".migration.json")
        fd = os.open(record, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(destination.parent)
        return report
