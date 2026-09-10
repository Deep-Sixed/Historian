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

- `data/manifest.js`: validates that the archive metadata member is present and parseable,
  and cross-checks stable account identity when present
- `data/account.js`: derives deterministic opaque `source_instance_id` from a stable
  account id
- `data/tweets.js`: enumerates tweet records
- `data/tweet-headers.js`: optionally joins header metadata into each tweet record version
- `data/tweets_media/`: binds archived tweet media members by tweet-id filename prefix when
  Twitter media entities are present

Likes, direct messages, followers, following, lists, Grok history and the rest of the
archive families are out of scope for this PR.

If a stable account id is unavailable, callers must provide `source_instance_id`
explicitly. The adapter does not manufacture source lineage from a local filesystem path.
For derived identities, every verification path re-reads the current account identity and
rejects archives whose stable account id no longer maps to the adapter's
`source_instance_id`. Explicit overrides do not prove account ownership, but any account
and manifest ids present in the current archive must still agree.

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
tweet_media
```

That means tweet-header or archived tweet-media changes are version changes rather than
silent metadata drift.

## Coordinates

The adapter supports:

- `BYTE_RANGE` over the canonical tweet JSON record bytes
- `JSON_POINTER` paths for exact fields inside the canonical record

`BYTE_RANGE` follows the Source Adapter v1 rule: zero-based and half-open `[start, end)`.
`JSON_POINTER` stores only the logical JSON path. The record `version_hash` protects the
record bytes, avoiding ambiguous byte anchors when identical values occur in multiple JSON
fields.
Array indexes are strict non-negative decimal indexes without leading zeros; negative,
signed, non-numeric, leading-zero or out-of-range indexes are rejected.

## Failure Behavior

The adapter fails closed with typed `SourceFailure` values for:

- missing archive roots
- missing stable account identity unless `source_instance_id` is explicitly supplied
- malformed archive data wrappers
- unexpected JavaScript assignment names for known archive members
- malformed JSON
- manifest/account identity mismatch
- source instance identity drift after pointer creation
- duplicate tweet ids
- duplicate tweet-header ids
- missing tweet ids
- wrong source system
- wrong source instance
- changed source versions
- unsupported coordinates
- byte ranges outside the canonical record
- invalid JSON pointer paths or array indexes
- missing archived tweet media for tweets that declare media entities
- archive member escape
- duplicate zip member names

Record enumeration raises `SourceEnumerationError` with a typed `SourceFailure` rather
than returning an empty iterator for malformed or unavailable exports. A valid export with
zero tweets still enumerates as empty.

Verification re-reads the current archive data before trusting a pointer, so mutation
after pointer creation fails closed instead of validating against stale cached bytes.

The adapter does not write to PostgreSQL and does not create `EvidenceRef` rows.
