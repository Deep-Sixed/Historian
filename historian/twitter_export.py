"""X/Twitter archive adapter for the SourceAdapter v1 contract."""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
from urllib.parse import urlsplit, unquote

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


class TwitterExportAdapter:
    """Reads tweet records from a full X/Twitter account archive.

    The archive format still uses Twitter terminology (`tweets.js`, `tweet_headers`,
    `window.YTD`), so the source system is `TWITTER_EXPORT`. The adapter treats those
    JavaScript files as serialized data containers and never executes them.
    """

    source_system = "TWITTER_EXPORT"
    _ASSIGNMENTS = {
        "data/manifest.js": ("window.__THAR_CONFIG",),
        "data/account.js": ("window.YTD.account.part0",),
        "data/tweets.js": ("window.YTD.tweets.part0",),
        "data/tweet-headers.js": ("window.YTD.tweet_headers.part0",),
    }

    def __init__(self, export_root: str | Path, source_instance_id: str | None = None):
        self._root = Path(export_root).resolve()
        if source_instance_id is not None and not source_instance_id:
            raise ValueError("source_instance_id cannot be empty")
        self._source_instance_id_overridden = source_instance_id is not None
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
            value = self._resolve_json_pointer(json.loads(content), parts["path"])
            return self._canonical_bytes(value)
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
        path = field_path if field_path == "" or field_path.startswith("/") else f"/{field_path}"
        try:
            self._resolve_json_pointer(json.loads(content), path)
        except (KeyError, TypeError, ValueError) as exc:
            return SourceFailure(SourceFailureCode.NOT_FOUND, str(exc))
        return SourcePointer(
            self.source_system,
            self.source_instance_id,
            record_id,
            version,
            SourceCoordinate(
                "JSON_POINTER",
                (CoordinatePart("path", path),),
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
        if set(parts) != {"path"}:
            return SourceFailure(
                SourceFailureCode.INVALID_POINTER,
                "JSON_POINTER requires path",
            )
        content = self._records[pointer.record_id]
        path = parts["path"]
        if path != "" and not path.startswith("/"):
            return SourceFailure(SourceFailureCode.INVALID_POINTER, "JSON pointer must be absolute")
        try:
            self._resolve_json_pointer(json.loads(content), path)
        except (KeyError, TypeError, ValueError) as exc:
            return SourceFailure(SourceFailureCode.INVALID_POINTER, str(exc))
        return None

    def _ensure_records(self) -> SourceFailure | None:
        try:
            self._validate_current_source_identity()
            media_index = self._media_index()
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
            media_refs = self._media_refs_for_tweet(tweet, tweet_id, media_index)
            if isinstance(media_refs, SourceFailure):
                return media_refs
            records[record_id] = self._canonical_bytes({
                "family": "tweet",
                "tweet": tweet,
                "tweet_header": headers.get(tweet_id),
                "tweet_media": media_refs,
            })

        self._records = records
        return None

    def _derive_source_instance_id(self) -> str:
        try:
            manifest = self._load_archive_manifest()
            account = self._load_ytd_array("data/account.js")
            account_id = self._account_id(account)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                "source_instance_id override required when account identity is unavailable"
            ) from exc
        if not account_id:
            raise ValueError("account.js does not contain a stable account id")
        manifest_account_id = self._manifest_account_id(manifest)
        if manifest_account_id and manifest_account_id != account_id:
            raise ValueError("manifest.js account id does not match account.js")
        return sha256_bytes(b"TWITTER_EXPORT_ACCOUNT\0" + account_id.encode("utf-8"))

    def _validate_current_source_identity(self) -> None:
        manifest = self._load_archive_manifest()
        manifest_account_id = self._manifest_account_id(manifest)
        account_id = None
        try:
            account_id = self._account_id(self._load_ytd_array("data/account.js"))
        except (FileNotFoundError, KeyError):
            if not self._source_instance_id_overridden:
                raise

        if manifest_account_id and account_id and manifest_account_id != account_id:
            raise ValueError("manifest.js account id does not match account.js")
        if self._source_instance_id_overridden:
            return
        if not account_id:
            raise ValueError("account.js does not contain a stable account id")
        expected = sha256_bytes(b"TWITTER_EXPORT_ACCOUNT\0" + account_id.encode("utf-8"))
        if expected != self.source_instance_id:
            raise ValueError("source instance identity changed")

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
        lhs, sep, rhs = raw.partition("=")
        if not sep:
            raise json.JSONDecodeError(f"{member_name} has no assignment", raw, 0)
        expected = self._ASSIGNMENTS.get(member_name)
        if expected is not None and lhs.strip() not in expected:
            raise json.JSONDecodeError(
                f"{member_name} has unexpected assignment {lhs.strip()!r}",
                raw,
                0,
            )
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

    def _list_export_members(self) -> list[str]:
        if self._root.is_dir():
            return [
                path.relative_to(self._root).as_posix()
                for path in self._root.rglob("*")
                if path.is_file()
            ]
        if self._root.is_file():
            with ZipFile(self._root) as archive:
                self._validate_zip_members(archive)
                return archive.namelist()
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

    def _media_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for member in self._list_export_members():
            normalized = posixpath.normpath(member)
            if not normalized.startswith("data/tweets_media/") or normalized.endswith("/"):
                continue
            filename = posixpath.basename(normalized)
            tweet_id, sep, _ = filename.partition("-")
            if not sep or not tweet_id:
                continue
            index.setdefault(tweet_id, []).append(normalized)
        return {tweet_id: sorted(members) for tweet_id, members in index.items()}

    def _media_refs_for_tweet(
        self,
        tweet: dict,
        tweet_id: str,
        media_index: dict[str, list[str]],
    ) -> list[dict[str, str]] | SourceFailure:
        if not self._tweet_declares_media(tweet):
            return []
        members = media_index.get(tweet_id)
        if not members:
            return SourceFailure(
                SourceFailureCode.NOT_FOUND,
                f"tweet {tweet_id!r} declares media but has no archived tweets_media member",
            )
        # Each declared entity needs its own archived payload. A thumbnail does
        # not establish that a video (or the other photos in a gallery) exists.
        declared = self._media_entities(tweet, "extended_entities") or self._media_entities(tweet, "entities")
        available = {posixpath.basename(member) for member in members}
        for entity in declared:
            if not isinstance(entity, dict):
                return SourceFailure(SourceFailureCode.MALFORMED_SOURCE, "invalid media entity")
            if entity.get("type") in {"video", "animated_gif"}:
                info = entity.get("video_info", {})
                variants = info.get("variants", []) if isinstance(info, dict) else []
                urls = [v.get("url") for v in variants if isinstance(v, dict)
                        and v.get("content_type") == "video/mp4"]
            else:
                urls = [entity.get("media_url_https") or entity.get("media_url")]
            expected = {
                f"{tweet_id}-{posixpath.basename(unquote(urlsplit(url).path))}"
                for url in urls if isinstance(url, str) and urlsplit(url).path
            }
            if not expected.intersection(available):
                return SourceFailure(SourceFailureCode.NOT_FOUND,
                                     f"tweet {tweet_id!r} has an unarchived media entity")
        refs = []
        for member in members:
            try:
                content = self._read_export_member(member)
            except (FileNotFoundError, KeyError):
                return SourceFailure(SourceFailureCode.NOT_FOUND, f"media reference missing: {member}")
            except (BadZipFile, OSError) as exc:
                return SourceFailure(SourceFailureCode.UNAVAILABLE, str(exc))
            except ValueError as exc:
                return SourceFailure(SourceFailureCode.INTEGRITY_FAILURE, str(exc))
            refs.append({"member": member, "sha256": sha256_bytes(content)})
        return refs

    def _tweet_declares_media(self, tweet: dict) -> bool:
        return any(
            self._media_entities(tweet, container)
            for container in ("entities", "extended_entities")
        )

    def _media_entities(self, tweet: dict, container: str) -> list:
        value = tweet.get(container)
        if not isinstance(value, dict):
            return []
        media = value.get("media")
        return media if isinstance(media, list) else []

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

    def _manifest_account_id(self, manifest: Any) -> str | None:
        for value in self._values_for_key(manifest, "accountId"):
            if isinstance(value, str) and value:
                return value
        return None

    def _values_for_key(self, value: Any, key: str) -> Iterable[Any]:
        if isinstance(value, dict):
            for item_key, item_value in value.items():
                if item_key == key:
                    yield item_value
                yield from self._values_for_key(item_value, key)
        elif isinstance(value, list):
            for item in value:
                yield from self._values_for_key(item, key)

    def _resolve_json_pointer(self, value: Any, path: str) -> Any:
        if path == "":
            return value
        if not path.startswith("/"):
            raise ValueError("JSON pointer must be absolute")
        current = value
        for raw_part in path[1:].split("/"):
            part = self._decode_json_pointer_token(raw_part)
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

    def _decode_json_pointer_token(self, token: str) -> str:
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


__all__ = ["TwitterExportAdapter"]
