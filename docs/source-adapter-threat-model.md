# Source Adapter Threat Model

Source adapters sit on the trust boundary between private external context and Historian's
provenance-bound evidence. Their failure mode must be refusal, not quiet substitution.

## Threats

- Source mutation: an external export changes while old evidence still cites the previous
  content.
- Source confusion: bytes from one source system are used to verify a pointer claiming
  another source system.
- Record collision: repeated imports create duplicate logical records for the same source
  item.
- Path escape: archive members or filesystem paths escape the declared source root.
- Malformed export: partial, corrupt or unsupported source material is normalized anyway.
- Coordinate drift: a pointer's span resolves to different material under the same
  version.
- Redaction ambiguity: redacted bytes are treated as original bytes.
- Fixture leakage: private operator data becomes required for CI or committed tests.

## Required Controls

- Bind verification to the adapter declared by `source_system`.
- Recompute source versions from bytes before trusting a pointer.
- Return `None` or otherwise reject unverifiable reads before producing `VerifiedSource`.
- Hash the exact bytes that were verified.
- Preserve normalized text as derived material only.
- Reject path traversal and absolute path addressing inside archives and filesystem roots.
- Represent redacted material with explicit redaction state and a redaction reference.
- Build synthetic fixtures that exercise identity, versioning, coordinate and failure
  contracts without depending on private exports.

## Acceptance Condition

A future adapter author can implement ChatGPT Export, Google Takeout Gmail, Google Drive,
Google Calendar, Google Keep or another source without changing Historian's adjudication
core or redefining provenance semantics.
