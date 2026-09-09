# Source Adapter Threat Model

Source adapters sit on the trust boundary between private external context and Historian's
provenance-bound evidence. Their failure mode must be refusal with a typed reason, not
quiet substitution.

## Threats

- Source mutation: an external export changes while old evidence still cites the previous
  content.
- Source confusion: bytes from one source system are used to verify a pointer claiming
  another source system.
- Instance collision: records from two accounts, exports or collections share local record
  identifiers.
- Record collision: repeated imports create duplicate logical records for the same source
  item.
- Path escape: archive members or filesystem paths escape the declared source root.
- Malformed export: partial, corrupt or unsupported source material is normalized anyway.
- Coordinate drift: a pointer's coordinate resolves to different material under the same
  version.
- Redaction ambiguity: redacted bytes are treated as original bytes.
- Fixture leakage: private operator data becomes required for CI or committed tests.

## Required Controls

- Bind verification to the adapter declared by `source_system`.
- Include `source_instance_id` in durable source identity.
- Recompute SHA-256 source versions from bytes and interpretation-critical metadata before
  trusting a pointer.
- Reject unverifiable reads before producing `VerifiedSource`.
- Return typed failure reasons for missing, unavailable, mutated, malformed, unsupported
  or integrity-failed source material.
- Hash the exact bytes that were verified.
- Preserve normalized text as derived material only.
- Use structured adapter-owned coordinates rather than forcing every source into line
  spans.
- Reject path traversal and absolute path addressing inside archives and filesystem roots.
- Represent redacted material with explicit redaction state and a redaction reference.
- Build synthetic fixtures that exercise identity, versioning, coordinate and failure
  contracts without depending on private exports.

## Failure Codes

- `NOT_FOUND`: source instance or record is not present.
- `UNAVAILABLE`: source exists but cannot currently be read.
- `VERSION_MISMATCH`: record exists, but not at the requested version hash.
- `INVALID_POINTER`: pointer shape is invalid for this adapter or outside source bounds.
- `UNSUPPORTED_COORDINATE`: coordinate system is not supported by this adapter.
- `MALFORMED_SOURCE`: source bytes cannot be parsed or interpreted safely.
- `INTEGRITY_FAILURE`: hashes, manifests or archive integrity checks fail.

## Acceptance Condition

A future adapter author can implement ChatGPT Export, Google Takeout Gmail, Google Drive,
Google Calendar, Google Keep or another source without changing Historian's adjudication
core or redefining provenance semantics. If persistence changes are needed, they should
preserve `EvidenceLocator` semantics rather than collapse new adapters into `OTHER`.
