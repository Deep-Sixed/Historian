# Historian operations

SQLite is the only supported database. Use the Linux peer-credential service; never
hand ordinary callers a database file or service-owner capability.

- [Installation, backup, restore and upgrade](docs/release-operations.md)
- [Exact deployment profile](docs/sqlite-profile-v1.md)
- [Application store API](docs/application-persistence.md)
- [Persistence v1 contract](docs/persistence-v1.md)

Run core tests with `python -m pytest -q -m 'not sqlite'` and the
real Linux enforcement suite with `scripts/ci-sqlite-profile.sh`. Installed-wheel
validation uses `scripts/ci-package.sh`. Synthetic queue checks run in core CI.
Run `python scripts/public_release_guard.py` before publishing source or fixtures.
Representative real-corpus validation remains a separate, locally operated release gate.
