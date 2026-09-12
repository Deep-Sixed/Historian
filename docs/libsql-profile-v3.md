# libsql-linux-peercred-service-v1 / version 3

Backend: libSQL 0.1.11. Python: 3.14.5. Contract: Persistence v1 unchanged.
Profile digest: `ce6b23bed85d14c79e3e342b332f3979733f9a860820b57a630faede5d27124b`.

Linux local Unix socket service, Python 3.14.5, libsql Python 0.1.11; service UID 10000; private 0700 database directory and 0755 socket directory; WAL with foreign_keys enabled; no remote database endpoint.

Kernel SO_PEERCRED maps service UID 10000 and capability UIDs 10001–10009 to a
fixed capability set. Caller JSON cannot choose its authority. Database directories
are service-owned 0700, socket directories service-owned and not caller-writable.
Ordinary callers cannot acquire service UID, root, ptrace, container control, a shared
credential or raw file access. The database, WAL/SHM sidecars and service process are
within the protected storage boundary. These host assumptions must hold in deployment.

Version 3 adds the per-domain-type capability matrix in access.py, included in this
digest, and full application object persistence. It supersedes v2 without claiming that
v2's evidence proves the expanded service. CI must independently test this exact profile.
The base 20 invariants and 43 probes are unchanged. Additional application tests cover
real adjudicator outputs, abstention, question binding, atomic rollback, immutable lineage,
gold, blind-reader isolation and every unauthorized domain reader/writer combination.

Database constraints enforce assertion origin/principal/capability tuples. Only the exact
named assertion_origin_binding constraint failure earns PV17 rejection evidence. Other
errors make that probe unavailable. Identity is kernel-derived, origin matching is a
DB constraint, and capability isolation is a tested OS/service boundary.

Conformance is not a production-host certificate or power-loss certification. Trusted
components and excluded threats are declared in historian/libsql_store/profile.py, whose
complete canonical content determines the digest. Operations, installation and backup
commands are documented in release-operations.md; full store methods in
application-persistence.md. There is no remote listener, arbitrary SQL endpoint, mutable
role selector, or supported alternate database engine.
