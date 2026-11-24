# sqlite-linux-peercred-service-v1 / version 4

Backend: SQLite through Python's standard-library `sqlite3`; no third-party database
driver. Certified runtime: Python 3.14.5 linked to SQLite 3.46.1, as shipped in the
proof image `python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97`.
Contract: Persistence v1 unchanged.
Profile digest: `ac319a88ff754bcaced495018df295d9b12a12a069ee94b361de376386e338f1`.

Linux local Unix socket service, Python 3.14.5, standard-library sqlite3 linked to SQLite 3.46.1 (image python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97); no third-party database driver; service UID 10000; private 0700 database directory and 0755 socket directory; WAL with foreign_keys enabled; no remote database endpoint.

Version 4 supersedes [libSQL profile version 3](libsql-profile-v3.md). It changes only
the backend family and the deployment model. These are unchanged:
- the trust boundary, the threat model and the `access.py` capability matrix;
- the schema and the socket protocol;
- the 20 invariants and 43 probes.

v3 evidence does not prove v4. CI must independently test this exact profile.

## Trust boundary

The trust boundary is unchanged from v3:
- One service process, running as UID 10000, owns the database file and its WAL/SHM
  sidecars. Callers never open the file.
- Every operation is authorised from the caller's kernel `SO_PEERCRED` UID, mapped to a
  fixed capability for UIDs 10001–10009. Caller JSON cannot choose its authority.
- Database directories are service-owned and 0700. Socket directories are service-owned
  and not caller-writable.

The host must also prevent ordinary callers from acquiring the service UID, root, ptrace,
container control, a shared credential or raw file access.

## Certified runtime

The runtime is part of the profile and is written as constants, not read from the running
interpreter, so the digest is the same on every machine (`CERTIFIED_RUNTIME` in
`historian/libsql_store/profile.py`). The checks are:
- The proof suite fails when the running Python or SQLite differs from the certified
  runtime.
- Every evidence report records the runtime it ran on.
- `scripts/prepare-release.py` rejects evidence from any other runtime.
- `historian profile` prints the running runtime and `runtime_is_certified`.
- The proof image is pinned by digest, both in `deployment/libsql/Dockerfile` and in the
  profile (`CERTIFIED_IMAGE`). A core test fails if the two differ.
- The service refuses to start on SQLite older than 3.38.0, the first release with
  built-in JSON functions, which the schema needs.

A different runtime or base image needs a new profile version and fresh evidence.
Updating the base image therefore means changing the pinned digest, re-running the
proof, and bumping the profile version.

## Constraint signals

Only the exact named `assertion_origin_binding` CHECK failure earns PV17 rejection
evidence. That means a `sqlite3.IntegrityError` with code `SQLITE_CONSTRAINT_CHECK` and
the exact message. Every other constraint failure is reported on the wire as
`ValueError`, as under libSQL 0.1.11, so the socket protocol and its error detail are
unchanged. Unrelated errors leave the probe unproven.

## Scope

Conformance is not a production-host certificate and not power-loss certification.
Trusted components and excluded threats are declared in
`historian/libsql_store/profile.py`; its complete canonical content determines the
digest. The module path keeps its historical name (see
[the design note](sqlite-migration-design.md)). Further reading:
- [migration.md](migration.md): migrating from v3;
- [release-operations.md](release-operations.md): operations.

There is no remote listener, arbitrary SQL endpoint, mutable role selector, or supported
alternate database engine.
