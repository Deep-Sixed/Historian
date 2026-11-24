import json

from historian.cli import main
from historian.libsql_store.profile import CERTIFIED_RUNTIME, SQLITE


def test_default_profile_is_exact_and_does_not_claim_deployment_conformance(capsys):
    assert main(["profile"]) == 0
    result = json.loads(capsys.readouterr().out)
    runtime = result.pop("runtime")
    certified = result.pop("runtime_is_certified")
    assert result == {"backend": "SQLite", "profile": SQLITE.name,
                      "version": 4, "digest": SQLITE.digest}
    assert set(runtime) == {"python", "sqlite"}
    assert certified == (runtime == CERTIFIED_RUNTIME)


def test_migrate_requires_service_uid(tmp_path, monkeypatch):
    import os
    import pytest
    monkeypatch.setattr(os, "getuid", lambda: 10001)
    with pytest.raises(SystemExit):
        main(["migrate", "--source", str(tmp_path / "a.db"),
              "--destination", str(tmp_path / "b.db")])


def test_request_preserves_service_denial(tmp_path, monkeypatch, capsys):
    from historian.libsql_store import client
    path = tmp_path / "request.json"
    path.write_text('{"id":"q"}')
    calls = []
    def denied(socket, operation, data):
        calls.append((socket, operation, data))
        return {"ok": False, "error": "forbidden"}
    monkeypatch.setattr(client, "request", denied)
    assert main(["request", "question", "--data-file", str(path)]) == 1
    assert calls == [("/run/historian/historian.sock", "question", {"id": "q"})]
    assert json.loads(capsys.readouterr().out)["error"] == "forbidden"
