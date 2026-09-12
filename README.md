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

Persistence and security guarantees are specified in [Persistence v1](docs/persistence-v1.md).
Conformance applies to an exact deployment profile; the current PostgreSQL candidate has
known gaps and is not yet conforming.

The default application backend is the [libSQL Linux service profile](docs/libsql-profile-v2.md) implements the same
contract with peer-credential capability isolation. Its independently reported conformance
result applies only to that exact named/versioned profile. PostgreSQL remains a separately tested legacy backend.

Run `historian profile` to inspect the default, `historian serve --corpus PATH` to
start the service, and `historian request OPERATION --data-file request.json` from a
provisioned capability UID. See [migration and upgrades](docs/migration.md).
