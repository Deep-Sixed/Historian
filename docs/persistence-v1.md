# Persistence v1 contract and conformance

**Persistence conformance applies to a backend together with an exact named and
versioned deployment/security profile. A database engine does not conform in isolation.**

The target is `backend + profile name + profile version + executed evidence`.
This specification is contract version **1**. The initial candidate is
`postgresql-role-isolated-v1`, profile version **1**. PostgreSQL has no exemptions.
Its current result is **DOES_NOT_CONFORM**, not a grandfathered reference success.

## Contract objects

The executable definitions live in `historian/persistence/`:

- `PersistenceInvariant`: stable ID, guarantee, permitted boundaries, required properties,
  additional defense in depth, failure semantics, and mandatory probes.
- `PersistenceProfile`: exact name/version, backend family, deployment and credential
  model, trusted and excluded/untrusted boundaries, coverage claims, and threat model.
- `ThreatModel`: actors, access assumptions and excluded threats. Excluded threats are
  assumptions to inspect, not convenient excuses for failed bypass probes.
- `BoundaryTest`: scenario, invariant ID, expected observation and access class.
- `ConformanceEvidence`: exact profile/version, invariant, probe, expected/observed result,
  boundary, access class, run ID, status and a safe diagnostic.
- `ConformanceResult`: exact profile/version/backend, contract version, run ID, evidence
  and aggregate status. Evidence from an earlier profile version cannot certify a new one.

A profile change that affects access, authentication, enforcement or deployment assumptions
requires a new profile version and fresh evidence. CI artifacts are additionally associated
with their Git commit and workflow run. Results are not portable to an untested deployment.

### Boundaries and properties

Placement is separate from strength. Permitted locations are `database`, `trusted_service`,
and an explicitly `approved_alternative`. Properties include atomicity, authenticated
identity, tamper resistance, capability isolation, referential integrity, durable uniqueness,
immutability and source integrity. Defense-in-depth checks never replace those properties.

A tuple of permitted boundaries expresses alternatives, not permission to omit enforcement.
An approved alternative requires a documented, reviewed threat model and real boundary probes;
merely reporting the enum value is not approval. A service implementation must demonstrate
that callers cannot acquire its unrestricted credential, open its database files, use another
connection endpoint, or assume a more privileged identity. A service returning “forbidden”
while the same caller can write directly fails the contract.

## Mandatory invariant catalog

The machine-readable authority is `historian/persistence/catalog.py`. All **20 invariants**
and their **43 probes** are mandatory; narrowing a profile's coverage claim does not skip them.
The following matrix names candidate PostgreSQL mechanisms, not guaranteed results.

| ID | Guarantee | Permitted enforcement | PostgreSQL candidate / observed gap |
|---|---|---|---|
| PV01 | Frozen question text remains bound through seed provenance | DB | Composite FK |
| PV02 | Claims used by a resolution answer its question | DB | Claim FK and insertion guard |
| PV03 | A resolution's routing answers its question | DB | Composite FK |
| PV04 | Durable identities cannot be reused | DB | Primary keys |
| PV05 | Published resolution dependency sets are complete and immutable | DB | Transaction exists; **post-commit appends allowed** |
| PV06 | Evidence revisions append rather than overwrite | DB/service/approved alternative | Writer grants |
| PV07 | Verifier attribution derives from authenticated identity | DB/service | Session identity binding |
| PV08 | Specialized capabilities cannot be assumed or bypassed | DB/service | SCRAM, role membership and grants |
| PV09 | Adjudication dependencies refer to existing artifacts | DB | Foreign keys |
| PV10 | Application callers cannot delete/truncate evidence | DB | Revoked mutation grants |
| PV11 | Open-ended locator identity is persisted losslessly | DB | **Unsupported source systems and instance identity** |
| PV12 | Structured coordinate systems and canonical parts survive persistence | DB | **LINE-only representation** |
| PV13 | Publication commits atomically; failures roll back; partial writes invisible | DB | Explicit transaction / separate observer connection |
| PV14 | Blind adjudicators cannot read contaminating internal material | DB/service | Blind views and read grants |
| PV15 | Adjudication consumes validated frozen packets | DB | Restricted finalizer and finalization guard |
| PV16 | Source verification checks actual source/version/anchor | Trusted service | EvidenceVerifier + SourceRegistry + source reader |
| PV17 | Assertion origin matches writer capability | DB | Row-level insert policies |
| PV18 | Gold descends from an eligible adjudication | DB | Gold eligibility guard |
| PV19 | Verified evidence preserves its candidate's locator and anchor | DB | Composite FK |
| PV20 | Human attribution derives from the authenticated principal | DB/service | Principal registry and session identity binding |

SQL function names, triggers, role names and generated columns are implementation choices.
They are not universal requirements for a future engine. The existing PostgreSQL security
suite additionally exercises finalization completeness/order, synthetic-human gold exclusion,
blindness, proposal/assertion separation and mutation permissions. It remains a required CI
gate alongside the shared probes; it has not been replaced by the smaller profile report.

## Threat model: postgresql-role-isolated-v1 / version 1

CI uses **PostgreSQL 18** (`postgres:18-alpine`), TCP, independent synthetic passwords and
SCRAM host authentication. Probe evidence records `server_version_num`; the CI artifact
identifies the exact run. The profile allows PostgreSQL 18 patch releases but each deployment
still requires its own run. CI provisions the frozen `v0.0.0-original` schema and role grants,
then applies migration 001. No production schema or grants are changed by this PR.

| Actor | Access and trust |
|---|---|
| Authorized Historian service | Trusted code for source verification; only its capability credential |
| Specialized writer | Its own credential; arbitrary SQL, including malicious raw queries, is in scope |
| Ordinary application caller | No owner or other writer credential; identity strings are untrusted |
| Caller bypassing application methods | May issue raw SQL using its permitted credential |
| Actor with direct DB connectivity | Connectivity is allowed; authentication, grants and role isolation must reject unauthorized actions |
| Privileged operator/owner | Provisioning/migration authority; host and owner compromise excluded explicitly |

Roles and capabilities are declared in `sql/02-roles.sql`:

| Identity | Allowed purpose |
|---|---|
| historian_extractor | Candidates, claims, relations, source-role and routing proposals |
| historian_evidence_verifier | Read candidates; create evidence |
| historian_case_designer | Build and finalize seeds |
| historian_typed_ingestor | Typed-source assertions |
| historian_human_reviewer | Reviewed-proposal assertions and assertion reviews |
| historian_runtime | Resolutions and dependency edges; no proposal authorship |
| historian_packet_builder | Build and finalize packets |
| Individual adjudicator login | Member of historian_adjudicator; blind views and verdict insertion |
| historian_gold_compiler | Derive gold from eligible adjudications |
| historian_owner | Trusted provisioning only; never an ordinary workflow credential |

Non-owner roles receive no UPDATE, DELETE or TRUNCATE grants. Tests use actual independent
connections, not an owner session merely claiming to be a role. A raw verifier credential
can supply invented source bytes: the verifier process is explicitly trusted for source
checking. SQL enforces which capability may create evidence; it cannot prove external bytes.
Compromise of that verifier is excluded, but an extractor writing evidence directly is not.

The CI environment does not prove a production secret distribution system is isolated.
Production adoption must verify credential/file/network access for its declared actors.
A deployment sharing the owner credential with ordinary callers is a different profile and
cannot borrow this profile's evidence.

## EvidenceLocator representation

`locator.py` supplies a JSON-compatible contract representation and validated round-trip,
not a persistence backend. The representation preserves:

- source_system, source_instance_id, record_id, version_hash;
- coordinate_system and coordinate_parts as `{name, value}` pairs sorted by name;
- content_hash, material_state and redaction_ref.

Coordinate values remain strings (including empty strings and Unicode); duplicate names are
rejected. Distinct accounts, versions and coordinates must remain distinct. Consumers must
not coerce arbitrary systems to OTHER or arbitrary coordinates to LINE. Hashes, redaction
state and references retain the existing Source Adapter validation. Immutable versions use
new durable identities; older evidence continues to reference the version originally read.

Current PostgreSQL `evidence_ref` has a closed source-system enum, no source-instance field,
and a LINE-only coordinate enum. Real attempted writes with TWITTER_EXPORT / JSON_POINTER
are rejected. The four locator/coordinate probes therefore report failure; the Python wire
round-trip is not claimed as proof of database persistence. No schema workaround is added.

## Execution and failure semantics

`ConformanceHarness` runs every catalog scenario through a `BackendProbe`. Adapters provide
actual observations, not their own PASS status or expected values. The harness binds each
observation to the current exact profile/run, checks the permitted and trusted boundary,
and compares it with the shared expected result. It never obtains success from configuration
inspection alone. Probe implementations and evidence collection are trusted test code and
must be reviewed; an adapter that simply echoes expectations is not conformance proof.

Access classes are normal authorized, unauthorized supported interface, direct/bypass, and
transaction/integrity. PostgreSQL's supported boundary is SQL: negative and bypass probes
use its real credentials and raw SQL. The service-required source probes invoke the real
EvidenceVerifier with synthetic source bytes and a recording sink. The existing source and
PostgreSQL integration suites continue to test their respective paths.

- `CONFORMS`: every mandatory probe ran and met the contract at a permitted trusted boundary.
- `DOES_NOT_CONFORM`: at least one executed probe demonstrated a violation, even if other
  evidence is missing.
- `NOT_TESTED`: no demonstrated violation, but at least one probe could not execute.

Errors retain their exception type only, never raw connection strings or credentials.
Unexpected database exceptions are not counted as successful authorization denial. Negative
SQL probes check the intended SQLSTATE. Rejections must leave previous committed history
intact; transaction probes check rollback and visibility through another authenticated connection.
Power-loss recovery, host compromise and arbitrary service compromise are not certified by
these tests. CONFORMS does not mean source assertions are true, source archives complete, or
adjudication business policy correct.

PV05 is stronger than transaction rollback alone: a committed resolution must not acquire
new dependencies later. Current runtime grants allow that raw insertion, changing its support
without a new resolution identity. This PR records the failure and does not introduce a
finalizer, revoke grants or redefine “published” to avoid it.

## Running and retaining evidence

Use a disposable PostgreSQL database provisioned by the existing CI setup scripts and the
same environment variables documented in `.github/workflows/validation.yml`. Do not run these
write probes against production. Probe IDs are unique; test database disposal is the cleanup.

```sh
python -m pytest -q -m 'not pg and not canary'
python -m pytest -q tests/test_persistence_contract.py
python -m pytest -q -m pg --run-pg
python -m pytest -q tests/test_source_adapter_contract.py tests/test_twitter_export_adapter.py
```

The PostgreSQL test writes `HISTORIAN_CONFORMANCE_REPORT` (default:
`/tmp/historian-persistence-conformance.json`). GitHub CI uploads it even when the gate fails
and displays the exact profile result in its step summary. Missing proof must never become
an implicit green conformance claim.

The regression assertion currently expects the five failing probes in PV05/PV11/PV12.
That lets CI confirm the harness reports the known gaps faithfully. **A passing pytest or
workflow badge is not CONFORMS.** The machine-readable report remains DOES_NOT_CONFORM.
Unexpected failures or unavailable probes fail the regression gate. When gaps are repaired
in separately reviewed work, update that baseline; do not weaken the catalog.

## Future libSQL profile

PR #7 must declare one named/versioned deployment profile, implement the same scenarios and
provide actual persistence and adversarial evidence. Service delegation requires proving
ordinary callers cannot access an unrestricted database credential or file, including through
alternate/raw access paths. A shared unrestricted credential does not provide an equivalent
capability boundary. Neither engine is exempt from any catalog invariant.

This PR adds no libSQL dependency, schema or implementation, replaces no PostgreSQL behavior,
and fixes none of the three open adjudication/Twitter findings. Taxonomy routing and incomplete
Twitter media verification remain production blockers; repeated archive loading remains a
scale blocker. Those are separate from persistence conformance.
