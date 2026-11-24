"""Profile v3 -> v4 migration: dry run by default, never in place, fully verified.

The real libSQL 0.1.11 -> SQLite round trip runs in scripts/ci-migration-compat.sh;
these tests cover the tool's refusals and verification with stdlib-written files, which
share the exact on-disk format and schema.
"""

import json
import os
import sqlite3
import stat

import pytest

from historian.libsql_store import migrate as m
from historian.libsql_store.operations import check, storage_lock
from historian.libsql_store.profile import PREVIOUS_PROFILE, SQLITE
from historian.libsql_store.repository import connect, initialize
from historian.libsql_store.service import require_supported_runtime, wire_error
from migration_fixture import populate


@pytest.fixture
def layout(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for directory in (old, new):
        directory.mkdir(mode=0o700)
    source = old / "historian.db"
    populate(source, tmp_path / "corpus")
    return source, new / "historian.db"


def digest(path):
    return m.file_sha256(path)


def leftovers(directory):
    return sorted(p.name for p in directory.iterdir() if not p.name.endswith(".lock"))


def test_dry_run_verifies_everything_and_writes_nothing(layout):
    source, destination = layout
    before = digest(source)
    report = m.migrate(source, destination)
    assert report["ok"] and report["dry_run"]
    assert report["source"]["profile"] == PREVIOUS_PROFILE
    assert report["destination"]["profile"] == {
        "name": SQLITE.name, "version": 4, "digest": SQLITE.digest}
    assert report["tables"]["question"]["rows"] == 3
    assert report["total_rows"] == sum(t["rows"] for t in report["tables"].values()) > 0
    assert leftovers(destination.parent) == []
    assert digest(source) == before
    assert leftovers(source.parent) == ["historian.db"]  # no -wal/-shm created


def test_apply_produces_a_verified_copy_and_leaves_the_source_untouched(layout):
    source, destination = layout
    before = digest(source)
    report = m.migrate(source, destination, apply=True)
    assert not report["dry_run"]
    assert digest(source) == before == report["source"]["sha256"]
    assert digest(destination) == report["destination"]["sha256"]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    record = json.loads(destination.with_name("historian.db.migration.json").read_text())
    assert record == json.loads(json.dumps(report, sort_keys=True))
    check(destination)
    c = connect(destination)
    try:
        assert m.inventory(c) == report["tables"]
        assert c.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM evidence")
    finally:
        c.close()
    # Service startup path accepts the migrated schema unchanged.
    initialize(destination)


def test_never_overwrites_an_existing_destination_or_its_sidecars(layout):
    source, destination = layout
    for suffix in ("", "-wal", "-shm", ".migration.json"):
        target = destination.with_name(destination.name + suffix)
        target.write_bytes(b"keep")
        with pytest.raises(m.MigrationError, match="already exists"):
            m.migrate(source, destination, apply=True)
        assert target.read_bytes() == b"keep"
        target.unlink()


def test_source_and_destination_must_differ(layout):
    source, _ = layout
    with pytest.raises(m.MigrationError):
        m.migrate(source, source, apply=True)


def test_refuses_uncheckpointed_wal(layout):
    source, destination = layout
    source.with_name(source.name + "-wal").write_bytes(b"\0" * 32)
    with pytest.raises(m.MigrationError, match="WAL"):
        m.migrate(source, destination)
    assert leftovers(destination.parent) == []


def test_empty_wal_left_by_clean_shutdown_is_accepted(layout):
    source, destination = layout
    source.with_name(source.name + "-wal").write_bytes(b"")
    assert m.migrate(source, destination)["ok"]


def test_refuses_libsql_replica_metadata(layout):
    source, destination = layout
    source.with_name(source.name + "-info").write_text("{}")
    with pytest.raises(m.MigrationError, match="replica"):
        m.migrate(source, destination)


def test_refuses_non_sqlite_or_encrypted_files(layout):
    source, destination = layout
    source.write_bytes(os.urandom(4096))
    with pytest.raises(m.MigrationError, match="plain local SQLite"):
        m.migrate(source, destination)


def test_refuses_symlinked_source(layout, tmp_path):
    source, destination = layout
    link = source.with_name("link.db")
    link.symlink_to(source)
    with pytest.raises(m.MigrationError, match="symlink"):
        m.migrate(link, destination)


def test_refuses_unknown_schema(layout):
    source, destination = layout
    c = connect(source)
    c.execute("DROP TRIGGER immutable_question_UPDATE")
    c.close()
    with pytest.raises(ValueError, match="unsupported schema"):
        m.migrate(source, destination)
    assert leftovers(destination.parent) == []


def test_refuses_while_the_service_holds_the_lock(layout):
    source, destination = layout
    with storage_lock(source):
        with pytest.raises(RuntimeError, match="in use"):
            m.migrate(source, destination, apply=True)
    assert not destination.exists()


def test_refuses_non_private_directories(layout):
    source, destination = layout
    destination.parent.chmod(0o755)
    with pytest.raises(ValueError, match="owner-private"):
        m.migrate(source, destination)


def test_copy_that_differs_from_source_is_discarded(layout, monkeypatch):
    source, destination = layout
    real = m.inventory
    calls = []

    def tampered(connection):
        result = real(connection)
        calls.append(1)
        if len(calls) == 2:  # the copy
            result["evidence"] = {**result["evidence"], "rows": result["evidence"]["rows"] - 1}
        return result

    monkeypatch.setattr(m, "inventory", tampered)
    with pytest.raises(m.MigrationError, match="differ"):
        m.migrate(source, destination, apply=True)
    assert not destination.exists()
    assert leftovers(destination.parent) == []


def test_inventory_distinguishes_storage_classes(tmp_path):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t(v)")
    c.execute("INSERT INTO t VALUES (1)")
    first = m.inventory(c)
    c.execute("DELETE FROM t")
    c.execute("INSERT INTO t VALUES ('1')")
    assert m.inventory(c)["t"]["rows"] == first["t"]["rows"]
    assert m.inventory(c)["t"]["sha256"] != first["t"]["sha256"]


def _integrity_error(sql):
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript("""
        CREATE TABLE p(id PRIMARY KEY);
        CREATE TABLE a(x, y REFERENCES p(id), z,
          CONSTRAINT assertion_origin_binding CHECK(x='ok'),
          CONSTRAINT other_constraint CHECK(z IS NULL OR z<5));
        CREATE TRIGGER no_delete BEFORE DELETE ON p BEGIN SELECT RAISE(ABORT,'immutable'); END;
        INSERT INTO p VALUES (1);""")
    try:
        c.execute(sql)
    except sqlite3.IntegrityError as exc:
        return exc
    raise AssertionError("statement was accepted")


def test_only_the_named_check_earns_assertion_origin_binding():
    assert wire_error(_integrity_error("INSERT INTO a VALUES ('bad', NULL, NULL)")) == (
        "assertion_origin_binding")


@pytest.mark.parametrize("sql", [
    "INSERT INTO a VALUES ('ok', NULL, 9)",  # a different named CHECK
    "INSERT INTO a VALUES ('ok', 99, NULL)",  # foreign key
    "DELETE FROM p",                         # RAISE(ABORT) trigger
])
def test_other_constraint_failures_keep_the_v3_wire_name(sql):
    assert wire_error(_integrity_error(sql)) == "ValueError"


def test_lookalike_message_without_the_check_code_is_not_pv17_evidence():
    message = "CHECK constraint failed: assertion_origin_binding"
    assert wire_error(ValueError(message)) == "ValueError"
    forged = sqlite3.IntegrityError("CHECK constraint failed: assertion_origin_binding")
    assert wire_error(forged) == "ValueError"
    assert wire_error(PermissionError("x")) == "PermissionError"


def test_runtime_floor():
    require_supported_runtime("3.38.0")
    require_supported_runtime(sqlite3.sqlite_version)
    with pytest.raises(RuntimeError, match="3.38.0"):
        require_supported_runtime("3.37.2")
