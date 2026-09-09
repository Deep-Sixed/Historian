"""ChatGPT export adapter for the SourceAdapter v1 contract."""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceFailure,
    SourceFailureCode,
    SourcePointer,
    SourceRecord,
    SourceVerificationResult,
    VerifiedSource,
    sha256_bytes,
)


class ChatGPTExportAdapter:
    """Reads conversation records from a ChatGPT data export.

    The adapter supports the standard `conversations.json` export member from either an
    unpacked export directory or a zip archive. It keeps the shared protocol source-agnostic
    by exposing conversation records as canonical JSON bytes and BYTE_RANGE coordinates.
    """

    source_system = "CHATGPT_EXPORT"

    def __init__(self, export_root: str | Path, source_instance_id: str | None = None):
        self._root = Path(export_root).resolve()
        if source_instance_id is not None and not source_instance_id:
            raise ValueError("source_instance_id cannot be empty")
        self.source_instance_id = source_instance_id or self._derive_source_instance_id()
        self._records: dict[str, bytes] | None = None
        self._load_failure: SourceFailure | None = None

    def enumerate_records(self):
        if failure := self._ensure_records():
            return iter(())
        records = [
            SourceRecord(
                self.source_system,
                self.source_instance_id,
                record_id,
                sha256_bytes(content),
                display_name=self._display_name(content),
                media_type="application/json",
                byte_length=len(content),
            )
            for record_id, content in self._records.items()
        ]
        return iter(sorted(records, key=lambda record: record.record_id))

    def version_of(self, source_instance_id: str, record_id: str) -> str | SourceFailure:
        if source_instance_id != self.source_instance_id:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "source instance is unknown")
        if failure := self._ensure_records():
            return failure
        content = self._records.get(record_id)
        if content is None:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "record is unknown")
        return sha256_bytes(content)

    def read(self, pointer: SourcePointer) -> bytes | SourceFailure:
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

    def verify(self, pointer: SourcePointer) -> SourceVerificationResult:
        read = self.read(pointer)
        if isinstance(read, SourceFailure):
            return SourceVerificationResult(failure=read)
        return SourceVerificationResult.verified(VerifiedSource.from_bytes(pointer, read))

    def locator_for(self, pointer: SourcePointer) -> EvidenceLocator | SourceFailure:
        result = self.verify(pointer)
        if result.failure is not None:
            return result.failure
        return EvidenceLocator.from_verified_source(result.source)

    def pointer_for_record(self, record_id: str) -> SourcePointer | SourceFailure:
        version = self.version_of(self.source_instance_id, record_id)
        if isinstance(version, SourceFailure):
            return version
        content = self._records[record_id]
        return SourcePointer(
            self.source_system,
            self.source_instance_id,
            record_id,
            version,
            SourceCoordinate.byte_range(0, len(content)),
        )

    def _precheck(self, pointer: SourcePointer) -> SourceFailure | None:
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
                "only BYTE_RANGE is supported for ChatGPT export records",
            )
        try:
            parts = {part.name: int(part.value) for part in pointer.coordinate.parts}
        except ValueError:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "byte range is not numeric")
        if set(parts) != {"start", "end"}:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "BYTE_RANGE requires start/end")
        if parts["start"] < 0 or parts["end"] < parts["start"]:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "invalid byte range")
        return None

    def _ensure_records(self) -> SourceFailure | None:
        if self._records is not None:
            return None
        try:
            payload = self._read_export_member("conversations.json")
            parsed = json.loads(payload)
        except KeyError as exc:
            self._load_failure = SourceFailure(SourceFailureCode.MALFORMED_SOURCE, str(exc))
            return self._load_failure
        except (BadZipFile, OSError) as exc:
            self._load_failure = SourceFailure(SourceFailureCode.UNAVAILABLE, str(exc))
            return self._load_failure
        except json.JSONDecodeError as exc:
            self._load_failure = SourceFailure(SourceFailureCode.MALFORMED_SOURCE, str(exc))
            return self._load_failure
        except ValueError as exc:
            self._load_failure = SourceFailure(SourceFailureCode.INTEGRITY_FAILURE, str(exc))
            return self._load_failure

        if not isinstance(parsed, list):
            self._load_failure = SourceFailure(
                SourceFailureCode.MALFORMED_SOURCE,
                "conversations.json must contain a list",
            )
            return self._load_failure

        records = {}
        for index, conversation in enumerate(parsed):
            if not isinstance(conversation, dict):
                self._load_failure = SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE,
                    f"conversation {index} is not an object",
                )
                return self._load_failure
            record_id = self._record_id(conversation)
            if not record_id:
                self._load_failure = SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE,
                    f"conversation {index} has no stable id",
                )
                return self._load_failure
            if record_id in records:
                self._load_failure = SourceFailure(
                    SourceFailureCode.INTEGRITY_FAILURE,
                    f"duplicate conversation id {record_id!r}",
                )
                return self._load_failure
            records[record_id] = self._canonical_bytes(conversation)

        self._records = records
        return None

    def _derive_source_instance_id(self) -> str:
        try:
            identity = self._read_export_member("user.json")
        except (BadZipFile, KeyError, OSError, ValueError):
            identity = str(self._root).encode("utf-8")
        return sha256_bytes(b"CHATGPT_EXPORT\0" + identity)

    def _read_export_member(self, member_name: str) -> bytes:
        if self._root.is_dir():
            path = (self._root / member_name).resolve()
            if path.parent != self._root:
                raise ValueError("export member escapes source root")
            return path.read_bytes()
        if self._root.is_file():
            with ZipFile(self._root) as archive:
                self._validate_zip_members(archive)
                return archive.read(member_name)
        raise OSError(f"export root does not exist: {self._root}")

    def _validate_zip_members(self, archive: ZipFile) -> None:
        for info in archive.infolist():
            name = info.filename
            normalized = posixpath.normpath(name)
            if (
                name.startswith("/")
                or normalized == ".."
                or normalized.startswith("../")
                or "/../" in normalized
            ):
                raise ValueError(f"archive member escapes source root: {name!r}")

    def _record_id(self, conversation: dict) -> str | None:
        for key in ("id", "conversation_id"):
            value = conversation.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _display_name(self, content: bytes) -> str | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        title = parsed.get("title") if isinstance(parsed, dict) else None
        return title if isinstance(title, str) and title else None

    def _canonical_bytes(self, conversation: dict) -> bytes:
        return json.dumps(
            conversation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


__all__ = ["ChatGPTExportAdapter"]
