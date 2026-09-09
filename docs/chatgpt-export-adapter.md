# ChatGPT Export Adapter

`ChatGPTExportAdapter` is the first concrete Source Adapter v1 implementation. It reads a
ChatGPT data export without changing PostgreSQL persistence or Historian adjudication.

## Supported Input

The adapter supports:

- an unpacked export directory containing `conversations.json`
- a zip archive containing `conversations.json`

If `user.json` is present, it is used to derive a deterministic opaque
`source_instance_id`. Otherwise, the adapter hashes the resolved export root path. Callers
may provide `source_instance_id` explicitly when they already have a stronger export
lineage identifier.

## Record Model

Each conversation object in `conversations.json` is one `SourceRecord`.

The record id is taken from:

- `id`
- `conversation_id`

Conversation records are exposed as canonical JSON bytes using sorted keys and compact
separators. The record `version_hash` is the SHA-256 digest of those canonical bytes.

## Coordinates

The adapter supports `BYTE_RANGE` coordinates over the canonical conversation JSON bytes.
`BYTE_RANGE` follows the Source Adapter v1 rule: zero-based and half-open `[start, end)`.

## Failure Behavior

The adapter fails closed with typed `SourceFailure` values for:

- missing export roots
- malformed JSON
- duplicate conversation ids
- missing stable conversation ids
- wrong source system
- wrong source instance
- changed source versions
- unsupported coordinates
- byte ranges outside the canonical record
- zip members that attempt archive escape

It does not extract archives to disk.
