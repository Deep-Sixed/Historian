"""Source adapter contracts for Historian intake.

Historian owns normalized provenance and qualification. Adapters own the source-specific
knowledge required to enumerate, address, read and verify external material. This module
defines only the shared contract; it does not parse ChatGPT exports, Google Takeout
archives, mailboxes, calendars, drives, JSON, ZIP files or any other concrete format.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol


SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _sha256(value: str, field_name: str) -> str:
    _required(value, field_name)
    if not SHA256_HEX.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SourceMaterialState(Enum):
    """Whether verified bytes are original source material or an explicit derivative."""

    ORIGINAL = "ORIGINAL"
    REDACTED = "REDACTED"


class SourceFailureCode(Enum):
    """Typed fail-closed reasons for adapter operations."""

    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    INVALID_POINTER = "INVALID_POINTER"
    UNSUPPORTED_COORDINATE = "UNSUPPORTED_COORDINATE"
    MALFORMED_SOURCE = "MALFORMED_SOURCE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


@dataclass(frozen=True, slots=True)
class SourceFailure:
    """A precise rejection reason that still produces no verified evidence."""

    code: SourceFailureCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, SourceFailureCode):
            raise TypeError("SourceFailure.code must be a SourceFailureCode")
        _required(self.detail, "SourceFailure.detail")


@dataclass(frozen=True, slots=True)
class CoordinatePart:
    """One source-owned coordinate component."""

    name: str
    value: str

    def __post_init__(self) -> None:
        _required(self.name, "CoordinatePart.name")
        _required(self.value, "CoordinatePart.value")


@dataclass(frozen=True, slots=True)
class SourceCoordinate:
    """Adapter-owned coordinate shape for exact material within a record version."""

    coordinate_system: str
    parts: tuple[CoordinatePart, ...]

    def __post_init__(self) -> None:
        _required(self.coordinate_system, "SourceCoordinate.coordinate_system")
        if not self.parts:
            raise ValueError("SourceCoordinate.parts is required")
        names = set()
        for part in self.parts:
            if not isinstance(part, CoordinatePart):
                raise TypeError("SourceCoordinate.parts must contain CoordinatePart values")
            if part.name in names:
                raise ValueError(f"duplicate coordinate part {part.name!r}")
            names.add(part.name)
        canonical = tuple(sorted(self.parts, key=lambda p: p.name))
        if self.parts != canonical:
            object.__setattr__(self, "parts", canonical)

    @classmethod
    def byte_range(cls, start: int, end: int) -> "SourceCoordinate":
        """Zero-based half-open byte range: [start, end)."""
        if start < 0 or end < start:
            raise ValueError(f"invalid byte span {start}..{end}")
        return cls(
            "BYTE_RANGE",
            (CoordinatePart("start", str(start)), CoordinatePart("end", str(end))),
        )


@dataclass(frozen=True, slots=True)
class SourcePointer:
    """Opaque pointer to exact material within one immutable source record version."""

    source_system: str
    source_instance_id: str
    record_id: str
    version_hash: str
    coordinate: SourceCoordinate

    def __post_init__(self) -> None:
        _required(self.source_system, "SourcePointer.source_system")
        _required(self.source_instance_id, "SourcePointer.source_instance_id")
        _required(self.record_id, "SourcePointer.record_id")
        _sha256(self.version_hash, "SourcePointer.version_hash")
        if not isinstance(self.coordinate, SourceCoordinate):
            raise TypeError("SourcePointer.coordinate must be a SourceCoordinate")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One logical external record available for intake."""

    source_system: str
    source_instance_id: str
    record_id: str
    version_hash: str
    display_name: str | None = None
    media_type: str | None = None
    byte_length: int | None = None

    def __post_init__(self) -> None:
        _required(self.source_system, "SourceRecord.source_system")
        _required(self.source_instance_id, "SourceRecord.source_instance_id")
        _required(self.record_id, "SourceRecord.record_id")
        _sha256(self.version_hash, "SourceRecord.version_hash")
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
        _sha256(self.content_hash, "VerifiedSource.content_hash")
        if not isinstance(self.content, bytes):
            raise TypeError("VerifiedSource.content must be bytes")
        if not isinstance(self.material_state, SourceMaterialState):
            raise TypeError("VerifiedSource.material_state must be a SourceMaterialState")
        if self.content_hash != sha256_bytes(self.content):
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
            content_hash=sha256_bytes(content),
            content=content,
            material_state=material_state,
            redaction_ref=redaction_ref,
        )


@dataclass(frozen=True, slots=True)
class SourceVerificationResult:
    """Either verified source material or a typed fail-closed reason."""

    source: VerifiedSource | None = None
    failure: SourceFailure | None = None

    def __post_init__(self) -> None:
        if (self.source is None) == (self.failure is None):
            raise ValueError("SourceVerificationResult requires exactly one of source or failure")
        if self.source is not None and not isinstance(self.source, VerifiedSource):
            raise TypeError("SourceVerificationResult.source must be a VerifiedSource")
        if self.failure is not None and not isinstance(self.failure, SourceFailure):
            raise TypeError("SourceVerificationResult.failure must be a SourceFailure")

    @classmethod
    def verified(cls, source: VerifiedSource) -> "SourceVerificationResult":
        return cls(source=source)

    @classmethod
    def rejected(
        cls,
        code: SourceFailureCode,
        detail: str,
    ) -> "SourceVerificationResult":
        return cls(failure=SourceFailure(code, detail))

    @property
    def ok(self) -> bool:
        return self.source is not None


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    """Bridge from open-ended adapter provenance to current or future EvidenceRef rows.

    The current Historian evidence model is enum-bound to RAG_V1/LEDGER/OTHER and LINE
    spans. This locator is the normalized provenance object a future schema migration can
    persist without collapsing all new adapters into OTHER. Until then, adjudication can
    still consume trusted evidence identity while intake keeps full source identity.
    """

    source_system: str
    source_instance_id: str
    record_id: str
    version_hash: str
    coordinate: SourceCoordinate
    content_hash: str
    material_state: SourceMaterialState
    redaction_ref: str | None = None

    def __post_init__(self) -> None:
        _required(self.source_system, "EvidenceLocator.source_system")
        _required(self.source_instance_id, "EvidenceLocator.source_instance_id")
        _required(self.record_id, "EvidenceLocator.record_id")
        _sha256(self.version_hash, "EvidenceLocator.version_hash")
        _sha256(self.content_hash, "EvidenceLocator.content_hash")
        if not isinstance(self.coordinate, SourceCoordinate):
            raise TypeError("EvidenceLocator.coordinate must be a SourceCoordinate")
        if not isinstance(self.material_state, SourceMaterialState):
            raise TypeError("EvidenceLocator.material_state must be a SourceMaterialState")
        if self.material_state is SourceMaterialState.REDACTED and not self.redaction_ref:
            raise ValueError("redacted locator requires redaction_ref")
        if self.material_state is SourceMaterialState.ORIGINAL and self.redaction_ref:
            raise ValueError("original locator cannot carry redaction_ref")

    @classmethod
    def from_verified_source(cls, source: VerifiedSource) -> "EvidenceLocator":
        pointer = source.pointer
        return cls(
            source_system=pointer.source_system,
            source_instance_id=pointer.source_instance_id,
            record_id=pointer.record_id,
            version_hash=pointer.version_hash,
            coordinate=pointer.coordinate,
            content_hash=source.content_hash,
            material_state=source.material_state,
            redaction_ref=source.redaction_ref,
        )

    @property
    def logical_source_key(self) -> tuple[str, str, str]:
        return (self.source_system, self.source_instance_id, self.record_id)

    @property
    def versioned_source_key(self) -> tuple[str, str, str, str]:
        return (*self.logical_source_key, self.version_hash)


@dataclass(frozen=True, slots=True)
class NormalizedIntakeRecord:
    """Derived text ready to become an evidence candidate.

    Normalized text is useful for indexing, extraction and adjudication preparation, but
    it is never the authority. The source locator remains the re-verifiable authority
    boundary.
    """

    locator: EvidenceLocator
    normalized_text: str
    normalized_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.locator, EvidenceLocator):
            raise TypeError("NormalizedIntakeRecord.locator must be an EvidenceLocator")
        _required(self.normalized_text, "NormalizedIntakeRecord.normalized_text")
        _sha256(self.normalized_hash, "NormalizedIntakeRecord.normalized_hash")
        if self.normalized_hash != sha256_text(self.normalized_text):
            raise ValueError("NormalizedIntakeRecord.normalized_hash must match text")

    @classmethod
    def from_text(cls, locator: EvidenceLocator, normalized_text: str) -> "NormalizedIntakeRecord":
        return cls(
            locator=locator,
            normalized_text=normalized_text,
            normalized_hash=sha256_text(normalized_text),
        )


class SourceAdapter(Protocol):
    """Common contract for source-specific intake adapters."""

    source_system: str

    def enumerate_records(self) -> Iterable[SourceRecord]:
        """Yield stable logical records visible to this adapter."""
        ...

    def version_of(self, source_instance_id: str, record_id: str) -> str | SourceFailure:
        """Return a SHA-256 version hash, or a typed failure reason."""
        ...

    def read(self, pointer: SourcePointer) -> bytes | SourceFailure:
        """Return exact bytes for a pointer, or a typed failure reason."""
        ...

    def verify(self, pointer: SourcePointer) -> SourceVerificationResult:
        """Return verified source material, or a typed fail-closed reason."""
        ...


__all__ = [
    "CoordinatePart",
    "EvidenceLocator",
    "NormalizedIntakeRecord",
    "SHA256_HEX",
    "SourceAdapter",
    "SourceCoordinate",
    "SourceFailure",
    "SourceFailureCode",
    "SourceMaterialState",
    "SourcePointer",
    "SourceRecord",
    "SourceVerificationResult",
    "VerifiedSource",
    "sha256_bytes",
    "sha256_text",
]
