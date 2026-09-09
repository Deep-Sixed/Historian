# Google Takeout Adapter Model

Google Takeout is an export family, not a single evidence format. A future
`GoogleTakeoutAdapter` should provide shared archive handling only where the contract is
actually common: source root containment, member enumeration, source-instance identity,
version hashing and source-system isolation.

Product-specific adapters own product-specific semantics:

```text
GoogleTakeoutAdapter
|-- Gmail
|-- Drive
|-- Calendar
`-- Keep
```

## Shared Takeout Responsibilities

- Treat the declared Takeout export root or archive as the only readable source root.
- Reject absolute paths, parent traversal and archive member names that resolve outside the
  declared root.
- Produce an opaque `source_instance_id` for the account or export lineage without
  requiring email addresses or other PII in the durable identifier.
- Version records with lowercase SHA-256 digests over source bytes plus any
  interpretation-critical metadata.
- Keep adapter identity in the `source_system` value so Google Takeout material cannot be
  verified through a ChatGPT export adapter or a local corpus reader.
- Use synthetic Takeout fixtures in CI.

## Product Responsibilities

Gmail should define message identity, thread handling, attachment handling, body
coordinates and redaction rules without leaking MBOX assumptions into the shared protocol.

Drive should define object identity, exported file variants, native Google document export
formats, revision semantics and byte/span coordinates without making local paths
authoritative.

Calendar should define event identity, recurrence handling, update identity and field
coordinates without assuming that event text is line-addressable.

Keep should define note identity, attachment identity, checklist semantics and coordinates
without assuming that every note is plain text.

## ChatGPT Export Is Separate

A `ChatGPTExportAdapter` should be a sibling of `GoogleTakeoutAdapter`, not a Takeout
sub-adapter. ChatGPT exports may arrive as archives and JSON, but that does not make them
Google Takeout. Conversation identity, message coordinates, attachment handling, export
versioning and source-instance identity are separate source semantics.

## Evidence Boundary

Takeout adapters produce `EvidenceLocator` objects after verification. They do not write
directly to the current enum-bound `EvidenceRef` shape unless a later schema design makes
that mapping lossless.

## Parser Deferral

This document does not specify the production parser. PR #4 can implement the first
conforming adapter after the contract stabilizes. The existing ChatGPT export corpus is a
good first target because Historian already has operational experience with it; Google
Takeout can then test that the contract generalizes.
