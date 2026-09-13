# Unreleased — standard-library SQLite

The current source replaces the libSQL driver with Python's standard-library `sqlite3`.
The Linux peer-credential boundary and application schema remain unchanged. The new
`sqlite-linux-peercred-service-v1` profile has its own runtime-bound digest and must earn
conformance independently. See docs/migration.md for existing local database handling.
No new release or tag is created by this change; GitHub-retained history cleanup remains
a release blocker.

# Historical v0.1.0a2 — libSQL only (withdrawn)

At that release, libSQL was the only database in the supported source tree, install dependencies,
deployment path, case-queue tool and CI. The retired backend's implementation remains
in rewritten Git history; the old release tags were withdrawn during sanitization.
No existing external database was modified.

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
