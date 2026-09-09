"""X/Twitter archive adapter for the SourceAdapter v1 contract."""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any
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


class SourceEnumerationError(RuntimeError):
    """Enumeration failed closed instead of pretending the export is empty."""

    def __init__(self, failure: SourceFailure):
        self.failure = failure
        super().__init__(f"{failure.code.value}: {failure.detail}")


class TwitterExportAdapter:
    """Reads tweet records from a full X/Twitter account archive.

    The archive format still uses Twitter terminology (`tweets.js`, `tweet_headers`,
    `window.YTD`), so the source system is `TWITTER_EXPORT`. The adapter treats those
    JavaScript files as serialized data containers and never executes them.
    """

    source_system = "TWITTER_EXPORT"

    def __init__(self, export_root: str | Path, source_instance_id: str | None = None):
        self._root = Path(export_root).resolve()
        if source_instance_id is not None and not source_instance_id:
            raise ValueError("source_instance_id cannot be empty")
        self.source_instance_id = source_instance_id or self._derive_source_instance_id()
        self._records: dict[str, bytes] | None = None

    def enumerate_records(self):
        if failure := self._ensure_records():
            raise SourceEnumerationError(failure)
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
        content = self._records[pointer.record_id]
        if pointer.coordinate.coordinate_system == "JSON_POINTER":
            parts = {part.name: part.value for part in pointer.coordinate.parts}
            start = int(parts["byte_start"])
            end = int(parts["byte_end"])
            return content[start:end]
        parts = {part.name: int(part.value) for part in pointer.coordinate.parts}
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

    def pointer_for_field(self, record_id: str, field_path: str) -> SourcePointer | SourceFailure:
        version = self.version_of(self.source_instance_id, record_id)
        if isinstance(version, SourceFailure):
            return version
        content = self._records[record_id]
        path = field_path if field_path.startswith("/") else f"/{field_path}"
        try:
            value = self._resolve_json_pointer(json.loads(content), path)
        except (KeyError, TypeError, ValueError) as exc:
            return SourceFailure(SourceFailureCode.NOT_FOUND, str(exc))
        needle = self._canonical_bytes(value)
        start = content.find(needle)
        if start == -1:
            return SourceFailure(SourceFailureCode.NOT_FOUND, "field value is not present")
        return SourcePointer(
            self.source_system,
            self.source_instance_id,
            record_id,
            version,
            SourceCoordinate(
                "JSON_POINTER",
                (
                    CoordinatePart("byte_end", str(start + len(needle))),
                    CoordinatePart("byte_start", str(start)),
                    CoordinatePart("path", path),
                ),
            ),
        )

    def locator_for(self, pointer: SourcePointer) -> EvidenceLocator | SourceFailure:
        result = self.verify(pointer)
        if result.failure is not None:
            return result.failure
        return EvidenceLocator.from_verified_source(result.source)

    def _precheck(self, pointer: SourcePointer) -> SourceFailure | None:
        if pointer.source_system != self.source_system:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "wrong source system")
        version = self.version_of(pointer.source_instance_id, pointer.record_id)
        if isinstance(version, SourceFailure):
            return version
        if pointer.version_hash != version:
            return SourceFailure(SourceFailureCode.VERSION_MISMATCH, "record version changed")
        if pointer.coordinate.coordinate_system == "BYTE_RANGE":
            return self._validate_byte_range(pointer)
        if pointer.coordinate.coordinate_system == "JSON_POINTER":
            return self._validate_json_pointer(pointer)
        return SourceFailure(
            SourceFailureCode.UNSUPPORTED_COORDINATE,
            "coordinate system is not supported for Twitter exports",
        )

    def _validate_byte_range(self, pointer: SourcePointer) -> SourceFailure | None:
        try:
            parts = {part.name: int(part.value) for part in pointer.coordinate.parts}
        except ValueError:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "byte range is not numeric")
        if set(parts) != {"start", "end"}:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "BYTE_RANGE requires start/end")
        if parts["start"] < 0 or parts["end"] < parts["start"]:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "invalid byte range")
        return None

    def _validate_json_pointer(self, pointer: SourcePointer) -> SourceFailure | None:
        parts = {part.name: part.value for part in pointer.coordinate.parts}
        if set(parts) != {"byte_end", "byte_start", "path"}:
            return SourceFailure(
                SourceFailureCode.INVALID_POINTER,
                "JSON_POINTER requires path/byte_start/byte_end",
            )
        try:
            start = int(parts["byte_start"])
            end = int(parts["byte_end"])
        except ValueError:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "byte anchors are not numeric")
        content = self._records[pointer.record_id]
        path = parts["path"]
        if not path.startswith("/"):
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "JSON pointer must be absolute")
        if start < 0 or end < start or end > len(content):
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "invalid JSON pointer byte range")
        try:
            expected = self._canonical_bytes(self._resolve_json_pointer(json.loads(content), path))
        except (KeyError, TypeError, ValueError) as exc:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, str(exc))
        if content[start:end] != expected:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "JSON pointer anchor moved")
        return None

    def _ensure_records(self) -> SourceFailure | None:
        try:
            self._load_archive_manifest()
            tweets = self._load_ytd_array("data/tweets.js")
            headers = self._tweet_headers_by_id()
        except KeyError as exc:
            return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, str(exc))
        except (BadZipFile, OSError) as exc:
            return SourceFailure(SourceFailureCode.UNAVAILABLE, str(exc))
        except json.JSONDecodeError as exc:
            return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, str(exc))
        except ValueError as exc:
            return SourceFailure(SourceFailureCode.INTEGRITY_FAILURE, str(exc))

        records = {}
        for index, item in enumerate(tweets):
            tweet = item.get("tweet") if isinstance(item, dict) else None
            if not isinstance(tweet, dict):
                return SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE,
                    f"tweet item {index} has no tweet object",
                )
            tweet_id = self._tweet_id(tweet)
            if not tweet_id:
                return SourceFailure(
                    SourceFailureCode.MALFORMED_SOURCE,
                    f"tweet item {index} has no stable id",
                )
            record_id = f"tweet:{tweet_id}"
            if record_id in records:
                return SourceFailure(
                    SourceFailureCode.INTEGRITY_FAILURE,
                    f"duplicate tweet id {tweet_id!r}",
                )
            if failure := self._validate_media_references(tweet):
                return failure
            records[record_id] = self._canonical_bytes({
                "family": "tweet",
                "tweet": tweet,
                "tweet_header": headers.get(tweet_id),
            })

        self._records = records
        return None

    def _derive_source_instance_id(self) -> str:
        try:
            account = self._load_ytd_array("data/account.js")
            account_id = self._account_id(account)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                "source_instance_id override required when account identity is unavailable"
            ) from exc
        if not account_id:
            raise ValueError("account.js does not contain a stable account id")
        return sha256_bytes(b"TWITTER_EXPORT_ACCOUNT\0" + account_id.encode("utf-8"))

    def _load_archive_manifest(self) -> Any:
        return self._load_ytd_payload("data/manifest.js")

    def _tweet_headers_by_id(self) -> dict[str, Any]:
        try:
            headers = self._load_ytd_array("data/tweet-headers.js")
        except (FileNotFoundError, KeyError):
            return {}
        by_id = {}
        for index, item in enumerate(headers):
            header = item.get("tweet") if isinstance(item, dict) else item
            if not isinstance(header, dict):
                raise ValueError(f"tweet header {index} is not an object")
            tweet_id = self._tweet_id(header)
            if not tweet_id:
                raise ValueError(f"tweet header {index} has no stable id")
            if tweet_id in by_id:
                raise ValueError(f"duplicate tweet header id {tweet_id!r}")
            by_id[tweet_id] = header
        return by_id

    def _load_ytd_array(self, member_name: str) -> list:
        payload = self._load_ytd_payload(member_name)
        if not isinstance(payload, list):
            raise json.JSONDecodeError(f"{member_name} must contain an array", "", 0)
        return payload

    def _load_ytd_payload(self, member_name: str) -> Any:
        raw = self._read_export_member(member_name).decode("utf-8")
        _, sep, rhs = raw.partition("=")
        if not sep:
            raise json.JSONDecodeError(f"{member_name} has no assignment", raw, 0)
        return json.loads(rhs.strip().rstrip(";"))

    def _read_export_member(self, member_name: str) -> bytes:
        self._validate_member_name(member_name)
        if self._root.is_dir():
            path = (self._root / member_name).resolve()
            try:
                path.relative_to(self._root)
            except ValueError as exc:
                raise ValueError("export member escapes source root") from exc
            return path.read_bytes()
        if self._root.is_file():
            with ZipFile(self._root) as archive:
                self._validate_zip_members(archive)
                return archive.read(member_name)
        raise OSError(f"export root does not exist: {self._root}")

    def _validate_zip_members(self, archive: ZipFile) -> None:
        seen = set()
        for info in archive.infolist():
            self._validate_member_name(info.filename)
            normalized = posixpath.normpath(info.filename)
            if normalized in seen:
                raise ValueError(f"duplicate archive member: {normalized!r}")
            seen.add(normalized)

    def _validate_member_name(self, member_name: str) -> None:
        normalized = posixpath.normpath(member_name)
        if (
            member_name.startswith("/")
            or normalized == ".."
            or normalized.startswith("../")
            or "/../" in normalized
        ):
            raise ValueError(f"archive member escapes source root: {member_name!r}")

    def _validate_media_references(self, tweet: dict) -> SourceFailure | None:
        for ref in self._strings(tweet):
            if "tweets_media/" not in ref:
                continue
            member = ref[ref.index("tweets_media/"):]
            member = member if member.startswith("data/") else f"data/{member}"
            try:
                self._read_export_member(member)
            except (FileNotFoundError, KeyError):
                return SourceFailure(SourceFailureCode.NOT_FOUND, f"media reference missing: {member}")
            except (BadZipFile, OSError) as exc:
                return SourceFailure(SourceFailureCode.UNAVAILABLE, str(exc))
            except ValueError as exc:
                return SourceFailure(SourceFailureCode.INTEGRITY_FAILURE, str(exc))
        return None

    def _strings(self, value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from self._strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._strings(child)

    def _tweet_id(self, tweet: dict) -> str | None:
        for key in ("id_str", "id", "tweet_id"):
            value = tweet.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _account_id(self, account_items: list) -> str | None:
        for item in account_items:
            account = item.get("account") if isinstance(item, dict) else None
            if not isinstance(account, dict):
                continue
            for key in ("accountId", "id", "userId"):
                value = account.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def _resolve_json_pointer(self, value: Any, path: str) -> Any:
        current = value
        for raw_part in path.strip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                current = current[part]
            elif isinstance(current, list):
                current = current[int(part)]
            else:
                raise TypeError("JSON pointer descends through a scalar")
        return current

    def _display_name(self, content: bytes) -> str | None:
        parsed = json.loads(content)
        text = parsed.get("tweet", {}).get("full_text")
        if not isinstance(text, str) or not text:
            return None
        return text[:80]

    def _canonical_bytes(self, value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


__all__ = ["SourceEnumerationError", "TwitterExportAdapter"]
