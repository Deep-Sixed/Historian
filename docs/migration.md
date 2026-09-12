# Migration and upgrade

libSQL is the only supported database from v0.1.0a2 onward. There is no legacy server,
driver, SQL dialect adapter, role provisioning, fallback or database-specific CI job.
Historical implementations and evidence remain available in v0.1.0a1 and earlier tags.

## Existing libSQL installations

Version 3 adds complete application objects and their constrained dependency graph to
the version 2 storage schema. Stop the service and callers. Back up with the old release,
retain that release's wheel, then install the new release in a separate environment.
As service UID 10000, run:

```sh
historian upgrade --database /var/lib/historian/private/historian.db
historian check --database /var/lib/historian/private/historian.db
```

The upgrader accepts only the exact previous or current schema, preserves existing rows,
adds application tables and their immutability triggers in a transaction, and is repeatable.
Startup never silently upgrades. Unknown schemas fail closed. Rollback means restoring
the old backup into a new path with the old release; do not point the old release at an
upgraded database. This upgrade does not invent complete application metadata for old
minimal conformance records. Existing minimal records remain addressable through their
original service operations; new complete objects use Store.put/get.

## Retired backend data

No live legacy database has been modified. If one exists, retain its backup and historical
release tooling for audit/export. This repository deliberately does not retain a second
database driver as a migration dependency. Re-ingest original sources through verified
adapters and write complete objects under the appropriate capabilities. Reconcile durable
IDs, source identity/version, coordinates, references, outcomes and counts before switching
callers. Missing historical coordinates or writer identity cannot be reconstructed truthfully
by copying tables. Any future import of an external export must fail on unrepresentable
records and be a separately validated operator task; it must not fabricate provenance.
