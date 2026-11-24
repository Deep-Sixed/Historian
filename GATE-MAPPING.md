# Release gate mapping

| Guarantee | Real enforcement / tests |
|---|---|
| All 20 Persistence v1 invariants | Unchanged catalog/harness; 43 probes in tests/sqlite_probe.py |
| Ordinary caller bypass resistance | 124 supplemental probes in tests/test_sqlite_profile.py |
| Complete application outputs and gold lineage | tests/test_sqlite_application.py |
| Every domain type's denied readers/writers | Full real-UID matrix in tests/test_sqlite_application.py |
| Unsupported schema rejection, coherent backup/restore, upgrade | tests/test_sqlite_storage.py |
| v3 → v4 migration: dry run, never in place, verified copy, refusals | tests/test_sqlite_migration.py |
| Genuine libSQL 0.1.11 database migrated and carried back | scripts/ci-migration-compat.sh |
| Evidence bound to the certified runtime | tests/test_sqlite_profile.py, scripts/prepare-release.py |
| Installed wheel independent of source checkout | scripts/ci-package.sh |
| Behavioral B1–B8, structural gates, source verification | Core and Source Adapter test suites |

The application tests preserve the former backend's high-value regressions: claim
proposals have real identities, claims/routes belong to their resolution's question,
refused relations are not recorded as support, unresolved outcomes round-trip, output
lineage remains immutable, runtime cannot author claims, blind readers cannot inspect
internal metadata, and insufficient packets cannot become gold. The backend's old
role/grant implementation tests were replaced by real UID/service/storage tests.

Prior backend code and its independent nonconformance evidence remain in historical
release tags, not in the supported runtime or CI. A green workflow cannot replace the
exact profile result. See docs/application-persistence.md for the new API boundary.
