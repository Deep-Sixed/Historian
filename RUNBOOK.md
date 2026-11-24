# Historian operations

SQLite, through Python's standard library, is the only supported database (profile v4).
Use the Linux peer-credential service; never
hand ordinary callers a database file or service-owner capability.

- [Installation, backup, restore and upgrade](docs/release-operations.md)
- [Exact deployment profile](docs/sqlite-profile-v4.md) (supersedes [libSQL v3](docs/libsql-profile-v3.md))
- [Migrating a libSQL v3 database](docs/migration.md)
- [Application store API](docs/application-persistence.md)
- [Persistence v1 contract](docs/persistence-v1.md)

Run core tests with `python -m pytest -q -m 'not deployment'` and the
real Linux enforcement suite with `scripts/ci-sqlite-profile.sh` (profile v4). `scripts/ci-migration-compat.sh` migrates a genuine
libSQL v3 database and carries it back. Installed-wheel
validation uses `scripts/ci-package.sh`. Synthetic queue checks run in core CI.
Run `python scripts/public_release_guard.py` before publishing source or fixtures.
Representative real-corpus validation remains a separate, locally operated release gate.
