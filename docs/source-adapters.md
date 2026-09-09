# Source Adapter Architecture

Historian owns normalized provenance and qualification. Adapters own understanding how a
specific external source is addressed and read.

The shared adapter contract is intentionally source-agnostic. It knows nothing about
Google, Gmail, Drive, Calendar, Keep, ChatGPT, JSON, MBOX, ZIP archives, markdown, local
paths or cloud APIs. Those details belong inside concrete adapters.

## Pipeline

```text
External Source
      |
      v
Source Adapter
      |
      +-- enumerate records
      +-- identify immutable source
      +-- calculate or verify version
      +-- address exact bytes or spans
      +-- fail closed
      |
      v
Normalized Intake Record
      |
      v
Evidence Candidate
      |
      v
Verified EvidenceRef
      |
      v
Historian adjudication
```

## Contract

The protocol in `historian/source_adapter.py` is the design boundary for future adapter
implementations:

```python
class SourceAdapter(Protocol):
    source_system: str

    def enumerate_records(self) -> Iterable[SourceRecord]: ...
    def version_of(self, record_id: str) -> str | None: ...
    def read(self, pointer: SourcePointer) -> bytes | None: ...
    def verify(self, pointer: SourcePointer) -> VerifiedSource | None: ...
```

The exact strings used for `record_id`, `version_hash` and `coordinate_system` are adapter
owned. Historian requires them to be stable and exact; it does not define a Google,
ChatGPT or filesystem addressing scheme.

## Adapter Families

```text
SourceAdapter
|-- ChatGPTExportAdapter
`-- GoogleTakeoutAdapter
    |-- Gmail
    |-- Drive
    |-- Calendar
    `-- Keep
```

ChatGPT export and Google Takeout are different export families. They must not share a
parser merely because both may arrive as archives. Google Takeout product areas may share
archive traversal and containment checks, but Gmail, Drive, Calendar and Keep still own
their own record identity, version and coordinate rules.

## Invariants

- Stable identity: the same source record resolves to the same logical identifier across
  repeated imports where possible.
- Content-addressed versioning: mutable exports produce a new version or hash rather than
  silently changing old evidence.
- No copied authority: normalized text is derived material; source bytes remain
  authoritative.
- Exact provenance: every verified evidence reference traces to source system, record,
  version and coordinate or span.
- Fail closed: missing, moved, mutated, malformed or unverifiable source material does not
  become verified evidence.
- Idempotent intake: importing the same export twice does not create semantically duplicate
  source records.
- Adapter isolation: a source claiming one adapter cannot be verified using another
  adapter's bytes.
- No path escape: archive members and filesystem-backed adapters cannot escape their
  declared source root.
- Redaction is explicit: redacted content never masquerades as original bytes.
- Private data is not a fixture dependency: CI uses synthetic exports constructed to
  exercise the same contracts.

## Non-Goals For This PR

This architecture definition does not implement a ChatGPT export parser, a Google Takeout
parser, database ingestion tables, background import workers or adjudication changes.
