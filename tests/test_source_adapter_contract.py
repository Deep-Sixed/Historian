from dataclasses import replace

import pytest

from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    NormalizedIntakeRecord,
    SourceCoordinate,
    SourceFailure,
    SourceFailureCode,
    SourceMaterialState,
    SourcePointer,
    SourceRecord,
    SourceVerificationResult,
    VerifiedSource,
    sha256_bytes,
)


class MemoryAdapter:
    source_system = "MEMORY_EXPORT"

    def __init__(self, source_instance_id="instance-1", records=None):
        self.source_instance_id = source_instance_id
        self._records = dict(records or {"record-1": b"alpha beta gamma"})

    def enumerate_records(self):
        for record_id, content in sorted(self._records.items()):
            yield SourceRecord(
                self.source_system,
                self.source_instance_id,
                record_id,
                sha256_bytes(content),
                byte_length=len(content),
            )

    def version_of(self, source_instance_id, record_id):
        if source_instance_id != self.source_instance_id:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "source instance is unknown")
        content = self._records.get(record_id)
        if content is None:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "record is unknown")
        return sha256_bytes(content)

    def read(self, pointer):
        failure = self._precheck(pointer)
        if failure:
            return failure
        parts = {part.name: int(part.value) for part in pointer.coordinate.parts}
        content = self._records[pointer.record_id]
        start = parts["start"]
        end = parts["end"]
        if end > len(content):
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "span is outside source")
        return content[start:end]

    def verify(self, pointer):
        read = self.read(pointer)
        if isinstance(read, SourceFailure):
            return SourceVerificationResult(failure=read)
        return SourceVerificationResult.verified(VerifiedSource.from_bytes(pointer, read))

    def _precheck(self, pointer):
        if pointer.source_system != self.source_system:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "wrong source system")
        version = self.version_of(pointer.source_instance_id, pointer.record_id)
        if isinstance(version, SourceFailure):
            return version
        if pointer.version_hash != version:
            return SourceFailure(SourceFailureCode.VERSION_MISMATCH, "record version changed")
        if pointer.coordinate.coordinate_system != "BYTE_RANGE":
            return SourceFailure(
                SourceFailureCode.UNSUPPORTED_COORDINATE,
                "only BYTE_RANGE is supported",
            )
        return None


def ptr(adapter=None, record_id="record-1", start=0, end=5):
    adapter = adapter or MemoryAdapter()
    version = adapter.version_of(adapter.source_instance_id, record_id)
    assert isinstance(version, str)
    return SourcePointer(
        adapter.source_system,
        adapter.source_instance_id,
        record_id,
        version,
        SourceCoordinate.byte_range(start, end),
    )


def test_source_pointer_identity_includes_instance_and_sha256_version():
    adapter = MemoryAdapter()
    pointer = ptr(adapter)
    assert pointer.source_instance_id == "instance-1"
    with pytest.raises(ValueError, match="version_hash"):
        SourcePointer(
            "CHATGPT_EXPORT",
            "export-1",
            "conversation-1",
            "version-1",
            SourceCoordinate.byte_range(0, 12),
        )


def test_source_coordinate_supports_non_linear_adapter_owned_selectors():
    coord = SourceCoordinate(
        "ICAL_PROPERTY",
        (CoordinatePart("event_uid", "evt-1"), CoordinatePart("property", "SUMMARY")),
    )
    pointer = SourcePointer("GOOGLE_TAKEOUT_CALENDAR", "acct-fp", "evt-1", "0" * 64, coord)
    assert pointer.coordinate.coordinate_system == "ICAL_PROPERTY"


def test_source_record_requires_stable_identity_instance_and_version():
    rec = SourceRecord("GOOGLE_TAKEOUT_GMAIL", "acct-fp", "message-1", "0" * 64)
    assert rec.source_instance_id == "acct-fp"
    with pytest.raises(ValueError, match="source_instance_id"):
        SourceRecord("GOOGLE_TAKEOUT_GMAIL", "", "message-1", "0" * 64)


def test_verified_source_hashes_the_authoritative_bytes():
    source = VerifiedSource.from_bytes(ptr(), b"alpha")
    assert source.content_hash == sha256_bytes(b"alpha")
    with pytest.raises(ValueError, match="content_hash"):
        VerifiedSource(ptr(), "0" * 64, b"source bytes")


def test_redacted_material_cannot_masquerade_as_original_bytes():
    with pytest.raises(ValueError, match="redaction_ref"):
        VerifiedSource.from_bytes(
            ptr(),
            b"redacted source bytes",
            material_state=SourceMaterialState.REDACTED,
        )
    with pytest.raises(ValueError, match="original source material"):
        VerifiedSource.from_bytes(ptr(), b"source bytes", redaction_ref="redaction-1")


def test_evidence_locator_bridges_adapter_provenance_without_collapsing_to_other():
    verified = MemoryAdapter().verify(ptr()).source
    locator = EvidenceLocator.from_verified_source(verified)
    assert locator.logical_source_key == ("MEMORY_EXPORT", "instance-1", "record-1")
    assert locator.versioned_source_key == (
        "MEMORY_EXPORT",
        "instance-1",
        "record-1",
        sha256_bytes(b"alpha beta gamma"),
    )


def test_normalized_intake_is_derived_from_evidence_locator():
    verified = MemoryAdapter().verify(ptr()).source
    locator = EvidenceLocator.from_verified_source(verified)
    intake = NormalizedIntakeRecord.from_text(locator, "normalized text")
    assert intake.locator is locator
    assert intake.normalized_hash != intake.locator.content_hash


def test_memory_adapter_is_idempotent_for_repeated_imports():
    adapter = MemoryAdapter()
    first = tuple(adapter.enumerate_records())
    second = tuple(adapter.enumerate_records())
    assert first == second


def test_memory_adapter_mutated_source_gets_new_version_and_old_pointer_fails_closed():
    adapter = MemoryAdapter(records={"record-1": b"alpha beta gamma"})
    old = ptr(adapter)
    mutated = MemoryAdapter(records={"record-1": b"alpha beta delta"})
    assert mutated.version_of("instance-1", "record-1") != old.version_hash
    result = mutated.verify(old)
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.VERSION_MISMATCH


def test_memory_adapter_rejects_wrong_source_system():
    adapter = MemoryAdapter()
    pointer = replace(ptr(adapter), source_system="OTHER_ADAPTER")
    result = adapter.verify(pointer)
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.INVALID_POINTER


def test_memory_adapter_rejects_outside_span():
    adapter = MemoryAdapter()
    result = adapter.verify(ptr(adapter, start=0, end=1000))
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.INVALID_POINTER


def test_memory_adapter_rejects_unsupported_coordinate():
    adapter = MemoryAdapter()
    pointer = replace(
        ptr(adapter),
        coordinate=SourceCoordinate("JSON_POINTER", (CoordinatePart("path", "/x"),)),
    )
    result = adapter.verify(pointer)
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.UNSUPPORTED_COORDINATE
