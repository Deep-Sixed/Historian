# Twitter Export Adapter

`TwitterExportAdapter` is the first concrete Source Adapter v1 implementation. It reads an
X/Twitter account archive without changing PostgreSQL persistence or Historian
adjudication.

The source system is `TWITTER_EXPORT` because the archive format still uses Twitter names:
`tweets.js`, `tweet-headers.js`, `window.YTD` and related data members.

## Supported Input

The adapter supports:

- an unpacked archive directory
- a zip archive

It reads data members in place and does not execute JavaScript or extract archives to disk.
Archive members with absolute paths, parent traversal or duplicate normalized names are
rejected before source records are accepted.

## Initial Coverage

PR #4 intentionally covers only the first archive slice:

- `data/manifest.js`: validates that the archive metadata member is present and parseable
- `data/account.js`: derives deterministic opaque `source_instance_id` from a stable
  account id
- `data/tweets.js`: enumerates tweet records
- `data/tweet-headers.js`: optionally joins header metadata into each tweet record version
- `data/tweets_media/`: verifies referenced tweet media members when tweets cite them

Likes, direct messages, followers, following, lists, Grok history and the rest of the
archive families are out of scope for this PR.

If a stable account id is unavailable, callers must provide `source_instance_id`
explicitly. The adapter does not manufacture source lineage from a local filesystem path.

## Record Model

Each tweet object in `data/tweets.js` becomes one `SourceRecord`.

Tweet record ids are namespaced:

```text
tweet:<tweet-id>
```

The namespace is part of the record id so future record families such as likes, direct
messages, deleted tweets and Grok items cannot collide with tweet ids.

The record `version_hash` is the SHA-256 digest of canonical JSON bytes containing:

```text
family
tweet
tweet_header
```

That means tweet-header changes are version changes rather than silent metadata drift.

## Coordinates

The adapter supports:

- `BYTE_RANGE` over the canonical tweet JSON record bytes
- `JSON_POINTER` anchors for exact field locations inside the canonical record

`BYTE_RANGE` follows the Source Adapter v1 rule: zero-based and half-open `[start, end)`.

## Failure Behavior

The adapter fails closed with typed `SourceFailure` values for:

- missing archive roots
- missing stable account identity unless `source_instance_id` is explicitly supplied
- malformed archive data wrappers
- malformed JSON
- duplicate tweet ids
- duplicate tweet-header ids
- missing tweet ids
- wrong source system
- wrong source instance
- changed source versions
- unsupported coordinates
- byte ranges outside the canonical record
- JSON pointer anchors that moved
- missing referenced tweet media
- archive member escape
- duplicate zip member names

Record enumeration raises `SourceEnumerationError` with a typed `SourceFailure` rather
than returning an empty iterator for malformed or unavailable exports. A valid export with
zero tweets still enumerates as empty.

Verification re-reads the current archive data before trusting a pointer, so mutation
after pointer creation fails closed instead of validating against stale cached bytes.

The adapter does not write to PostgreSQL and does not create `EvidenceRef` rows.
