"""Source adapter contracts for Historian intake.

Historian owns normalized provenance and qualification. Adapters own the source-specific
knowledge required to enumerate, address, read and verify external material. This module
defines only the shared contract; it does not parse ChatGPT exports, Google Takeout
archives, mailboxes, calendars, drives, JSON, ZIP files or any other concrete format.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


class SourceMaterialState(Enum):
    """Whether verified bytes are original source material or an explicit derivative."""

    ORIGINAL = "ORIGINAL"
    REDACTED = "REDACTED"


@dataclass(frozen=True, slots=True)
class SourcePointer:
    """Opaque pointer to exact material within one immutable source record version.

    The strings are deliberately adapter-defined. A line span, byte range, message id,
    calendar field or archive member path may require different coordinate semantics, but
    every verified pointer must still name the source system, logical record, immutable
    version and exact coordinate range.
    """

    source_system: str
    record_id: str
    version_hash: str
    coordinate_system: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _required(self.source_system, "SourcePointer.source_system")
        _required(self.record_id, "SourcePointer.record_id")
        _required(self.version_hash, "SourcePointer.version_hash")
        _required(self.coordinate_system, "SourcePointer.coordinate_system")
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid coordinate span {self.start}..{self.end}")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One logical external record available for intake."""

    source_system: str
    record_id: str
    version_hash: str
    display_name: str | None = None
    media_type: str | None = None
    byte_length: int | None = None

    def __post_init__(self) -> None:
        _required(self.source_system, "SourceRecord.source_system")
        _required(self.record_id, "SourceRecord.record_id")
        _required(self.version_hash, "SourceRecord.version_hash")
        if self.byte_length is not None and self.byte_length < 0:
            raise ValueError("SourceRecord.byte_length cannot be negative")


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    """Source bytes verified against a pointer and retained as the authority boundary."""

    pointer: SourcePointer
    content_hash: str
    content: bytes
    material_state: SourceMaterialState = SourceMaterialState.ORIGINAL
    redaction_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pointer, SourcePointer):
            raise TypeError("VerifiedSource.pointer must be a SourcePointer")
        _required(self.content_hash, "VerifiedSource.content_hash")
        if not isinstance(self.content, bytes):
            raise TypeError("VerifiedSource.content must be bytes")
        if not isinstance(self.material_state, SourceMaterialState):
            raise TypeError("VerifiedSource.material_state must be a SourceMaterialState")
        expected = hashlib.sha256(self.content).hexdigest()
        if self.content_hash != expected:
            raise ValueError("VerifiedSource.content_hash must match content bytes")
        if self.material_state is SourceMaterialState.REDACTED and not self.redaction_ref:
            raise ValueError("redacted source material requires redaction_ref")
        if self.material_state is SourceMaterialState.ORIGINAL and self.redaction_ref:
            raise ValueError("original source material cannot carry redaction_ref")

    @classmethod
    def from_bytes(
        cls,
        pointer: SourcePointer,
        content: bytes,
        *,
        material_state: SourceMaterialState = SourceMaterialState.ORIGINAL,
        redaction_ref: str | None = None,
    ) -> "VerifiedSource":
        return cls(
            pointer=pointer,
            content_hash=hashlib.sha256(content).hexdigest(),
            content=content,
            material_state=material_state,
            redaction_ref=redaction_ref,
        )


@dataclass(frozen=True, slots=True)
class NormalizedIntakeRecord:
    """Derived text ready to become an evidence candidate.

    Normalized text is useful for indexing, extraction and adjudication preparation, but
    it is never the authority. The source pointer and source hash remain the re-verifiable
    authority boundary.
    """

    source: VerifiedSource
    normalized_text: str
    normalized_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, VerifiedSource):
            raise TypeError("NormalizedIntakeRecord.source must be a VerifiedSource")
        _required(self.normalized_text, "NormalizedIntakeRecord.normalized_text")
        _required(self.normalized_hash, "NormalizedIntakeRecord.normalized_hash")
        expected = hashlib.sha256(self.normalized_text.encode("utf-8")).hexdigest()
        if self.normalized_hash != expected:
            raise ValueError("NormalizedIntakeRecord.normalized_hash must match text")

    @classmethod
    def from_text(cls, source: VerifiedSource, normalized_text: str) -> "NormalizedIntakeRecord":
        return cls(
            source=source,
            normalized_text=normalized_text,
            normalized_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        )


class SourceAdapter(Protocol):
    """Common contract for source-specific intake adapters."""

    source_system: str

    def enumerate_records(self) -> Iterable[SourceRecord]:
        """Yield stable logical records visible to this adapter."""
        ...

    def version_of(self, record_id: str) -> str | None:
        """Return the content-addressed version for a record, or None if unverifiable."""
        ...

    def read(self, pointer: SourcePointer) -> bytes | None:
        """Return exact bytes for a pointer, or None for any failed verification precheck."""
        ...

    def verify(self, pointer: SourcePointer) -> VerifiedSource | None:
        """Return verified source material, or None if the adapter cannot fail closed."""
        ...


__all__ = [
    "NormalizedIntakeRecord",
    "SourceAdapter",
    "SourceMaterialState",
    "SourcePointer",
    "SourceRecord",
    "VerifiedSource",
]
