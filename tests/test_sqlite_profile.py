"""Linux deployment proof. Run only inside the disposable profile container as root."""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from enum import Enum
from pathlib import Path
from uuid import uuid4

import pytest

from sqlite_probe import ROLES, SQLiteProbe, locator

from historian.sqlite_store.profile import SQLITE
from historian.persistence.catalog import CATALOG
from historian.persistence.contract import Access, ConformanceHarness, Status

pytestmark = pytest.mark.sqlite


@pytest.fixture(scope="module")
def deployment():
    if os.environ.get("HISTORIAN_RUN_SQLITE") != "1":
        pytest.skip(
            "requires disposable Linux profile deployment; see deployment/sqlite/Dockerfile"
        )
    assert sys.platform == "linux" and os.getuid() == 0, (
        "run in disposable profile container as root"
    )
    root = Path(tempfile.mkdtemp(prefix="historian-sqlite-", dir="/tmp"))
    root.chmod(0o755)
    private, public, corpus = (root / name for name in ("private", "socket", "corpus"))
    for directory in (private, public, corpus):
        directory.mkdir()
        os.chown(directory, 10000, 10000)
        directory.chmod(0o755 if directory == public else 0o700)
    (corpus / "2026-01-01-source.md").write_bytes(b"authority passage\n")
    database, socket = private / "historian.db", public / "historian.sock"

    def start():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "historian.sqlite_store.service",
                "--database",
                str(database),
                "--socket",
                str(socket),
                "--corpus",
                str(corpus),
            ],
            user=10000,
            group=10000,
            extra_groups=[],
        )
        for _ in range(100):
            if socket.exists():
                return process
            if process.poll() is not None:
                raise AssertionError("service failed to start")
            time.sleep(0.05)
        process.terminate()
        raise AssertionError("service startup timed out")

    process = start()
    probe = SQLiteProbe(database, socket, corpus)
    probe.boundary_evidence = []
    try:
        yield probe, process, start
    finally:
        process.terminate()
        process.wait(timeout=10)
        if probe.boundary_evidence:
            Path("/tmp/historian-sqlite-boundaries.json").write_text(
                json.dumps(
                    {
                        "profile_name": SQLITE.name,
                        "profile_version": SQLITE.version,
                        "profile_digest": SQLITE.digest,
                        "evidence": probe.boundary_evidence,
                    },
                    indent=2,
                )
            )



def test_sqlite_profile_conformance(deployment):
    probe, _, _ = deployment
    report = ConformanceHarness(CATALOG).run(SQLITE, probe)
    destination = Path(
        os.environ.get(
            "HISTORIAN_SQLITE_REPORT", "/tmp/historian-sqlite-conformance.json"
        )
    )
    destination.write_text(
        json.dumps(
            asdict(report),
            indent=2,
            default=lambda v: v.value if isinstance(v, Enum) else str(v),
        )
    )
    print(
        f"\n{report.profile_name} v{report.profile_version} {report.profile_digest}: {report.status.value}"
    )
    untested = [
        (e.test_id, e.detail) for e in report.evidence if e.status is Status.NOT_TESTED
    ]
    failures = {
        e.test_id for e in report.evidence if e.status is Status.DOES_NOT_CONFORM
    }
    assert not untested, untested
    assert failures == set()
    assert report.status is Status.CONFORMS
    assert len(report.evidence) == 43
    assert all(e.profile_digest == SQLITE.digest for e in report.evidence)


@pytest.mark.parametrize("uid", list(ROLES.values()) + [10099])
def test_real_callers_cannot_access_or_mutate_storage_or_assume_service_uid(
    deployment, uid
):
    probe, process, _ = deployment
    # Positive control proves the path is real and readable by the service owner.
    assert probe.worker(10000, {"kind": "file", "path": probe.database})["ok"]
    attempts = [
        {"kind": "file", "path": probe.database},
        {"kind": "file", "path": probe.database, "mode": "r+b"},
        {"kind": "replace_socket", "path": probe.database},
        {"kind": "replace_socket", "path": probe.socket},
        {"kind": "file", "path": f"/proc/{process.pid}/environ"},
        {"kind": "assume"},
    ]
    for attempt in attempts:
        result = probe.worker(uid, attempt)
        probe.boundary_evidence.append(
            {
                "actor": f"uid:{uid}",
                "access": "direct_bypass",
                "operation": attempt["kind"],
                "target": attempt.get("path", "service UID"),
                "expected": "PermissionError",
                "observed": result.get("error", "accepted"),
            }
        )
        assert not result["ok"] and result["error"] == "PermissionError", (
            uid,
            attempt["kind"],
        )
    result = probe.worker(
        uid,
        {
            "kind": "sql",
            "database": probe.database,
            "statements": [("DELETE FROM evidence", [])],
        },
    )
    probe.boundary_evidence.append(
        {
            "actor": f"uid:{uid}",
            "access": "direct_bypass",
            "operation": "raw_sqlite_delete",
            "expected": "cannot open database",
            "observed": "cannot open database"
            if not result["ok"] and "open" in result.get("detail", "").lower()
            else "unexpected result",
        }
    )
    assert not result["ok"]
    assert "open" in result.get("detail", "").lower()


@pytest.mark.parametrize("role", list(ROLES))
def test_raw_socket_has_no_sql_role_switch_or_finalizer_escape(deployment, role):
    probe, _, _ = deployment
    for operation in (
        "raw_sql",
        "set_role",
        "set_capability_context",
        "finalize",
        "delete",
        "update",
    ):
        result = probe.call(
            role, operation, sql="DELETE FROM evidence", role="verifier", uid=10000
        )
        probe.boundary_evidence.append(
            {
                "actor": result["principal"],
                "capability": result["capability"],
                "access": "direct_bypass",
                "operation": operation,
                "expected": "forbidden",
                "observed": result.get("error", "accepted"),
            }
        )
        assert not result["ok"] and result["error"] == "forbidden"
        assert result["principal"] == f"uid:{ROLES[role]}"



def test_second_service_cannot_replace_live_socket(deployment):
    probe, _, _ = deployment
    result = subprocess.run(
        [sys.executable, "-m", "historian.sqlite_store.service",
         "--database", str(probe.database), "--socket", str(probe.socket),
         "--corpus", str(probe.corpus)],
        user=10000, group=10000, extra_groups=[], capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert b"storage is in use" in result.stderr
    probe.ok("designer", "question", id=uuid4().hex, text="still serving")

def test_assertion_origin_binding_is_enforced_by_database(deployment):
    probe, _, _ = deployment
    probe.setup()
    typed_ok = probe.call(
        "typed",
        "assertion",
        id=uuid4().hex,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="TYPED_SOURCE",
    )
    typed_bad = probe.call(
        "typed",
        "assertion",
        id=uuid4().hex,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="HUMAN_REVIEWED_PROPOSAL",
    )
    reviewer_ok = probe.call(
        "reviewer",
        "assertion",
        id=uuid4().hex,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="HUMAN_REVIEWED_PROPOSAL",
    )
    reviewer_bad = probe.call(
        "reviewer",
        "assertion",
        id=uuid4().hex,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="TYPED_SOURCE",
    )
    assert typed_ok["ok"] and reviewer_ok["ok"]
    assert not typed_bad["ok"] and typed_bad["error"] == "assertion_origin_binding"
    assert (
        not reviewer_bad["ok"] and reviewer_bad["error"] == "assertion_origin_binding"
    )


@pytest.mark.parametrize(
    "error",
    [
        "forbidden",
        "ValueError",
        "IntegrityError",
        "OperationalError",
        "RuntimeError",
        "database locked",
        "disk I/O error",
        "FOREIGN KEY constraint failed",
        "CHECK constraint failed: other_constraint",
    ],
)
def test_pv17_unrelated_rejection_cannot_earn_conformance(error):
    invariant = next(i for i in CATALOG if i.id == "PV17")
    profile = replace(SQLITE, claimed_invariant_coverage=("PV17",))
    probe = SQLiteProbe.__new__(SQLiteProbe)

    class RejectionProbe:
        def execute(self, test):
            return probe.assertion_db_result(
                {
                    "ok": test.id == "PV17.normal",
                    "error": error,
                    "principal": "uid:10004",
                    "capability": "typed",
                },
                test.access,
            )

    result = ConformanceHarness((invariant,)).run(profile, RejectionProbe())
    bypass = next(e for e in result.evidence if e.test_id == "PV17.bypass")
    assert bypass.status is Status.NOT_TESTED
    assert result.status is not Status.CONFORMS


def test_pv17_specific_constraint_rejection_earns_conformance(deployment):
    probe, _, _ = deployment
    invariant = next(i for i in CATALOG if i.id == "PV17")
    profile = replace(SQLITE, claimed_invariant_coverage=("PV17",))
    result = ConformanceHarness((invariant,)).run(profile, probe)
    assert result.status is Status.CONFORMS


def test_assertion_unrelated_database_error_is_not_origin_binding(deployment):
    probe, _, _ = deployment
    probe.setup()
    result = probe.call(
        "typed",
        "assertion",
        id=uuid4().hex,
        subject_id="missing-evidence",
        object_id=probe.e2,
        origin="TYPED_SOURCE",
    )
    assert not result["ok"] and result["error"] == "IntegrityError"
    with pytest.raises(RuntimeError, match="not proven"):
        probe.assertion_db_result(result, Access.BYPASS)


def test_assertion_request_body_cannot_override_principal_or_capability(deployment):
    probe, _, _ = deployment
    probe.setup()
    assertion_id = uuid4().hex
    result = probe.call(
        "typed",
        "assertion",
        id=assertion_id,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="TYPED_SOURCE",
        writer_principal="uid:10005",
        writer_capability="reviewer",
        writer="uid:10005",
        principal="uid:10005",
        capability="reviewer",
    )
    assert result["ok"]
    row = probe.sql(
        (
            "SELECT origin,writer_principal,writer_capability FROM assertion WHERE id=?",
            (assertion_id,),
        )
    )
    assert row["rows"] == [[["TYPED_SOURCE", "uid:10004", "typed"]]]


def test_direct_inconsistent_assertion_tuple_is_rejected_by_database(deployment):
    probe, _, _ = deployment
    probe.setup()
    result = probe.sql(
        (
            "INSERT INTO assertion VALUES (?,?,?,?,?,?)",
            (
                uuid4().hex,
                probe.e,
                probe.e2,
                "HUMAN_REVIEWED_PROPOSAL",
                "uid:10004",
                "typed",
            ),
        )
    )
    assert not result["ok"]
    assert result["detail"] == "CHECK constraint failed: assertion_origin_binding"


def test_canonical_coordinates_and_revisions_survive_restart(deployment):
    probe, process, start = deployment
    value = locator()
    value["coordinate_system"] = "FUTURE_COORDINATE"
    value["coordinate_parts"] = [
        {"name": "z", "value": ""},
        {"name": "a", "value": "雪"},
    ]
    probe.ok(
        "verifier", "evidence", id="restart-evidence", locator=value, quote="retained"
    )
    probe.setup()
    assertion_id = uuid4().hex
    assert probe.call(
        "reviewer",
        "assertion",
        id=assertion_id,
        subject_id=probe.e,
        object_id=probe.e2,
        origin="HUMAN_REVIEWED_PROPOSAL",
    )["ok"]
    process.terminate()
    process.wait(timeout=10)
    Path(probe.socket).unlink()
    replacement = start()
    try:
        record = probe.ok("verifier", "get_evidence", id="restart-evidence")
        assert record["locator"]["coordinate_parts"] == [
            {"name": "a", "value": "雪"},
            {"name": "z", "value": ""},
        ]
        assert record["quote"] == "retained" and record["writer"] == "uid:10002"
        row = probe.sql(
            (
                "SELECT origin,writer_principal,writer_capability FROM assertion WHERE id=?",
                (assertion_id,),
            )
        )
        assert row["rows"] == [[["HUMAN_REVIEWED_PROPOSAL", "uid:10005", "reviewer"]]]
    finally:
        replacement.terminate()
        replacement.wait(timeout=10)
