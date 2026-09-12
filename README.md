# Historian

Historian is a provenance-first context intake and evidence qualification system.

It imports external historical sources through source-specific adapters, preserves
re-verifiable source identity and versioning, normalizes records without copying
authority away from the original material, and adjudicates what conclusions that evidence
can support.

The current pre-1.0 release is `v0.1.0a2`. It includes source adapters,
question-bound adjudication and the default Linux peer-credential libSQL service.
The frozen original baseline remains available at `v0.0.0-original`.

See [installation and backup/restore](docs/release-operations.md),
[migration](docs/migration.md), and [the remaining 1.0 gates](docs/road-to-1.0.md).

Historian remains private while public-release safeguards are still under review.

Persistence and security guarantees are specified in [Persistence v1](docs/persistence-v1.md).
The only database is the [libSQL Linux service profile](docs/libsql-profile-v3.md).
Complete application stores use its authenticated socket API; no server-database driver
or fallback is installed. Run `historian profile` to inspect the exact profile identity.

See [application persistence](docs/application-persistence.md) for store methods and
staged case-queue intake. Existing libSQL installations need the explicit schema upgrade
in [migration](docs/migration.md) before running v0.1.0a2.
