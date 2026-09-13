# sqlite-linux-peercred-service-v1 / version 1

Backend: Python standard-library `sqlite3`, using its linked SQLite engine. Primary
deployment: Python 3.14.5 on Linux. Contract: Persistence v1 unchanged.
Run `historian profile` for the exact digest. The profile definition includes the actual
Python and SQLite versions, so a different linked engine or Python runtime gets a different
digest and cannot reuse conformance evidence from another build. Run release-evidence
validation in the same runtime as the tested deployment.

Linux local Unix socket service; service UID 10000; private 0700 database directory and
0755 socket directory; WAL with foreign_keys enabled; no remote database endpoint.
The runtime has no external database-driver dependency.

Kernel SO_PEERCRED maps service UID 10000 and capability UIDs 10001–10009 to a
fixed capability set. Caller JSON cannot choose its authority. Database directories
are service-owned 0700, socket directories service-owned and not caller-writable.
Ordinary callers cannot acquire service UID, root, ptrace, container control, a shared
credential or raw file access. The database, WAL/SHM sidecars and service process are
within the protected storage boundary. These host assumptions must hold in deployment.

This is a new SQLite profile, version 1. It retains the previous service's per-domain-type
capability matrix in access.py and full application object persistence. The matrix is
included in the digest. Prior libSQL evidence does not prove this profile; CI must
independently test it.
The base 20 invariants and 43 probes are unchanged. Additional application tests cover
real adjudicator outputs, abstention, question binding, atomic rollback, immutable lineage,
gold, blind-reader isolation and every unauthorized domain reader/writer combination.

Database constraints enforce assertion origin/principal/capability tuples. Only the exact
named assertion_origin_binding constraint failure, with `IntegrityError` and SQLite's
`SQLITE_CONSTRAINT_CHECK` error code, earns PV17 rejection evidence. Other
errors make that probe unavailable. Identity is kernel-derived, origin matching is a
DB constraint, and capability isolation is a tested OS/service boundary.

Conformance is not a production-host certificate or power-loss certification. Trusted
components and excluded threats are declared in historian/sqlite_store/profile.py, whose
complete canonical content determines the digest. Operations, installation and backup
commands are documented in release-operations.md; full store methods in
application-persistence.md. There is no remote listener, arbitrary SQL endpoint, mutable
role selector, or supported alternate database engine.
