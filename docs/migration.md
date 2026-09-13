# Migration and upgrade

The current source uses Python's standard-library `sqlite3` as its only database driver.
The Linux peer-credential service, capability UIDs, schema and socket operations are
unchanged. Prior libSQL release downloads/tags were withdrawn during the history scrub;
this change does not publish a replacement release or imply that an operator database
has already migrated.

## Existing local libSQL installations

The previous service used an unencrypted local SQLite-format file. This implementation
retains its exact schema and reads that format directly; it does not export/rewrite rows
or fabricate provenance. Remote/synchronized/encrypted databases and unknown schemas
are not supported migration inputs.

1. Stop callers and the old service. Preserve a validated offline backup using the old
   environment; a raw copy of the main file alone is insufficient when WAL is present.
2. Retain the old environment for rollback. Install the new wheel into a separate
   environment with no libSQL dependency, under the same isolated service account.
3. Run `historian check --database PATH` against a protected copy first. The current
   application schema needs no upgrade. Compare durable IDs, counts, locators,
   coordinates, resolutions and lineage before directing callers to the new service.
4. Start the service with the existing protected database/socket paths. Exercise the
   declared SQLite profile on the actual host; old libSQL conformance does not transfer.
5. Roll back by stopping the new service and restoring the preserved backup into a new
   protected path with the old environment. Do not merge two independently written files.

Python API clients must update imports from `historian.libsql_store` to
`historian.sqlite_store`. The `historian` CLI commands and socket protocol are unchanged.

## Older minimal schemas

The application schema adds complete objects and their constrained dependency graph to
the older minimal storage schema. Stop the service and callers. Back up with the old release,
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
