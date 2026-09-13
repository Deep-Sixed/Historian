"""Regression checks for the publication boundary, with constructed fake values."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_release_guard", ROOT / "scripts/public_release_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize("content,rule", [
    ("/" + "home" + "/operator/source.md", "home-directory"),
    ("12345678" + "-1234" * 3 + "-123456789abc", "conversation-identifier"),
    (json.dumps({"conversation" + "_id": "example"}), "export-record"),
    ("-----BEGIN " + "PRIVATE KEY-----", "private-key"),
    ("ghp_" + "x" * 36, "credential"),
    ('password' + ' = "' + 'x' * 12 + '"', "credential-assignment"),
    ("https://" + "user:example-value@host.invalid", "credential-url"),
    ("192" + ".168.1.5", "private-network"),
    ("private-" + "fixture-marker", "known-private-marker"),
])
def test_prohibited_content_fails_without_echoing_value(content, rule):
    result = guard.findings("example.txt", content.encode())
    assert rule in result
    assert content not in repr(result)


@pytest.mark.parametrize("name", ["cases/packets/example.txt", "cases/new-report.json", "cases/synthetic/unreviewed.md"])
def test_unapproved_case_artifacts_fail_even_with_innocuous_text(name):
    assert "unapproved-case-artifact" in guard.findings(name, b"innocuous")


@pytest.mark.parametrize("name", ["export.zip", "mail.mbox", ".env", "historian.db-wal", "historian.db-shm"])
def test_prohibited_file_classes(name):
    assert "prohibited-file-class" in guard.findings(name, b"innocuous")


def test_binary_and_symlink_cannot_bypass_scanning(tmp_path):
    assert "unreviewed-binary" in guard.findings("image.dat", b"\xff\x00")
    target = tmp_path / "target.txt"
    target.write_text("public synthetic note")
    (tmp_path / "alias.txt").symlink_to(target)
    assert guard.scan(tmp_path, ["alias.txt"])[0]["rules"] == ["symlink"]


def test_public_source_and_service_paths_are_allowed():
    assert not guard.findings("example.py", b"socket = '/run/historian/historian.sock'\n")


def test_extracted_artifact_scan_returns_failure_without_disclosing_match(tmp_path):
    value = "ghp_" + "q" * 36
    (tmp_path / "example.txt").write_text(value)
    run = subprocess.run([sys.executable, str(ROOT / "scripts/public_release_guard.py"),
                          "--tree", str(tmp_path)], capture_output=True, text=True)
    assert run.returncode == 1
    assert json.loads(run.stdout)["status"] == "FAIL"
    assert value not in run.stdout + run.stderr


def test_supported_tree_passes_guard():
    run = subprocess.run([sys.executable, str(ROOT / "scripts/public_release_guard.py")],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["status"] == "PASS"
