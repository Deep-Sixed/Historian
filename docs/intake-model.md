# Intake Model

Historian intake separates source-specific reading from provenance-bound qualification.
Adapters turn external material into verified source bytes and evidence locators.
Historian can then use normalized records to produce evidence candidates and later
verified evidence references.

## Source Identity

Durable source identity has four parts:

- `source_system`: the adapter family, such as `CHATGPT_EXPORT` or
  `GOOGLE_TAKEOUT_GMAIL`.
- `source_instance_id`: the source collection, account or export lineage. This should be a
  deterministic opaque identifier or fingerprint when the natural label would expose PII.
- `record_id`: the stable logical record identity inside that source instance.
- `version_hash`: a lowercase SHA-256 hex digest for the immutable record version.

This prevents collisions between Google Account A and Google Account B, or between two
independent ChatGPT exports with overlapping local record identifiers.

## Source Pointer

A `SourcePointer` names exact material within one record version:

- source system
- source instance
- record id
- version hash
- source coordinate

The pointer is not a path and is not trusted because it exists. It becomes useful only
when the adapter that owns `source_system` verifies it against source bytes.

## Source Coordinate

A `SourceCoordinate` is adapter-owned and structured as:

- `coordinate_system`
- named coordinate parts

`BYTE_RANGE` is the canonical simple case. Non-linear sources may use product-specific
coordinate systems such as `MESSAGE_PART`, `JSON_POINTER`, `ICAL_PROPERTY`, `ATTACHMENT`
or `FIELD`.

## Source Record

A `SourceRecord` is what an adapter enumerates before extraction. It is the smallest
logical external item that can be imported idempotently. For different adapters, that may
mean a conversation, message, email, drive object, calendar event, note or another
source-owned unit.

Repeated imports of the same export should resolve to the same source identity and version
hash. If a mutable source changes, the adapter must produce a different version hash.

## Verified Source

A `VerifiedSource` binds a pointer to bytes and a SHA-256 hash of those bytes.
Verification is adapter-owned because only the adapter knows whether a pointer is valid
for its source.

If verification cannot establish source system, source instance, record, version and
coordinates, it returns a typed failure. It must not return best-effort content.

## Evidence Locator

An `EvidenceLocator` is the normalized provenance bridge between adapter intake and
Historian evidence. It carries open-ended source provenance:

```text
source_system
source_instance_id
record_id
version_hash
coordinate
content_hash
material_state
redaction_ref
```

The current `EvidenceRef` and database schema are limited to `RAG_V1`, `LEDGER`, `OTHER`
and `LINE` spans. New adapters must not be collapsed into `OTHER` just to fit that shape.
A later persistence PR can store locators directly or expand the evidence schema. This PR
only freezes the design contract.

## Normalized Intake Record

A `NormalizedIntakeRecord` is derived text suitable for indexing, extraction and candidate
generation. It carries a hash of the normalized text, but that hash does not replace the
source hash.

Normalized text has no independent authority. Evidence remains tied back to the
`EvidenceLocator` and the verified source bytes behind it.

## Evidence Candidate Boundary

An evidence candidate may be model-produced or otherwise extracted, but it must cite the
locator it claims to come from. A later verifier must re-read the source through the
declared adapter before creating a trusted evidence reference.

That preserves the existing Historian rule: proposals do not become authority merely
because they are well formed.

## Idempotence

Intake idempotence is based on logical source identity plus content-addressed version. Two
imports of the same source record and version should converge to the same source record
identity. New evidence candidates may still be regenerated, but they must not imply a new
underlying source record when the source did not change.
