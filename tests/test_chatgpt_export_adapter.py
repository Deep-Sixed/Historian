import json
import zipfile
from dataclasses import replace

import pytest

from historian.chatgpt_export import ChatGPTExportAdapter
from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceFailure,
    SourceFailureCode,
    SourcePointer,
    SourceVerificationResult,
    VerifiedSource,
    sha256_bytes,
)


def write_export(root, conversations, *, user=None):
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(conversations), encoding="utf-8")
    if user is not None:
        (root / "user.json").write_text(json.dumps(user), encoding="utf-8")
    return root


def conversation(cid="conv-1", title="Fixture conversation", content="hello world"):
    return {
        "id": cid,
        "title": title,
        "mapping": {
            "node-1": {
                "message": {
                    "id": "message-1",
                    "author": {"role": "user"},
                    "content": {"parts": [content]},
                }
            }
        },
    }


def adapter_for(tmp_path, conversations=None, *, user=None, instance_id=None):
    export = write_export(
        tmp_path / "export",
        conversations or [conversation()],
        user=user or {"id": "account-1"},
    )
    return ChatGPTExportAdapter(export, source_instance_id=instance_id)


def full_pointer(adapter, record_id="conv-1"):
    pointer = adapter.pointer_for_record(record_id)
    assert isinstance(pointer, SourcePointer)
    return pointer


def test_enumerates_stable_conversation_records(tmp_path):
    adapter = adapter_for(
        tmp_path,
        [conversation("conv-b"), conversation("conv-a")],
        instance_id="instance-fixed",
    )

    records = tuple(adapter.enumerate_records())

    assert [record.record_id for record in records] == ["conv-a", "conv-b"]
    assert {record.source_instance_id for record in records} == {"instance-fixed"}
    assert all(
        record.version_hash == adapter.version_of("instance-fixed", record.record_id)
        for record in records
    )


def test_source_instance_id_is_deterministic_from_export_identity(tmp_path):
    first = adapter_for(tmp_path / "first", user={"id": "account-1"})
    second = adapter_for(tmp_path / "second", user={"id": "account-1"})
    other = adapter_for(tmp_path / "other", user={"id": "account-2"})

    assert first.source_instance_id == second.source_instance_id
    assert first.source_instance_id != other.source_instance_id


def test_empty_source_instance_override_is_rejected(tmp_path):
    export = write_export(tmp_path / "export", [conversation()])

    with pytest.raises(ValueError, match="source_instance_id"):
        ChatGPTExportAdapter(export, source_instance_id="")


def test_pointer_reads_and_verifies_exact_source_bytes(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)
    result = adapter.verify(pointer)

    assert isinstance(result, SourceVerificationResult)
    assert result.ok is True
    assert isinstance(result.source, VerifiedSource)
    assert result.source.pointer == pointer
    assert result.source.content_hash == sha256_bytes(result.source.content)


def test_partial_byte_pointer_uses_zero_based_half_open_range(tmp_path):
    adapter = adapter_for(tmp_path)
    full = full_pointer(adapter)
    pointer = replace(full, coordinate=SourceCoordinate.byte_range(0, 7))

    result = adapter.verify(pointer)

    assert result.ok is True
    assert result.source.content == adapter.read(full)[:7]


def test_locator_is_produced_from_verified_chatgpt_source(tmp_path):
    adapter = adapter_for(tmp_path)
    locator = adapter.locator_for(full_pointer(adapter))

    assert isinstance(locator, EvidenceLocator)
    assert locator.source_system == "CHATGPT_EXPORT"
    assert locator.source_instance_id == adapter.source_instance_id
    assert locator.record_id == "conv-1"


def test_repeated_imports_are_idempotent(tmp_path):
    conversations = [conversation("conv-1"), conversation("conv-2")]
    first = adapter_for(tmp_path / "first", conversations, user={"id": "account-1"})
    second = adapter_for(tmp_path / "second", conversations, user={"id": "account-1"})

    assert tuple(first.enumerate_records()) == tuple(second.enumerate_records())


def test_mutated_source_gets_new_version_and_old_pointer_fails_closed(tmp_path):
    original = adapter_for(tmp_path / "original", [conversation(content="old")])
    old_pointer = full_pointer(original)
    mutated = adapter_for(tmp_path / "mutated", [conversation(content="new")])

    assert mutated.version_of(mutated.source_instance_id, "conv-1") != old_pointer.version_hash
    result = mutated.verify(old_pointer)
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.VERSION_MISMATCH


def test_wrong_adapter_wrong_instance_and_wrong_version_fail_closed(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)

    wrong_adapter = adapter.verify(replace(pointer, source_system="GOOGLE_TAKEOUT_GMAIL"))
    wrong_instance = adapter.verify(replace(pointer, source_instance_id="other-instance"))
    wrong_version = adapter.verify(replace(pointer, version_hash="0" * 64))

    assert wrong_adapter.failure.code is SourceFailureCode.INVALID_POINTER
    assert wrong_instance.failure.code is SourceFailureCode.NOT_FOUND
    assert wrong_version.failure.code is SourceFailureCode.VERSION_MISMATCH


def test_rejects_invalid_or_unsupported_coordinates(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)

    unsupported = adapter.verify(
        replace(
            pointer,
            coordinate=SourceCoordinate("JSON_POINTER", (CoordinatePart("path", "/x"),)),
        )
    )
    invalid = adapter.verify(
        replace(pointer, coordinate=SourceCoordinate("BYTE_RANGE", (CoordinatePart("start", "0"),)))
    )
    outside = adapter.verify(replace(pointer, coordinate=SourceCoordinate.byte_range(0, 999999)))

    assert unsupported.failure.code is SourceFailureCode.UNSUPPORTED_COORDINATE
    assert invalid.failure.code is SourceFailureCode.INVALID_POINTER
    assert outside.failure.code is SourceFailureCode.INVALID_POINTER


def test_missing_or_malformed_exports_fail_closed(tmp_path):
    missing = ChatGPTExportAdapter(tmp_path / "missing")
    bad = write_export(tmp_path / "bad", [])
    (bad / "conversations.json").write_text("{not json", encoding="utf-8")

    assert isinstance(missing.version_of(missing.source_instance_id, "conv-1"), SourceFailure)
    failure = ChatGPTExportAdapter(bad).version_of(ChatGPTExportAdapter(bad).source_instance_id, "x")
    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.MALFORMED_SOURCE


def test_rejects_duplicate_conversation_ids(tmp_path):
    adapter = adapter_for(tmp_path, [conversation("dup"), conversation("dup")])
    failure = adapter.version_of(adapter.source_instance_id, "dup")

    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.INTEGRITY_FAILURE


def test_rejects_archive_member_escape(tmp_path):
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("conversations.json", json.dumps([conversation()]))
        archive.writestr("../escape.txt", "nope")

    adapter = ChatGPTExportAdapter(archive_path, source_instance_id="instance-fixed")
    failure = adapter.version_of("instance-fixed", "conv-1")

    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.INTEGRITY_FAILURE


def test_reads_zip_export_without_extracting(tmp_path):
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("user.json", json.dumps({"id": "account-1"}))
        archive.writestr("conversations.json", json.dumps([conversation()]))

    adapter = ChatGPTExportAdapter(archive_path)
    result = adapter.verify(full_pointer(adapter))

    assert result.ok is True
    assert result.source.pointer.source_system == "CHATGPT_EXPORT"


def test_zip_export_without_user_json_uses_path_fallback_identity(tmp_path):
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("conversations.json", json.dumps([conversation()]))

    adapter = ChatGPTExportAdapter(archive_path)

    assert adapter.verify(full_pointer(adapter)).ok is True
