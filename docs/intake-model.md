# Intake Model

Historian intake separates source-specific reading from provenance-bound qualification.
Adapters turn external material into verified source bytes and normalized intake records.
Historian then turns normalized records into evidence candidates and later verified
evidence references.

## Source Pointer

A `SourcePointer` names:

- `source_system`: the adapter-owned source family, such as a future ChatGPT export adapter
  or Google Takeout product adapter.
- `record_id`: the stable logical record identity inside that source system.
- `version_hash`: the content-addressed immutable version of that record.
- `coordinate_system`: the adapter-owned addressing scheme for the cited material.
- `start` and `end`: exact coordinates within that scheme.

The pointer is not a path. It is not trusted because it exists. It becomes useful only when
the adapter that owns `source_system` verifies it against source bytes.

## Source Record

A `SourceRecord` is what an adapter enumerates before extraction. It is the smallest
logical external item that can be imported idempotently. For different adapters, that may
mean a conversation, message, email, drive object, calendar event, note or another
source-owned unit.

Repeated imports of the same export should resolve to the same `record_id` and
`version_hash`. If a mutable source changes, the adapter must produce a different
`version_hash`.

## Verified Source

A `VerifiedSource` binds a pointer to bytes and a hash of those bytes. Verification is
adapter-owned because only the adapter knows whether a pointer is valid for its source.

If verification cannot establish source identity, version and coordinates, it returns no
verified source. It must not return best-effort content.

## Normalized Intake Record

A `NormalizedIntakeRecord` is derived text suitable for indexing, extraction and candidate
generation. It carries a hash of the normalized text, but that hash does not replace the
source hash.

Normalized text has no independent authority. Evidence remains tied back to the
`VerifiedSource` and its pointer.

## Evidence Candidate Boundary

An evidence candidate may be model-produced or otherwise extracted, but it must cite the
source pointer it claims to come from. A later verifier must re-read the source through the
declared adapter before creating an `EvidenceRef`.

That preserves the existing Historian rule: proposals do not become authority merely
because they are well formed.

## Idempotence

Intake idempotence is based on logical source identity plus content-addressed version. Two
imports of the same source record and version should converge to the same source record
identity. New evidence candidates may still be regenerated, but they must not imply a new
underlying source record when the source did not change.
