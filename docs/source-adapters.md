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
      +-- fail closed with typed reason
      |
      v
SourcePointer
      |
      v
VerifiedSource
      |
      v
EvidenceLocator
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
    def version_of(self, source_instance_id: str, record_id: str) -> str | SourceFailure: ...
    def read(self, pointer: SourcePointer) -> bytes | SourceFailure: ...
    def verify(self, pointer: SourcePointer) -> SourceVerificationResult: ...
```

`source_system` identifies the adapter family. `source_instance_id` identifies the
particular source collection, account or export lineage without requiring exposed PII.
`record_id` identifies the logical record inside that instance. `version_hash` identifies
the immutable record version.

Enumeration failure is also part of the shared contract. Adapters raise
`SourceEnumerationError` with a typed `SourceFailure` when a source is malformed,
unavailable or otherwise unverifiable during record enumeration. Returning an empty
iterator means the source is valid and contains no records.

The durable source identity is:

```text
(source_system, source_instance_id, record_id, version_hash)
```

## Evidence Boundary

The current Historian evidence model is intentionally closed:

```text
SourceSystem: RAG_V1, LEDGER, OTHER
CoordinateSystem: LINE
```

The old evidence model used a closed source and line-span shape. New adapters therefore cannot
truthfully feed `EvidenceRef` by mapping every external source to `OTHER`; that would
destroy source-system isolation.

The libSQL evidence table persists EvidenceLocator directly, including open-ended source
identity and canonical structured coordinates. The older in-memory EvidenceRef model
remains LINE-based; its bridge rejects unsupported coordinates instead of relabeling them.
Adapter intake does not collapse arbitrary systems into OTHER.

## Version Hash

Historian-side `version_hash` values are lowercase SHA-256 hex digests. They are not
timestamps, export sequence numbers, provider revision ids or arbitrary adapter labels.

For sources where interpretation depends on metadata, the adapter must hash a canonical
representation of:

```text
source bytes + interpretation-critical source metadata
```

If a future source needs to retain a provider revision id, that value is adapter metadata.
It does not replace `version_hash`.

## Coordinates

Coordinates are adapter-owned structures, not always linear spans. `SourceCoordinate`
carries a `coordinate_system` name and named coordinate parts. `BYTE_RANGE` is available
as a canonical simple case. It is zero-based and half-open: `[start, end)`, so `start=0`
and `end=5` identifies bytes 0 through 4. Coordinate parts are canonicalized by name and
duplicate part names are invalid, so equivalent coordinates have one durable
representation. Adapters may define coordinates such as `MESSAGE_PART`, `JSON_POINTER`,
`ICAL_PROPERTY`, `ATTACHMENT` or `FIELD` without changing Historian's core contract.

## Adapter Families

```text
SourceAdapter
|-- TwitterExportAdapter
|-- ChatGPTExportAdapter
`-- GoogleTakeoutAdapter
    |-- Gmail
    |-- Drive
    |-- Calendar
    `-- Keep
```

Twitter export, ChatGPT export and Google Takeout are different export families. They
must not share a parser merely because each may arrive as an archive. Google Takeout
product areas may share archive traversal and containment checks, but Gmail, Drive,
Calendar and Keep still own their own record identity, version and coordinate rules.

## Fail-Closed Reasons

Adapter operations reject unverifiable material with typed reasons:

- `NOT_FOUND`
- `UNAVAILABLE`
- `VERSION_MISMATCH`
- `INVALID_POINTER`
- `UNSUPPORTED_COORDINATE`
- `MALFORMED_SOURCE`
- `INTEGRITY_FAILURE`

Every failure still means no verified evidence is produced. The reason exists for
operator diagnostics and importer behavior, not for weakening the trust boundary.

## Invariants

- Stable identity: the same source record resolves to the same logical identifier across
  repeated imports where possible.
- Source-instance identity: source collection, account or export lineage is explicit and
  does not have to expose PII.
- Content-addressed versioning: mutable exports produce a new SHA-256 version hash rather
  than silently changing old evidence.
- No copied authority: normalized text is derived material; source bytes remain
  authoritative.
- Exact provenance: every verified evidence reference traces to source system, source
  instance, record, version and coordinate.
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
parser, database ingestion tables, background import workers, schema migration or
adjudication changes.
