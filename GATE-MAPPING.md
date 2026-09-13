# Release gate mapping

| Guarantee | Real enforcement / tests |
|---|---|
| All 20 Persistence v1 invariants | Unchanged catalog/harness; 43 probes in tests/sqlite_probe.py |
| Ordinary caller bypass resistance | 124 supplemental probes in tests/test_sqlite_profile.py |
| Complete application outputs and gold lineage | tests/test_sqlite_application.py |
| Every domain type's denied readers/writers | Full real-UID matrix in tests/test_sqlite_application.py |
| Unsupported schema rejection, coherent backup/restore, upgrade | tests/test_sqlite_storage.py |
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
