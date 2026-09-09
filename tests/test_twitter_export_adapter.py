import json
import zipfile
from dataclasses import replace

import pytest

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
from historian.twitter_export import TwitterExportAdapter


def js_assignment(name, payload):
    return f"window.YTD.{name}.part0 = {json.dumps(payload)};"


def tweet(tweet_id="100", text="hello", media_ref=None):
    data = {"id_str": tweet_id, "full_text": text, "created_at": "Fri Sep 04 00:00:00 +0000 2026"}
    if media_ref:
        data["extended_entities"] = {"media": [{"media_url": media_ref}]}
    return {"tweet": data}


def header(tweet_id="100"):
    return {"tweet": {"id_str": tweet_id, "created_at": "Fri Sep 04 00:00:00 +0000 2026"}}


def write_export(root, *, tweets=None, headers=None, account=None, manifest=None, media=None):
    data = root / "data"
    data.mkdir(parents=True)
    (root / "Your archive.html").write_text("<html></html>", encoding="utf-8")
    (data / "manifest.js").write_text(
        js_assignment("manifest", manifest or {"archiveInfo": {"createdAt": "2026-09-04"}}),
        encoding="utf-8",
    )
    (data / "account.js").write_text(
        js_assignment("account", account or [{"account": {"accountId": "acct-1"}}]),
        encoding="utf-8",
    )
    (data / "tweets.js").write_text(
        js_assignment("tweets", tweets or [tweet()]),
        encoding="utf-8",
    )
    if headers is not None:
        (data / "tweet-headers.js").write_text(
            js_assignment("tweet_headers", headers),
            encoding="utf-8",
        )
    if media:
        media_dir = data / "tweets_media"
        media_dir.mkdir()
        for name, content in media.items():
            (media_dir / name).write_bytes(content)
    return root


def write_zip_export(path, *, tweets=None, headers=None, account=None, manifest=None, media=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Your archive.html", "<html></html>")
        archive.writestr(
            "data/manifest.js",
            js_assignment("manifest", manifest or {"archiveInfo": {"createdAt": "2026-09-04"}}),
        )
        archive.writestr(
            "data/account.js",
            js_assignment("account", account or [{"account": {"accountId": "acct-1"}}]),
        )
        archive.writestr("data/tweets.js", js_assignment("tweets", tweets or [tweet()]))
        if headers is not None:
            archive.writestr("data/tweet-headers.js", js_assignment("tweet_headers", headers))
        for name, content in (media or {}).items():
            archive.writestr(f"data/tweets_media/{name}", content)
    return path


def adapter_for(tmp_path, **kwargs):
    return TwitterExportAdapter(write_export(tmp_path / "twitter-export", **kwargs))


def full_pointer(adapter, record_id="tweet:100"):
    pointer = adapter.pointer_for_record(record_id)
    assert isinstance(pointer, SourcePointer)
    return pointer


def test_enumerates_stable_tweet_records(tmp_path):
    adapter = adapter_for(tmp_path, tweets=[tweet("200", "b"), tweet("100", "a")])

    records = tuple(adapter.enumerate_records())

    assert [record.record_id for record in records] == ["tweet:100", "tweet:200"]
    assert {record.source_system for record in records} == {"TWITTER_EXPORT"}
    assert all(
        record.version_hash == adapter.version_of(adapter.source_instance_id, record.record_id)
        for record in records
    )


def test_source_instance_id_is_deterministic_from_account_data(tmp_path):
    first = TwitterExportAdapter(write_export(tmp_path / "first"))
    second = TwitterExportAdapter(write_export(tmp_path / "second"))
    other = TwitterExportAdapter(
        write_export(tmp_path / "other", account=[{"account": {"accountId": "acct-2"}}])
    )

    assert first.source_instance_id == second.source_instance_id
    assert first.source_instance_id != other.source_instance_id


def test_explicit_source_instance_id_is_supported_and_empty_is_rejected(tmp_path):
    export = write_export(tmp_path / "export")

    assert TwitterExportAdapter(export, source_instance_id="instance-1").source_instance_id == "instance-1"
    with pytest.raises(ValueError, match="source_instance_id"):
        TwitterExportAdapter(export, source_instance_id="")


def test_pointer_reads_and_verifies_exact_source_bytes(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)
    result = adapter.verify(pointer)

    assert isinstance(result, SourceVerificationResult)
    assert result.ok is True
    assert isinstance(result.source, VerifiedSource)
    assert result.source.pointer == pointer
    assert result.source.content_hash == sha256_bytes(result.source.content)


def test_partial_byte_pointer_is_zero_based_and_end_exclusive(tmp_path):
    adapter = adapter_for(tmp_path)
    full = full_pointer(adapter)
    pointer = replace(full, coordinate=SourceCoordinate.byte_range(0, 8))

    result = adapter.verify(pointer)

    assert result.ok is True
    assert result.source.content == adapter.read(full)[:8]


def test_json_pointer_coordinate_addresses_exact_field_anchor(tmp_path):
    adapter = adapter_for(tmp_path, tweets=[tweet("100", "field target")])
    pointer = adapter.pointer_for_field("tweet:100", "/tweet/full_text")
    assert isinstance(pointer, SourcePointer)

    result = adapter.verify(pointer)

    assert result.ok is True
    assert result.source.content == json.dumps("field target").encode("utf-8")


def test_locator_is_produced_from_verified_twitter_source(tmp_path):
    adapter = adapter_for(tmp_path)
    locator = adapter.locator_for(full_pointer(adapter))

    assert isinstance(locator, EvidenceLocator)
    assert locator.source_system == "TWITTER_EXPORT"
    assert locator.source_instance_id == adapter.source_instance_id
    assert locator.record_id == "tweet:100"


def test_repeated_imports_are_idempotent(tmp_path):
    tweets = [tweet("100"), tweet("200")]
    first = TwitterExportAdapter(write_export(tmp_path / "first", tweets=tweets))
    second = TwitterExportAdapter(write_export(tmp_path / "second", tweets=tweets))

    assert tuple(first.enumerate_records()) == tuple(second.enumerate_records())


def test_mutated_source_gets_new_version_and_old_pointer_fails_closed(tmp_path):
    original = TwitterExportAdapter(write_export(tmp_path / "original", tweets=[tweet(text="old")]))
    old_pointer = full_pointer(original)
    mutated = TwitterExportAdapter(write_export(tmp_path / "mutated", tweets=[tweet(text="new")]))

    assert mutated.version_of(mutated.source_instance_id, "tweet:100") != old_pointer.version_hash
    result = mutated.verify(old_pointer)
    assert result.ok is False
    assert result.failure.code is SourceFailureCode.VERSION_MISMATCH


def test_wrong_adapter_wrong_instance_and_wrong_version_fail_closed(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)

    wrong_adapter = adapter.verify(replace(pointer, source_system="CHATGPT_EXPORT"))
    wrong_instance = adapter.verify(replace(pointer, source_instance_id="other-instance"))
    wrong_version = adapter.verify(replace(pointer, version_hash="0" * 64))

    assert wrong_adapter.failure.code is SourceFailureCode.INVALID_POINTER
    assert wrong_instance.failure.code is SourceFailureCode.NOT_FOUND
    assert wrong_version.failure.code is SourceFailureCode.VERSION_MISMATCH


def test_rejects_invalid_or_unsupported_coordinates(tmp_path):
    adapter = adapter_for(tmp_path)
    pointer = full_pointer(adapter)

    unsupported = adapter.verify(
        replace(pointer, coordinate=SourceCoordinate("LINE_RANGE", (CoordinatePart("start", "1"),)))
    )
    invalid_json = adapter.verify(
        replace(
            pointer,
            coordinate=SourceCoordinate("JSON_POINTER", (CoordinatePart("path", "/tweet/full_text"),)),
        )
    )
    outside = adapter.verify(replace(pointer, coordinate=SourceCoordinate.byte_range(0, 999999)))

    assert unsupported.failure.code is SourceFailureCode.UNSUPPORTED_COORDINATE
    assert invalid_json.failure.code is SourceFailureCode.INVALID_POINTER
    assert outside.failure.code is SourceFailureCode.INVALID_POINTER


def test_missing_or_malformed_exports_fail_closed(tmp_path):
    missing = TwitterExportAdapter(tmp_path / "missing")
    bad = write_export(tmp_path / "bad")
    (bad / "data" / "tweets.js").write_text("window.YTD.tweets.part0 = {not json", encoding="utf-8")

    assert isinstance(missing.version_of(missing.source_instance_id, "tweet:100"), SourceFailure)
    failure = TwitterExportAdapter(bad).version_of(TwitterExportAdapter(bad).source_instance_id, "x")
    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.MALFORMED_SOURCE


def test_rejects_duplicate_tweet_ids(tmp_path):
    adapter = adapter_for(tmp_path, tweets=[tweet("100"), tweet("100")])
    failure = adapter.version_of(adapter.source_instance_id, "tweet:100")

    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.INTEGRITY_FAILURE


def test_rejects_archive_member_escape(tmp_path):
    archive_path = tmp_path / "twitter.zip"
    write_zip_export(archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("../escape.txt", "nope")

    adapter = TwitterExportAdapter(archive_path, source_instance_id="instance-fixed")
    failure = adapter.version_of("instance-fixed", "tweet:100")

    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.INTEGRITY_FAILURE


def test_reads_zip_export_without_extracting(tmp_path):
    archive_path = write_zip_export(tmp_path / "twitter.zip")
    adapter = TwitterExportAdapter(archive_path)
    result = adapter.verify(full_pointer(adapter))

    assert result.ok is True
    assert result.source.pointer.source_system == "TWITTER_EXPORT"


def test_media_references_are_verified_when_present(tmp_path):
    adapter = adapter_for(
        tmp_path,
        tweets=[tweet(media_ref="tweets_media/100-photo.jpg")],
        media={"100-photo.jpg": b"image bytes"},
    )
    missing_media = adapter_for(
        tmp_path / "missing",
        tweets=[tweet(media_ref="tweets_media/100-photo.jpg")],
    )

    assert adapter.verify(full_pointer(adapter)).ok is True
    failure = missing_media.version_of(missing_media.source_instance_id, "tweet:100")
    assert isinstance(failure, SourceFailure)
    assert failure.code is SourceFailureCode.NOT_FOUND


def test_tweet_headers_are_included_in_versioned_record(tmp_path):
    with_header = adapter_for(tmp_path / "with", headers=[header("100")])
    without_header = adapter_for(tmp_path / "without", headers=[])

    assert (
        with_header.version_of(with_header.source_instance_id, "tweet:100")
        != without_header.version_of(without_header.source_instance_id, "tweet:100")
    )
