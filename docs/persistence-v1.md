# Persistence v1

Persistence conformance is evaluated against a backend together with its declared
deployment and security profile. An engine does not conform in isolation.

The unchanged authority is historian/persistence/catalog.py and contract.py. Each
PersistenceInvariant declares its guarantee, permitted boundaries, required properties,
defense in depth, failure semantics and conformance tests. BoundaryTest observations must
identify actual access, actor and capability. Missing proof produces NOT_TESTED; a failure
produces DOES_NOT_CONFORM. Only complete successful proof may yield CONFORMS.

Every result binds the exact profile name, version, canonical definition digest, contract
version and run ID. Normal, unauthorized-interface, direct/bypass and transaction tests
exercise real enforcement. A service returning forbidden cannot prove a database constraint.
Required properties count only when successfully demonstrated by the relevant probe.

The only current implementation is [libSQL profile version 3](libsql-profile-v3.md).
The earlier reference backend is retired; its evidence is retained with historical releases.
The 20 invariants and 43 probes were not relaxed during backend retirement.

| ID | Guarantee | Permitted boundaries | Required properties |
|---|---|---|---|
| PV01 | A frozen question cannot be restated by downstream provenance. | database | referential_integrity |
| PV02 | Claims and resolution claim dependencies belong to the same question. | database | referential_integrity |
| PV03 | Routing and its resolution belong to the same question. | database | referential_integrity |
| PV04 | Durable artifact identities cannot be reused or overwritten. | database | durable_uniqueness |
| PV05 | Published resolutions include an immutable complete dependency set. | database | atomicity, immutability |
| PV06 | Committed evidence is append-only; revisions use new identities. | database, trusted_service, approved_alternative | immutability, tamper_resistance |
| PV07 | Verifier identity is authenticated and cannot be supplied by a caller. | database, trusted_service | authenticated_identity |
| PV08 | Specialized writers cannot assume or invoke another capability. | database, trusted_service | capability_isolation, authenticated_identity |
| PV09 | Every persisted adjudication dependency refers to an existing artifact. | database | referential_integrity |
| PV10 | Application identities cannot delete or truncate committed evidence. | database | tamper_resistance, immutability |
| PV11 | EvidenceLocator round-trips open-ended source and version identity. | database | referential_integrity, durable_uniqueness |
| PV12 | Coordinates preserve canonical named parts without LINE coercion. | database | referential_integrity |
| PV13 | Failed multi-record publication rolls back; partial writes stay invisible. | database | atomicity |
| PV14 | Blind adjudicators cannot read proposals or internal seed metadata. | database, trusted_service | capability_isolation |
| PV15 | Only validated, frozen seed/packet aggregates may reach adjudication. | database | immutability, capability_isolation |
| PV16 | Verified evidence is checked against the declared source and version. | trusted_service | source_integrity |
| PV17 | Assertion origin must match the authenticated writer capability. | database | authenticated_identity, capability_isolation |
| PV18 | Gold must descend from an eligible adjudication, never packet insufficiency. | database | referential_integrity, capability_isolation |
| PV19 | Verified evidence preserves the candidate locator and anchor it cites. | database | referential_integrity |
| PV20 | Human adjudication attribution comes from the authenticated principal. | database, trusted_service | authenticated_identity |

Run scripts/ci-libsql-profile.sh for the real Linux proof deployment. CI retains the
43-probe report, 124 original supplemental boundary checks, and the application API
capability matrix. Reports identify exact profile definitions independently of the test
badge. Root, service UID/code compromise, compromised trusted verifier, kernel compromise,
and physical disk access remain explicitly outside the profile's ordinary-caller threat
model. The host must actually prevent ordinary callers obtaining those privileges.
