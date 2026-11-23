import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import UnixStreamServer
from urllib.parse import parse_qs, urlsplit

import pytest

from historian.dreaming_turns import DreamingTurnsAdapter, HttpResponse, http_fetch
from historian.source_adapter import (
    CoordinatePart,
    SourceCoordinate,
    SourceEnumerationError,
    SourceFailure,
    SourceFailureCode,
    SourcePointer,
    sha256_bytes,
)

TENANT = "synthetic-tenant"
TENANT_ID = "tnt_01SYNTHETICTENANT00000000"
OTHER_ID = "tnt_01SYNTHETICOTHER000000000"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FakeDreaming:
    """The slice of Dreaming's /v2 API the adapter uses, with synthetic turns."""

    def __init__(self, turns=3):
        self.turns = {}
        self.tenant_of = {}
        self.origin_of = {}
        self.forgotten = set()
        self.status = None
        self.lie_about_hash = False
        self.listing_tenant_ids = []   # tenant_id to report per listing call, then TENANT_ID
        self.requests = []
        for i in range(1, turns + 1):
            self.add(f"trn_{i:02d}", {"role": "user", "text": f"synthetic note {i}"}, seq=i)

    def add(self, turn_id, content, seq, tenant_id=TENANT_ID, origin="human"):
        self.turns[turn_id] = (seq, canonical(content))
        self.tenant_of[turn_id] = tenant_id
        self.origin_of[turn_id] = origin

    def __call__(self, method, path, body=None):
        self.requests.append(path)
        if self.status is not None:
            return HttpResponse(self.status, {}, b'{"error":{}}')
        url = urlsplit(path)
        parts = url.path.strip("/").split("/")
        if parts[:2] == ["v2", "tenants"] and parts[3:] == ["turns"]:
            if parts[2] != TENANT:
                return HttpResponse(404, {}, b"{}")
            q = parse_qs(url.query)
            after, limit = int(q.get("after_seq", ["0"])[0]), int(q.get("limit", ["100"])[0])
            rows = sorted((seq, tid, data) for tid, (seq, data) in self.turns.items()
                          if seq > after and self.tenant_of[tid] == TENANT_ID)[:limit]
            listing = [{"id": tid, "seq": seq, "kind": "message", "origin_class": self.origin_of[tid],
                        "content_sha256": hashlib.sha256(data).hexdigest(), "byte_length": len(data),
                        "ingested_at": "2026-11-23T00:00:00+00:00", "forgotten": tid in self.forgotten}
                       for seq, tid, data in rows]
            reported = self.listing_tenant_ids.pop(0) if self.listing_tenant_ids else TENANT_ID
            body = {"tenant": TENANT, "tenant_id": reported, "turns": listing,
                    "next": rows[-1][0] if len(rows) == limit else None}
            return HttpResponse(200, {}, json.dumps(body).encode())
        if parts[:2] == ["v2", "turns"] and parts[3:] == ["raw"]:
            tid = parts[2]
            if tid not in self.turns:
                return HttpResponse(404, {}, b"{}")
            if tid in self.forgotten:
                return HttpResponse(410, {}, b"{}")
            data = self.turns[tid][1]
            declared = "0" * 64 if self.lie_about_hash else hashlib.sha256(data).hexdigest()
            return HttpResponse(200, {"x-dreaming-content-sha256": declared,
                                      "x-dreaming-tenant-id": self.tenant_of[tid]}, data)
        return HttpResponse(404, {}, b"{}")


def adapter(fake=None, **kw):
    fake = fake or FakeDreaming()
    return DreamingTurnsAdapter(fake, TENANT, **kw), fake


def test_enumerates_turns_with_sha256_versions_and_tenant_instance():
    a, fake = adapter()
    records = list(a.enumerate_records())
    assert [r.record_id for r in records] == ["trn_01", "trn_02", "trn_03"]
    assert {r.source_system for r in records} == {"DREAMING_TURNS"}
    assert {r.source_instance_id for r in records} == {TENANT_ID}
    for r in records:
        assert r.version_hash == sha256_bytes(fake.turns[r.record_id][1]) and r.media_type == "application/json"


def test_enumeration_pages_and_skips_forgotten_turns():
    fake = FakeDreaming(turns=7)
    fake.forgotten.add("trn_04")
    a, _ = adapter(fake)
    a._PAGE = 2
    assert [r.record_id for r in a.enumerate_records()] == ["trn_01", "trn_02", "trn_03", "trn_05", "trn_06", "trn_07"]


def test_tenant_id_changing_between_pages_fails_enumeration():
    fake = FakeDreaming(turns=4)
    fake.listing_tenant_ids = [TENANT_ID, TENANT_ID, OTHER_ID]   # resolve, page 1, page 2
    a, _ = adapter(fake)
    a._PAGE = 2
    with pytest.raises(SourceEnumerationError) as err:
        list(a.enumerate_records())
    assert err.value.failure.code is SourceFailureCode.INTEGRITY_FAILURE


def test_origin_filter_limits_enumeration_not_verification():
    fake = FakeDreaming(turns=2)
    fake.add("trn_tool", {"tool": "ls", "result": "synthetic"}, seq=3, origin="tool")
    a, _ = adapter(fake, origin_classes=frozenset({"human"}))
    assert [r.record_id for r in a.enumerate_records()] == ["trn_01", "trn_02"]
    assert a.verify(a.pointer_for_record("trn_tool")).ok
    assert [r.record_id for r in adapter(fake)[0].enumerate_records()] == ["trn_01", "trn_02", "trn_tool"]
    with pytest.raises(ValueError):
        adapter(fake, origin_classes=frozenset())


def test_record_pointer_reads_and_verifies_exact_bytes():
    a, fake = adapter()
    pointer = a.pointer_for_record("trn_02")
    result = a.verify(pointer)
    assert result.ok and result.source.content == fake.turns["trn_02"][1]
    locator = a.locator_for(pointer)
    assert locator.versioned_source_key == ("DREAMING_TURNS", TENANT_ID, "trn_02", sha256_bytes(fake.turns["trn_02"][1]))


def test_field_pointer_addresses_canonical_json_value():
    a, _ = adapter()
    pointer = a.pointer_for_field("trn_01", "text")
    assert pointer.coordinate.coordinate_system == "JSON_POINTER"
    assert a.read(pointer) == canonical("synthetic note 1")
    assert isinstance(a.pointer_for_field("trn_01", "/missing"), SourceFailure)


def test_partial_byte_range_is_half_open():
    a, fake = adapter()
    whole = a.pointer_for_record("trn_01")
    part = SourcePointer(whole.source_system, whole.source_instance_id, whole.record_id, whole.version_hash,
                         SourceCoordinate.byte_range(0, 5))
    assert a.read(part) == fake.turns["trn_01"][1][:5]
    beyond = SourcePointer(whole.source_system, whole.source_instance_id, whole.record_id, whole.version_hash,
                           SourceCoordinate.byte_range(0, 10_000))
    assert a.read(beyond).code is SourceFailureCode.INVALID_POINTER


def test_changed_content_fails_closed_with_version_mismatch():
    a, fake = adapter()
    pointer = a.pointer_for_record("trn_01")
    fake.add("trn_01", {"role": "user", "text": "edited"}, seq=1)
    assert a.verify(pointer).failure.code is SourceFailureCode.VERSION_MISMATCH


def test_forgotten_turn_no_longer_verifies():
    a, fake = adapter()
    pointer = a.pointer_for_record("trn_03")
    fake.forgotten.add("trn_03")
    failure = a.verify(pointer).failure
    assert failure.code is SourceFailureCode.NOT_FOUND and "forgotten" in failure.detail


def test_bytes_that_do_not_match_the_declared_hash_fail_integrity():
    a, fake = adapter()
    a.pointer_for_record("trn_01")
    fake.lie_about_hash = True
    assert a.version_of(TENANT_ID, "trn_01").code is SourceFailureCode.INTEGRITY_FAILURE


def test_wrong_system_instance_or_foreign_tenant_record_fail_closed():
    fake = FakeDreaming()
    fake.add("trn_foreign", {"text": "other tenant"}, seq=99, tenant_id=OTHER_ID)
    a, _ = adapter(fake)
    good = a.pointer_for_record("trn_01")
    wrong_system = SourcePointer("TWITTER_EXPORT", good.source_instance_id, good.record_id, good.version_hash,
                                 good.coordinate)
    assert a.read(wrong_system).code is SourceFailureCode.INVALID_POINTER
    wrong_instance = SourcePointer(good.source_system, OTHER_ID, good.record_id, good.version_hash, good.coordinate)
    assert a.read(wrong_instance).code is SourceFailureCode.NOT_FOUND
    foreign = SourcePointer(good.source_system, TENANT_ID, "trn_foreign", sha256_bytes(fake.turns["trn_foreign"][1]),
                            SourceCoordinate.byte_range(0, 1))
    assert a.read(foreign).code is SourceFailureCode.NOT_FOUND


def test_unsupported_and_malformed_coordinates():
    a, _ = adapter()
    good = a.pointer_for_record("trn_01")
    line = SourcePointer(good.source_system, good.source_instance_id, good.record_id, good.version_hash,
                         SourceCoordinate("LINE", (CoordinatePart("start", "1"), CoordinatePart("end", "2"))))
    assert a.read(line).code is SourceFailureCode.UNSUPPORTED_COORDINATE
    relative = SourcePointer(good.source_system, good.source_instance_id, good.record_id, good.version_hash,
                             SourceCoordinate("JSON_POINTER", (CoordinatePart("path", "text"),)))
    assert a.read(relative).code is SourceFailureCode.INVALID_POINTER


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_refused_or_failing_api_is_unavailable_and_enumeration_raises(status):
    a, fake = adapter()
    pointer = a.pointer_for_record("trn_01")
    fake.status = status
    assert a.verify(pointer).failure.code is SourceFailureCode.UNAVAILABLE
    with pytest.raises(SourceEnumerationError) as err:
        list(DreamingTurnsAdapter(fake, TENANT).enumerate_records())
    assert err.value.failure.code is SourceFailureCode.UNAVAILABLE


def test_unreachable_api_is_unavailable():
    def down(method, path, body=None):
        raise ConnectionRefusedError("synthetic")
    a = DreamingTurnsAdapter(down, TENANT)
    with pytest.raises(SourceEnumerationError) as err:
        list(a.enumerate_records())
    assert err.value.failure.code is SourceFailureCode.UNAVAILABLE


def test_pinned_source_instance_must_match_dreaming():
    a, _ = adapter(source_instance_id=OTHER_ID)
    with pytest.raises(SourceEnumerationError) as err:
        list(a.enumerate_records())
    assert err.value.failure.code is SourceFailureCode.INTEGRITY_FAILURE
    assert list(adapter(source_instance_id=TENANT_ID)[0].enumerate_records())


def test_from_env_requires_a_token():
    with pytest.raises(ValueError):
        DreamingTurnsAdapter.from_env({"DREAMING_URL": "http://127.0.0.1:9", "DREAMING_TENANT": TENANT})


# ---- the stdlib transport, against real sockets ----------------------------------------------------

def _handler(fake, seen):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.headers.get("Authorization"))
            resp = fake("GET", self.path)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            self.wfile.write(resp.body)

        def log_message(self, *a):
            pass
    return Handler


def test_http_transport_sends_the_bearer_token():
    fake, seen = FakeDreaming(), []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake, seen))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        a = DreamingTurnsAdapter(http_fetch(f"http://127.0.0.1:{server.server_address[1]}", "synthetic-token"), TENANT)
        assert a.verify(a.pointer_for_record("trn_02")).ok
        assert set(seen) == {"Bearer synthetic-token"}
    finally:
        server.shutdown()


class _UnixHTTPServer(UnixStreamServer):
    def get_request(self):
        request, _ = super().get_request()
        return request, ("local", 0)


def test_unix_socket_transport(tmp_path):
    fake, seen = FakeDreaming(), []
    path = str(tmp_path / "gateway.sock")
    server = _UnixHTTPServer(path, _handler(fake, seen))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        a = DreamingTurnsAdapter(http_fetch(f"unix:{path}", "synthetic-token"), TENANT)
        assert [r.record_id for r in a.enumerate_records()] == ["trn_01", "trn_02", "trn_03"]
    finally:
        server.shutdown()
        server.server_close()
