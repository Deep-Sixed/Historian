"""Linux deployment proof. Run only inside the disposable profile container as root."""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from enum import Enum
from pathlib import Path

import pytest

pytest.importorskip("libsql")
from libsql_probe import ROLES, LibSQLProbe, locator

from historian.libsql_store.profile import LIBSQL
from historian.persistence.catalog import CATALOG
from historian.persistence.contract import ConformanceHarness, Status

pytestmark = pytest.mark.libsql


@pytest.fixture(scope="module")
def deployment():
    if os.environ.get("HISTORIAN_RUN_LIBSQL") != "1":
        pytest.skip(
            "requires disposable Linux profile deployment; see deployment/libsql/Dockerfile"
        )
    assert sys.platform == "linux" and os.getuid() == 0, (
        "run in disposable profile container as root"
    )
    root = Path(tempfile.mkdtemp(prefix="historian-libsql-", dir="/tmp"))
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
                "historian.libsql_store.service",
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
    probe = LibSQLProbe(database, socket, corpus)
    probe.boundary_evidence = []
    try:
        yield probe, process, start
    finally:
        process.terminate()
        process.wait(timeout=10)
        Path("/tmp/historian-libsql-boundaries.json").write_text(
            json.dumps(
                {
                    "profile_name": LIBSQL.name,
                    "profile_version": LIBSQL.version,
                    "profile_digest": LIBSQL.digest,
                    "evidence": probe.boundary_evidence,
                },
                indent=2,
            )
        )


def test_libsql_profile_conformance(deployment):
    probe, _, _ = deployment
    report = ConformanceHarness(CATALOG).run(LIBSQL, probe)
    destination = Path(
        os.environ.get(
            "HISTORIAN_LIBSQL_REPORT", "/tmp/historian-libsql-conformance.json"
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
    assert failures == {"PV17.normal", "PV17.bypass"}
    assert report.status is Status.DOES_NOT_CONFORM
    assert len(report.evidence) == 43
    assert all(e.profile_digest == LIBSQL.digest for e in report.evidence)


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
            "operation": "raw_libsql_delete",
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
    for operation in ("raw_sql", "set_role", "finalize", "delete", "update"):
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
    finally:
        replacement.terminate()
        replacement.wait(timeout=10)
