# Migration and upgrade

SQLite through Python's standard-library `sqlite3` is the only supported database
([profile v4](sqlite-profile-v4.md)). libSQL 0.1.11 ([profile v3](libsql-profile-v3.md))
is no longer installed. Before v0.1.0a2, older backends existed; their implementations
and evidence remain in v0.1.0a1 and earlier tags.

## libSQL (profile v3) → SQLite (profile v4)

A v3 database is a local SQLite-format file with exactly the v4 schema. The migration
never opens it for writing and never converts it in place. Instead it builds a new,
verified file. See the [design note](sqlite-migration-design.md) for the reasoning.

Supported inputs are unencrypted local files with the exact v3 schema. These are
refused:
- remote, synchronized (embedded-replica) or encrypted libSQL databases;
- files with an uncheckpointed WAL;
- unknown schemas.

Older minimal schemas must first be upgraded with the v3 release (next section).

1. **Stop** the callers and the v3 service. Keep the v3 environment (its wheel and
   `libsql==0.1.11`) for rollback. Take a validated backup with the v3 release:
   `historian backup --database OLD --destination /protected/backups/v3-final.db`.
2. **Install** the v4 wheel into a separate environment. `historian profile` should
   report profile version 4 and `"runtime_is_certified": true`.
3. **Dry run** as UID 10000. This is the default and writes nothing:

   ```sh
   historian migrate --source /var/lib/historian/private/historian.db \
     --destination /var/lib/historian/private-v4/historian.db
   ```

   Every step runs against a temporary copy, which is then deleted:
   - take the service's exclusive lock on both paths;
   - check the exact schema, `integrity_check` and `foreign_key_check`;
   - record every table's row count and content SHA-256;
   - copy with the SQLite online backup API, then re-verify the copy through the
     service's own `connect()`;
   - check WAL mode and that the source bytes are unchanged.

   The JSON report lists every table with its row count and digest. Review it.
4. **Apply** by repeating the command with `--apply`. The verified copy is linked into
   place, which never overwrites anything. `DESTINATION.migration.json` (0600) records:
   - the source and copy hashes and the per-table inventory;
   - the v3 and v4 profile identities and the runtime.

   Migrating the v3 backup from step 1 instead of the live file is equally valid.
5. Run `historian check --database NEW`. Point the unit's `--database` at `NEW` (and its
   permitted writable paths), start the v4 service, and verify three things from the
   capability accounts:
   - an authorised request succeeds;
   - an unauthorised request is rejected;
   - existing records are readable.

   v3 conformance evidence does not transfer: exercise the v4 profile on the host.

### Rollback

The migration never writes the v3 file, so rollback is:
1. stop the v4 service;
2. switch the unit back to the retained v3 environment and the original database path;
3. start it.

Writes accepted by v4 after the cutover exist only in the new file. To keep them, stop
v4 and run `historian migrate --source NEW --destination ROLLBACK --apply` with v4. Then
start v3 on `ROLLBACK`. libSQL 0.1.11 opens, checks and appends to such files; CI proves
this in `scripts/ci-migration-compat.sh`. Never merge two files that were written
independently.

## Older libSQL minimal schemas (v2 → v3)

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
