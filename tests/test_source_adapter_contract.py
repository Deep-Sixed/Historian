import hashlib

import pytest

from historian.source_adapter import (
    NormalizedIntakeRecord,
    SourceMaterialState,
    SourcePointer,
    SourceRecord,
    VerifiedSource,
)


def ptr(system="CHATGPT_EXPORT"):
    return SourcePointer(system, "conversation-1", "version-1", "BYTE", 0, 12)


def test_source_pointer_requires_exact_versioned_coordinates():
    with pytest.raises(ValueError, match="version_hash"):
        SourcePointer("CHATGPT_EXPORT", "conversation-1", "", "BYTE", 0, 12)
    with pytest.raises(ValueError, match="invalid coordinate span"):
        SourcePointer("CHATGPT_EXPORT", "conversation-1", "version-1", "BYTE", 12, 0)


def test_source_record_requires_stable_identity_and_version():
    rec = SourceRecord("GOOGLE_TAKEOUT_GMAIL", "message-1", "version-1")
    assert rec.source_system == "GOOGLE_TAKEOUT_GMAIL"
    with pytest.raises(ValueError, match="record_id"):
        SourceRecord("GOOGLE_TAKEOUT_GMAIL", "", "version-1")


def test_verified_source_hashes_the_authoritative_bytes():
    src = VerifiedSource.from_bytes(ptr(), b"source bytes")
    assert src.content_hash == hashlib.sha256(b"source bytes").hexdigest()
    with pytest.raises(ValueError, match="content_hash"):
        VerifiedSource(ptr(), "not-the-hash", b"source bytes")


def test_redacted_material_cannot_masquerade_as_original_bytes():
    with pytest.raises(ValueError, match="redaction_ref"):
        VerifiedSource.from_bytes(
            ptr(),
            b"redacted source bytes",
            material_state=SourceMaterialState.REDACTED,
        )
    with pytest.raises(ValueError, match="original source material"):
        VerifiedSource.from_bytes(ptr(), b"source bytes", redaction_ref="redaction-1")


def test_normalized_intake_is_derived_from_verified_source():
    src = VerifiedSource.from_bytes(ptr(), b"raw source bytes")
    intake = NormalizedIntakeRecord.from_text(src, "normalized text")
    assert intake.source is src
    assert intake.normalized_hash == hashlib.sha256(b"normalized text").hexdigest()
    assert intake.source.content != intake.normalized_text.encode()
