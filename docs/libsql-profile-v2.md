# libSQL Linux peer-credential service, profile v2

**Conformance belongs to a backend plus an exact deployment/security profile, not an engine.**
This implementation is `libsql-linux-peercred-service-v1`, version **2**. Its complete definition
and SHA-256 digest are in `historian/libsql_store/profile.py`. It uses the unchanged Persistence v1
20-invariant / 43-probe catalog, property obligations, access classes, harness and evidence format.

The tested result is **CONFORMS** when all deployment probes pass. Profile v2 changes only the
PV17 assertion-origin enforcement placement: Linux `SO_PEERCRED` still authenticates the caller,
and libSQL now enforces that the persisted assertion origin is compatible with the authenticated
principal/capability tuple. The Persistence v1 catalog, PV17 permitted boundaries, harness and
expected probe results are unchanged.

## Actual deployment boundary

The supplied image runs Python **3.14.5** and the **libsql 0.1.11** Python binding. This is the
libSQL engine, not Python's sqlite3 module or the newer Turso rewrite. The
[upstream Python binding](https://github.com/tursodatabase/libsql-python) supplies local durable
connections; [Turso's reference](https://docs.turso.tech/sdk/python/reference) distinguishes these engines.
No network database, hosted account, token, external service or embedded replica is used here.

The executable service listens on a Linux Unix-domain socket. Kernel `SO_PEERCRED` identifies
its callers; request bodies never select a principal. A fixed UID map selects the allowed
operations. There is no arbitrary SQL, role-switch, finalization-bypass or mutation endpoint.
The service itself runs as UID/GID **10000** and owns the database directory with mode **0700**.
The socket directory is service-owned **0755**; the socket is connectable by callers but they
cannot replace it. Startup rejects unsafe database/socket directory ownership or permissions.

| UID | Capability | Permitted operations |
|---|---|---|
| 10001 | extractor | Candidate, claim and route creation |
| 10002 | trusted verifier | Evidence intake, configured-source verification, evidence readback |
| 10003 | designer | Question and frozen seed creation |
| 10004 | typed ingestor | Assertions whose stored context satisfies the libSQL typed constraint |
| 10005 | human reviewer | Assertions whose stored context satisfies the libSQL reviewer constraint |
| 10006 | runtime | Atomic resolution publication and published readback |
| 10007 | packet builder | Complete packet creation/finalization |
| 10008 | adjudicator | Blind packet view and human verdict insertion |
| 10009 | gold compiler | Eligible gold creation and adjudication readback |
| other | ordinary caller | Connection permitted; every operation denied |

Each capability means a separate OS identity. Do not run ordinary callers as the service UID,
root, or another capability UID. Processes sharing a UID share all its authority. In this
version there is one adjudicator identity; the service records `uid:10008`, not an unverified
human name supplied by a request. Mapping that account to a real human is the operator's task.
The assertion table stores both the requested origin and the authenticated context. For this exact
profile, libSQL accepts only `uid:10004` / `typed` / `TYPED_SOURCE` and `uid:10005` / `reviewer` /
`HUMAN_REVIEWED_PROPOSAL`. Adding identities, remote authentication, shared credentials, namespace
mappings or another service access model requires a revised profile and fresh evidence.

The Docker image supplies the filesystem ownership. A persistent deployment must use a private
volume for `/data`, populated with the image's service-owned directories. It must not mount
that volume into ordinary caller containers, expose a Docker socket to callers, grant host
privileges, or share the service UID. The proof deployment runs wholly in one disposable Linux
container; the root test orchestrator provisions and launches separate-UID processes. Root is
explicitly the trusted operator, not a simulated unprivileged actor.

## Threat model and trust limits

Ordinary and specialized caller processes may send arbitrary JSON, bypass the Python client,
try direct libSQL connections, read/write/delete database files, replace the socket, read service
process metadata, or attempt to acquire service UID. Their process identity cannot be forged
by setting `role`, `uid`, `verified_by` or `human_id` fields. Calls return the actual kernel-derived
principal and capability, which the test process cross-checks against its effective UID.

Host root, kernel compromise, service-code compromise and acquisition of another capability
identity are excluded. The boundary depends on Linux DAC and peer credentials, no sudo/setuid/
ptrace privileges for callers, no host mount exposing private files, and exclusive operator
control of the fixed identity map. These are deployment requirements, not properties of libSQL.
The service has no raw DB credential to leak; exclusive filesystem access is its storage authority.

Like PostgreSQL's verifier capability, UID 10002 is trusted to verify external source bytes before
submitting adapter evidence. The generic `evidence` operation persists a validated EvidenceLocator;
it cannot reread every future source system. Compromising that verifier is outside the source-trust
model and permits false evidence. The `verify_source` operation separately rereads a configured
RAG source with the existing RagV1SourceReader, checks version/span/anchor, and persists only after
success. A mismatch leaves no evidence. This does not prove a source assertion is true, a Twitter
archive complete, or arbitrary adapter code trustworthy. No source adapter behavior is changed.

## Persistence and enforcement

`repository.py` implements durable operations and `schema.sql` defines this profile's schema.
All mutations use parameterized statements. Foreign keys are enabled on every connection;
WAL and synchronous FULL are used. Seed and packet membership is immutable after sealing;
packet sealing checks exact evidence membership against the frozen seed. Resolution publication
inserts the header, dependency edges and seal in one transaction. Only sealed resolutions are
visible through the service read API. Database triggers reject later dependency insertion and
UPDATE/DELETE on committed rows. New evidence revisions use distinct identities.

Open-ended locator fields are persisted directly, including source instance, source record,
version, coordinate system and canonical named coordinate parts, plus content hash and redaction
state/reference. No OTHER or LINE coercion is performed. Structured Unicode and empty-string
coordinate values survive durable readback and service restart. Candidate-to-evidence binding
uses the canonical locator and anchor; claim/routing-to-question binding and all stored dependency
identities use database foreign keys. Gold insertion rejects insufficient adjudications.

Identity authentication, the operation allowlist and blind-reader access are service mechanisms.
Database constraints independently enforce identity uniqueness, question binding, referential
integrity, mutation resistance, transactional publication and assertion-origin compatibility.
For PV17, the service derives `writer_principal` and `writer_capability` from `SO_PEERCRED` and
passes the requested origin through to storage. libSQL is the component that accepts or rejects the
origin/principal/capability tuple. Request fields such as `principal`, `writer`, `role` or
`writer_capability` cannot override the kernel-derived context, and there is no raw-SQL or
capability-context setter endpoint. The named `assertion_origin_binding` CHECK produces an
exact driver failure signature, sanitized to `assertion_origin_binding` by the service.
PV17 rejection evidence requires that error; unrelated storage failures leave the probe unavailable.

The immutable DML triggers are not protection against the trusted storage owner dropping tables,
disabling constraints or editing the file. The tested OS boundary prevents ordinary capability
UIDs from obtaining that owner's direct storage access. Constraint probes deliberately run as
storage owner and send raw SQL, separately from those hostile caller-file probes. Their evidence
labels distinguish service UID/root test authority from ordinary actors.

This is one standalone persistence implementation for the declared contract, not a migration
of production PostgreSQL data or a replacement for the full legacy database interface. There
is no automatic default switch, live service deployment, data import or migration in this PR.
No power-loss/crash-recovery certification is claimed by a process-restart test.

## Proof and artifacts

Run the exact deployment proof from the repository root:

```sh
scripts/ci-libsql-profile.sh
```

The script builds the image, runs a disposable container, collects artifacts with `docker cp`,
and removes only that test container. It needs neither a host database mount nor production
credentials. Tests exercise all 43 shared scenarios, plus each of the nine capabilities and
an unassigned UID attempting file access, mutation, service UID escalation and raw libSQL access.
Each capability also attempts unsupported SQL/role/finalization/mutation socket operations.
The restart test proves stored coordinates, evidence and assertion attribution remain addressable
after a new service process starts. Successful owner file access supplies the positive control for
caller denials.

Artifacts (default `/tmp/historian-libsql-artifacts/`):

- `historian-libsql-conformance.json`: unchanged ConformanceResult format, exact profile name,
  version, digest, actual actors/access paths, property coverage and 43 observations.
- `historian-libsql-boundaries.json`: supplemental direct-file and raw-interface evidence,
  bound to the same profile digest, recording expected and actual denials per actor.

Supplemental probes are required regression gates, not additions or exemptions to the catalog.
If they fail, CI fails even if the shared scenario report is present. No deployment should claim
CONFORMS from that report while disregarding failed supplemental boundary evidence.

CI runs the PostgreSQL profile independently without modifying its schema, roles, probes or
expected failure set, and retains separate artifacts and summaries for both profiles. Both
summaries include exact name, version, digest and status. Missing artifacts say NOT_TESTED.

| Profile | Conformance | Demonstrated failures |
|---|---|---|
| postgresql-role-isolated-v1 v1 | DOES_NOT_CONFORM | PV05.bypass, PV11.normal/integrity, PV12.normal/integrity |
| libsql-linux-peercred-service-v1 v1 | DOES_NOT_CONFORM | PV17.normal, PV17.bypass (service placement where DB required) |
| libsql-linux-peercred-service-v1 v2 | CONFORMS | none |

The PostgreSQL profile digest remains
`cee528e2a6a00e5230c91079fe703e5971898229466667d81d1c966e13006906`.
The historical v1 libSQL profile digest was
`7dcacb02a640474c6d3ee1824512d093555f7e41f8efef7125edfcd9beb891d0`.
The v2 libSQL profile digest is
`d87dd43b3a6826e4338539470b975b89d331539d9f4f689f537e56e7f1253d87`.
Both versions are separate conformance claims because security-relevant enforcement changed.
The three taxonomy/Twitter review findings remain untouched and retain their original blockers.
