# Application persistence

SQLite is Historian's only database. `historian.sqlite_store.stores.Store` implements
ProposalStore, AssertionStore, ResolutionStore, SeedStore, PacketStore,
AdjudicationStore and GoldStore. It is a socket client, not a database connection.
Constructing one grants no authority. The service checks the real kernel UID against
`historian/sqlite_store/access.py` on every put/get; that exact matrix participates in
the version 1 profile digest.

`Store.put(value)` / `Store.get(type_name, id)` persist complete immutable domain objects.
The wire codec only constructs a closed set of Historian dataclasses and enums. There
is no pickle, dynamic import, arbitrary SQL or identity-switch method. Named put/get
methods implement the existing capability protocols. EvidenceLocator intake remains
open-ended. The old in-memory EvidenceRef model still represents LINE evidence; the
legacy verifier bridge rejects other coordinate systems instead of coercing them.

The application tables augment the evidence/security schema. They preserve every field
of resolutions (including unresolved reasons and revision lineage), claims, routes and
alternates, proposed/asserted relations, reviews, seeds, packets, adjudications and gold.
Database foreign keys enforce typed dependencies and question binding. Seal triggers
require complete reference edges, which become immutable at publication. Writes, their
dependencies and seals share one transaction. A missing or cross-question dependency
rolls back the entire object. Support profile is derived from actual dependency edges.

The service independently compares embedded evidence references with verified storage.
Full source passages are retained as immutable ordered packet snapshots, accessible through
Store.get_packet_snapshot only to packet readers. Packet writes must match the seed's ordered evidence and question, and the service
re-reads configured source bytes. Blind packet reads omit internal seed identity;
family, invariants, proposals, system outputs and gold remain inaccessible. Reviewer
and adjudicator identities are overwritten from kernel credentials. Gold's base FK
chain and additional object bindings reject inconsistent or insufficient verdicts.

## Case queue

`cases/build_queue.py` now uses the service exclusively. Choose a unique `--run-id`
and a readable `--corpus` copy identical to the service's approved corpus. First run
without `--apply` to inspect the plan. Execute these stages separately under their
actual capability UIDs, using the same run ID and source copy:

1. UID 10001: `--stage candidates --apply`
2. UID 10002: `--stage verify --apply`
3. UID 10003: `--stage seeds --apply`
4. UID 10007: `--stage packets --apply`

The tool never changes UID or retrieves credentials. Writes are append-only and duplicate
identities are rejected. A failed stage is reported, not silently skipped. For a revised
queue use a new run ID; retain the prior records and evidence for audit.
