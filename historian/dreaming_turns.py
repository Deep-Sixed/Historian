"""Dreaming turns adapter for the SourceAdapter v1 contract.

Dreaming (Deep-Sixed/Dreaming, memory store v2) records conversation and agent turns
for memory consolidation. This adapter makes those turns a Historian source:

```text
source_system      DREAMING_TURNS
source_instance_id Dreaming tenant public id (tnt_...); opaque, no PII
record_id          Dreaming turn public id (trn_...)
version_hash       SHA-256 of the turn's stored canonical JSON bytes
coordinates        BYTE_RANGE over those bytes, or JSON_POINTER into them
```

The adapter reads Dreaming's authenticated /v2 API with a read-scoped token. Every
read re-fetches the exact stored bytes from `/v2/turns/{id}/raw` and checks them three
ways: against the hash Dreaming declares, against the pointer's version hash, and
against the tenant the pointer names. A forgotten turn (HTTP 410) and an unreachable
or unauthorized API fail closed. Dreaming's own records stay the authority; Historian
gets verified bytes only. Model-produced Dreaming memories are not offered as sources.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceEnumerationError,
    SourceFailure,
    SourceFailureCode,
    SourcePointer,
    SourceRecord,
    SourceVerificationResult,
    VerifiedSource,
    sha256_bytes,
)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Fetch = Callable[[str, str, bytes | None], HttpResponse]


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float):
        super().__init__("dreaming", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def http_fetch(base_url: str, token: str, timeout: float = 10.0) -> Fetch:
    """A stdlib transport for `http://host:port` or `unix:/path/to/gateway.sock`."""
    if not token:
        raise ValueError("a Dreaming read token is required")
    if base_url.startswith("unix:"):
        socket_path, prefix = base_url[len("unix:"):], ""

        def connect() -> http.client.HTTPConnection:
            return _UnixHTTPConnection(socket_path, timeout)
    else:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("DREAMING_URL must be http(s)://host[:port] or unix:/path")
        prefix = parts.path.rstrip("/")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection

        def connect() -> http.client.HTTPConnection:
            return cls(parts.hostname, parts.port, timeout=timeout)

    def fetch(method: str, path: str, body: bytes | None = None) -> HttpResponse:
        conn = connect()
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, prefix + path, body=body, headers=headers)
            resp = conn.getresponse()
            return HttpResponse(resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read())
        finally:
            conn.close()

    return fetch


class DreamingTurnsAdapter:
    """Reads one Dreaming tenant's turns as Historian source records."""

    source_system = "DREAMING_TURNS"
    _PAGE = 500

    def __init__(self, fetch: Fetch, tenant: str, source_instance_id: str | None = None, *,
                 origin_classes: frozenset[str] | None = None):
        """`origin_classes` limits enumeration to turns of those Dreaming origins, e.g.
        `frozenset({"human"})` to take in only what a person typed. Verification of an
        explicit pointer is unaffected: provenance does not depend on the filter."""
        if not tenant:
            raise ValueError("tenant is required")
        if source_instance_id is not None and not source_instance_id:
            raise ValueError("source_instance_id cannot be empty")
        self._fetch = fetch
        self._tenant = tenant
        self._expected_instance = source_instance_id
        self._instance: str | None = None
        if origin_classes is not None and not origin_classes:
            raise ValueError("origin_classes cannot be empty; pass None for all origins")
        self._origins = origin_classes

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DreamingTurnsAdapter":
        """`DREAMING_URL`, `DREAMING_TOKEN` (read scope), `DREAMING_TENANT`, optional
        `DREAMING_SOURCE_INSTANCE_ID` to pin the expected tenant id, optional
        `DREAMING_ORIGIN_CLASSES` (comma-separated) to limit enumeration."""
        env = os.environ if environ is None else environ
        fetch = http_fetch(env.get("DREAMING_URL", ""), env.get("DREAMING_TOKEN", ""))
        origins = frozenset(o.strip() for o in env.get("DREAMING_ORIGIN_CLASSES", "").split(",") if o.strip())
        return cls(fetch, env.get("DREAMING_TENANT", ""), env.get("DREAMING_SOURCE_INSTANCE_ID") or None,
                   origin_classes=origins or None)

    @property
    def source_instance_id(self) -> str:
        instance = self._resolve_instance()
        if isinstance(instance, SourceFailure):
            raise SourceEnumerationError(instance)
        return instance

    # ---- SourceAdapter ------------------------------------------------------------------

    def enumerate_records(self) -> Iterator[SourceRecord]:
        instance = self._resolve_instance()
        if isinstance(instance, SourceFailure):
            raise SourceEnumerationError(instance)
        records = []
        after = 0
        while True:
            page = self._json("GET", f"/v2/tenants/{quote(self._tenant, safe='')}/turns?"
                              + urlencode({"after_seq": after, "limit": self._PAGE}))
            if isinstance(page, SourceFailure):
                raise SourceEnumerationError(page)
            if page.get("tenant_id") != instance:
                raise SourceEnumerationError(SourceFailure(
                    SourceFailureCode.INTEGRITY_FAILURE, "tenant id changed during enumeration"))
            try:
                for turn in page["turns"]:
                    if turn["forgotten"] or (self._origins is not None and turn["origin_class"] not in self._origins):
                        continue
                    records.append(SourceRecord(
                        self.source_system, instance, turn["id"], turn["content_sha256"],
                        display_name=f"{turn['kind']} {turn['origin_class']} {turn['ingested_at']}",
                        media_type="application/json", byte_length=int(turn["byte_length"])))
                next_seq = page["next"]
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceEnumerationError(SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE, f"turn listing is malformed: {exc}")) from None
            if next_seq is None:
                return iter(records)
            if not isinstance(next_seq, int) or next_seq <= after:
                raise SourceEnumerationError(SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE, "turn listing cursor did not advance"))
            after = next_seq

    def version_of(self, source_instance_id: str, record_id: str) -> str | SourceFailure:
        raw = self._raw(source_instance_id, record_id)
        return raw if isinstance(raw, SourceFailure) else sha256_bytes(raw)

    def read(self, pointer: SourcePointer) -> bytes | SourceFailure:
        if pointer.source_system != self.source_system:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "wrong source system")
        content = self._raw(pointer.source_instance_id, pointer.record_id)
        if isinstance(content, SourceFailure):
            return content
        if sha256_bytes(content) != pointer.version_hash:
            return SourceFailure(SourceFailureCode.VERSION_MISMATCH, "record version changed")
        system = pointer.coordinate.coordinate_system
        parts = {part.name: part.value for part in pointer.coordinate.parts}
        if system == "BYTE_RANGE":
            try:
                start, end = int(parts["start"]), int(parts["end"])
            except (KeyError, ValueError):
                return SourceFailure(SourceFailureCode.INVALID_POINTER, "BYTE_RANGE requires numeric start/end")
            if set(parts) != {"start", "end"} or start < 0 or end < start:
                return SourceFailure(SourceFailureCode.INVALID_POINTER, "invalid byte range")
            if end > len(content):
                return SourceFailure(SourceFailureCode.INVALID_POINTER, "span is outside source")
            return content[start:end]
        if system == "JSON_POINTER":
            if set(parts) != {"path"}:
                return SourceFailure(SourceFailureCode.INVALID_POINTER, "JSON_POINTER requires path")
            try:
                value = _resolve_json_pointer(json.loads(content), parts["path"])
            except (KeyError, TypeError, ValueError) as exc:
                return SourceFailure(SourceFailureCode.INVALID_POINTER, str(exc))
            return _canonical_bytes(value)
        return SourceFailure(SourceFailureCode.UNSUPPORTED_COORDINATE,
                             "coordinate system is not supported for Dreaming turns")

    def verify(self, pointer: SourcePointer) -> SourceVerificationResult:
        read = self.read(pointer)
        if isinstance(read, SourceFailure):
            return SourceVerificationResult(failure=read)
        return SourceVerificationResult.verified(VerifiedSource.from_bytes(pointer, read))

    # ---- helpers matching the other adapters --------------------------------------------------

    def pointer_for_record(self, record_id: str) -> SourcePointer | SourceFailure:
        instance = self._resolve_instance()
        if isinstance(instance, SourceFailure):
            return instance
        content = self._raw(instance, record_id)
        if isinstance(content, SourceFailure):
            return content
        return SourcePointer(self.source_system, instance, record_id, sha256_bytes(content),
                             SourceCoordinate.byte_range(0, len(content)))

    def pointer_for_field(self, record_id: str, field_path: str) -> SourcePointer | SourceFailure:
        instance = self._resolve_instance()
        if isinstance(instance, SourceFailure):
            return instance
        content = self._raw(instance, record_id)
        if isinstance(content, SourceFailure):
            return content
        path = field_path if field_path == "" or field_path.startswith("/") else f"/{field_path}"
        try:
            _resolve_json_pointer(json.loads(content), path)
        except (KeyError, TypeError, ValueError) as exc:
            return SourceFailure(SourceFailureCode.NOT_FOUND, str(exc))
        return SourcePointer(self.source_system, instance, record_id, sha256_bytes(content),
                             SourceCoordinate("JSON_POINTER", (CoordinatePart("path", path),)))

    def locator_for(self, pointer: SourcePointer) -> EvidenceLocator | SourceFailure:
        result = self.verify(pointer)
        if result.failure is not None:
            return result.failure
        return EvidenceLocator.from_verified_source(result.source)

    # ---- Dreaming API --------------------------------------------------------------------------

    def _resolve_instance(self) -> str | SourceFailure:
        if self._instance is not None:
            return self._instance
        page = self._json("GET", f"/v2/tenants/{quote(self._tenant, safe='')}/turns?limit=1")
        if isinstance(page, SourceFailure):
            return page
        instance = page.get("tenant_id") if isinstance(page, dict) else None
        if not isinstance(instance, str) or not instance:
            return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, "turn listing has no tenant_id")
        if self._expected_instance is not None and instance != self._expected_instance:
            return SourceFailure(SourceFailureCode.INTEGRITY_FAILURE,
                                 "Dreaming tenant id does not match the configured source instance")
        self._instance = instance
        return instance

    def _raw(self, source_instance_id: str, record_id: str) -> bytes | SourceFailure:
        instance = self._resolve_instance()
        if isinstance(instance, SourceFailure):
            return instance
        if source_instance_id != instance:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "source instance is unknown")
        resp = self._call("GET", f"/v2/turns/{quote(record_id, safe='')}/raw")
        if isinstance(resp, SourceFailure):
            return resp
        if resp.headers.get("x-dreaming-tenant-id") != instance:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "record belongs to another source instance")
        declared = resp.headers.get("x-dreaming-content-sha256", "")
        if sha256_bytes(resp.body) != declared:
            return SourceFailure(SourceFailureCode.INTEGRITY_FAILURE, "bytes do not match the declared hash")
        try:
            json.loads(resp.body)
        except ValueError:
            return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, "turn bytes are not JSON")
        return resp.body

    def _json(self, method: str, path: str) -> Any:
        resp = self._call(method, path)
        if isinstance(resp, SourceFailure):
            return resp
        try:
            return json.loads(resp.body)
        except ValueError:
            return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, "Dreaming returned non-JSON")

    def _call(self, method: str, path: str) -> HttpResponse | SourceFailure:
        try:
            resp = self._fetch(method, path, None)
        except (OSError, http.client.HTTPException) as exc:
            return SourceFailure(SourceFailureCode.UNAVAILABLE, f"Dreaming API unreachable: {type(exc).__name__}")
        if resp.status == 200:
            return resp
        if resp.status == 404:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "record is unknown")
        if resp.status == 410:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "record was forgotten in Dreaming")
        if resp.status in (401, 403):
            return SourceFailure(SourceFailureCode.UNAVAILABLE, f"Dreaming refused the token (HTTP {resp.status})")
        return SourceFailure(SourceFailureCode.UNAVAILABLE, f"Dreaming returned HTTP {resp.status}")


def _resolve_json_pointer(value: Any, path: str) -> Any:
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError("JSON pointer must be absolute")
    current = value
    for raw_part in path[1:].split("/"):
        part = _decode_json_pointer_token(raw_part)
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            if not part or not all("0" <= char <= "9" for char in part):
                raise ValueError("JSON pointer array index must be a non-negative decimal")
            if len(part) > 1 and part.startswith("0"):
                raise ValueError("JSON pointer array index must not contain leading zeros")
            index = int(part)
            if index >= len(current):
                raise ValueError("JSON pointer array index is out of range")
            current = current[index]
        else:
            raise TypeError("JSON pointer descends through a scalar")
    return current


def _decode_json_pointer_token(token: str) -> str:
    decoded = []
    index = 0
    while index < len(token):
        char = token[index]
        if char != "~":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ValueError("JSON pointer token contains an invalid escape")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["DreamingTurnsAdapter", "HttpResponse", "http_fetch"]
