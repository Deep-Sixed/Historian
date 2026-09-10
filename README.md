# Historian

Historian is a provenance-first context intake and evidence qualification system.

It imports external historical sources through source-specific adapters, preserves
re-verifiable source identity and versioning, normalizes records without copying
authority away from the original material, and adjudicates what conclusions that evidence
can support.

The repository currently contains:

- the frozen original baseline at `v0.0.0-original`
- provenance hardening for question-bound adjudication
- PostgreSQL migration and CI gates for security/invariant tests
- the Source Adapter v1 contract
- the first production adapter, `TwitterExportAdapter`

Historian remains private while public-release safeguards are still under review.
