import json

from historian.cli import main
from historian.libsql_store.profile import LIBSQL


def test_default_profile_is_exact_and_does_not_claim_deployment_conformance(capsys):
    assert main(["profile"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"backend": "libSQL", "profile": LIBSQL.name,
                      "version": LIBSQL.version, "digest": LIBSQL.digest}


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
