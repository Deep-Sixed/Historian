# Unreleased — SQLite profile v4

The libSQL 0.1.11 driver is replaced by Python's standard-library `sqlite3`. The package
now has no runtime dependencies. One service process still owns the database, and every
operation is still authorised by the caller's kernel UID. The schema, socket protocol
(including error names), capability matrix and Persistence v1 catalog are unchanged.

- New profile `sqlite-linux-peercred-service-v1` version 4 (digest `ac319a88…38f1`).
  It supersedes libSQL v3, whose record and digest are unchanged. The certified
  runtime (Python 3.14.5, SQLite 3.46.1) and the proof image, pinned by digest, are fixed
  in the profile. Evidence from any
  other runtime is rejected by the release gate.
- `historian migrate --source OLD --destination NEW [--apply]` moves a stopped v3
  database to a new file. It is a dry run unless `--apply` is given, and it never
  writes the source. It verifies the exact schema, integrity, foreign keys, and
  per-table row counts and content digests. See docs/migration.md.
- `historian profile` also reports the running runtime and whether it is certified.
- The Python module path `historian.libsql_store` is unchanged, and so is
  `historian.libsql_store.profile`. The profile object there is renamed from `LIBSQL` to
  `SQLITE`: any import of the old name fails, rather than silently getting v4.
- CI runners are pinned to `ubuntu-24.04`. A new job migrates a genuine libSQL 0.1.11
  database and carries it back.

No release or tag is created. The GitHub cleanup gate in docs/history-sanitization.md
still applies.

# Historian v0.1.0a2 — libSQL only

libSQL is now the only database in the supported source tree, install dependencies,
deployment path, case-queue tool and CI. The retired backend's implementation remains
available only in historical release tags; no existing external database was modified.

Complete application stores now persist resolved/unresolved outputs, typed provenance
edges, review events, ordered seeds/packets, independent adjudications and gold through
the authenticated Unix socket service. Every domain type has an explicit read/write
capability matrix, bound into profile version 3's digest and tested under real UIDs.
Question-bound foreign keys, publication seals and immutable dependency edges remain
storage-enforced. Persistence v1's 20 invariants and 43 probes are unchanged.

Existing libSQL v2 installations require an explicit additive schema upgrade. Back up
with the previous release, retain its wheel, then follow docs/migration.md. Unknown
schemas fail closed. Restore/rollback never overwrites an existing database.

The release includes installed wheel/source distributions and exact conformance,
base bypass and application-boundary evidence. Production host certification, importing
an external legacy database and proving real-corpus capacity remain separate operator
work; this release does not fabricate missing historical provenance.

Co-authored-by: Codex <codex@openai.com>
