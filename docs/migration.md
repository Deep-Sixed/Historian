# Application default and migration

The application CLI defaults to libsql-linux-peercred-service-v1 v2. It does not
silently fall back to PostgreSQL or expose an embedded unrestricted connection.
`historian profile` prints configuration identity, not a conformance claim about
an untested installation. Only deployments meeting the declared profile qualify.

The default change affects new CLI deployments only. It does not modify existing
PostgreSQL data or redacted services. Keep an existing installation on its previous
version until an explicit data migration has been validated.

There is no automatic PostgreSQL importer in this pre-1.0 release. The two schemas
are not interchangeable: PostgreSQL cannot losslessly represent all locators or
coordinates, and published dependencies may already have changed. SQL table copies
cannot manufacture missing provenance. Preserve a database backup and the original
sources; re-ingest through verified source adapters and capability-scoped service
operations, preserving externally referenced identities where possible. Re-adjudicate
rather than invent historical writer identity. Compare counts, identities, locators,
relationships and published results before switching callers. Retain the old database
read-only for audit and rollback. Do not retire PostgreSQL on the strength of CI alone.

For libSQL upgrades: stop callers and the service, take and validate a backup, install
the pinned release in a new environment, and run its schema/restore checks before
restarting. Only the release's exact schema is supported. Unknown/older schemas must
fail closed; no automatic destructive conversion is permitted. Restore the old backup
with the old application version to roll back. Never run old and new services over the
same database simultaneously. See the release operations guide for commands.
