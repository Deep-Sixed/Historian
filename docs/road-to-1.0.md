# From alpha to 1.0

The architecture is settled for the declared Linux profile. The three original
correctness/scale findings are fixed and regression tested. Further persistence
architecture expansion is not a prerequisite for the next release.

The first alpha supplies a tested library, low-level service CLI, installation guidance,
backup/restore, strict schema checks and retained conformance evidence. It is not a
claim that a production host has been provisioned or that historical data has migrated.

## Current status (2026-11-24)

### Complete

- **SQLite persistence, [profile v4](sqlite-profile-v4.md).** It replaced libSQL 0.1.11
  with the standard-library `sqlite3` driver in Deep-Sixed/historian#19, and Historian
  now has no runtime dependencies.
  - The trust boundary is unchanged: one service process owns the database, and the
    kernel UID is checked on every operation. The schema, socket protocol, capability
    matrix and Persistence v1 catalog are also unchanged.
  - The certified runtime (Python 3.14.5, SQLite 3.46.1) and the proof image (pinned by
    digest) are part of the profile digest
    `ac319a88ff754bcaced495018df295d9b12a12a069ee94b361de376386e338f1`.
  - The background is in the [design note](sqlite-migration-design.md).
- **Container conformance proof.** CI passes on the pinned image: 43/43 Persistence v1
  probes, 124 supplemental boundary checks, the full application capability-denial
  matrix and the certified-runtime assertion. Evidence from any other runtime is
  rejected by `scripts/prepare-release.py`.
- **Migration from libSQL v3 ([migration](migration.md)).** `historian migrate` is a dry
  run by default and never writes its source. It verifies schema, integrity, foreign
  keys and per-table row counts and content digests. In CI it runs both ways: a
  database written by libSQL 0.1.11 is migrated forward, then carried back and
  appended to by v3.
- **Package rename.** `historian.libsql_store` is now `historian.sqlite_store`
  (Deep-Sixed/historian#20). Tests, scripts and evidence files follow the new name.
  There is no compatibility alias.
- **`DREAMING_TURNS` adapter** ([adapter](dreaming-turns-adapter.md),
  Deep-Sixed/historian#18). Historian reads Dreaming turns through Dreaming's
  authenticated `/v2` API; Historian exposes no inbound interface for this.
- **Dreaming contract test, run locally.** Dreaming's `tests/test_historian_contract.py`
  passed against this repository's `main`. It drives the real adapter against Dreaming's
  API with in-memory fixtures, and Dreaming's full suite passed alongside it.
- **Repository cleanup.** The earlier SQLite attempt (Deep-Sixed/historian#17) is
  closed as superseded. Every merged or superseded branch is deleted, leaving only
  `main`, and head branches are now deleted automatically on merge. CI passes on
  `main` after each merge.

### Remaining before a release

1. **History sanitization (release blocker).** First resolve the
   [remaining GitHub-retained history](history-sanitization.md). Create no release or
   tag until GitHub Support has removed the retained pull-request references and that
   removal has been verified.
2. **Standing Dreaming integration CI.**
   - The contract test lives in Dreaming and is not yet on Dreaming's main branch.
   - Once it merges, Dreaming's CI should check out this repository and set
     `HISTORIAN_SRC`, so that every change on either side runs the contract.
   - Until then, the local pass above is the only cross-repository evidence.
3. **Live Dreaming integration** on the actual deployment host:
   - the adapter runs as the verifier identity, UID 10002;
   - it uses a Dreaming read token limited to one tenant, held only in that identity's
     environment;
   - the Dreaming socket is mounted into its namespace.

   Verify these against a running Dreaming service:
   - byte-exact reads;
   - fail-closed behaviour for forgotten turns and cross-tenant records;
   - the optional `archived_as` link back to Dreaming.
4. **Real-corpus validation.** Run a representative private source corpus through intake
   and adjudication.
   - Confirm that partial or malformed media failures are actionable, and compare the
     conclusions with what was expected.
   - Keep raw inputs and results outside Git; publish only reviewed aggregate evidence.
   - Hosted CI uses synthetic cases and does not satisfy this gate.
5. **Capacity.** Measure ingestion time, memory and query latency at the intended
   archive size. A deterministic load-count regression fixes the quadratic metadata
   reload, but it does not establish a production capacity number.
6. **Production host validation.**
   - Rehearse installation, restart, verified backup, restore and rollback on the
     actual deployment host, including its UID isolation and the inability of callers to
     bypass the service.
   - Run the v4 profile on that host. CI conformance is not a host certificate.
   - Where an existing libSQL v3 database exists, rehearse the documented migration
     and rollback on a copy before the cutover.
7. **Upgrade policy.** Establish the supported upgrade compatibility window, the
   dependency and base-image update policy, and recovery objectives.
   - A base-image update needs a digest bump, a fresh proof run and a new profile
     version.
   - Unknown schemas currently fail closed; future schema changes require separately
     tested migration paths.
8. **Operator workflow.** The CLI exposes persistence operations, not a complete
   end-to-end import/adjudication product command. Add a higher-level workflow only
   after alpha use identifies the specific missing steps.
9. **Legacy data.** Reconcile any external legacy data export through a separately
   validated import or verified re-ingestion. The supported runtime is stdlib SQLite
   only (profile v4).

Profile v4 stays unchanged unless this validation finds a defect.

## Deferred: external API (proposed profile v5)

Historian has no network listener. Its interfaces are local:
- the Unix-socket service, with kernel-UID capabilities;
- the Python `Store` client;
- the CLI.

An inbound REST or MCP interface would change the trust model, not only the transport,
so it is deferred. Work on it should start only when a real consumer and its
requirements are established, and only after the remaining gates above. When it
starts, it must be a new profile version that meets these requirements:

- **A dedicated reader UID, enforced by Historian itself.**
  - The existing `runtime` capability (UID 10006) is not read-only. It can `publish`,
    write `Resolution` objects, and read internal working objects such as proposals,
    dispositions, assertions and reviews.
  - The reader capability must be added to the service's capability map and to
    `access.py`, so the service refuses writes even if the gateway is compromised.
- **Published resolutions only, by default.** No access to internal working objects.
- **An explicit evidence disclosure policy.** Supporting evidence quotes source text,
  so it is disclosed only for authorised resolutions, subject to owner-defined
  sensitivity restrictions.
- **Blind-adjudication isolation is preserved (PV14, PV15, PV18).** Readers never see
  seeds, packets, adjudications or gold.
- **Remote identities stay separate.** Remote callers are authenticated without being
  presented as a local verifier, adjudicator or any other existing capability. The
  authenticated-identity invariants (PV07, PV20) must not be diluted by many callers
  sharing one gateway UID.
- **Fresh certification.**
  - an updated capability matrix and profile digest;
  - a threat model covering the gateway;
  - real-UID conformance tests, including every denied operation for the reader.
- **One shared security boundary.** REST and MCP sit on the same restricted gateway
  and enforce identical permissions. The gateway reaches Historian only through the
  Unix socket; the database is never exposed externally.

## Release path

Use alpha releases for fixes and workflow feedback, beta when the supported workflows
and upgrade contract are stable, and a release candidate after the above evidence is
available. No arbitrary feature quota or date determines 1.0 readiness. Repository
visibility, public licensing/security review, PyPI publication and production rollout
are separate decisions. The repository is public; source fixtures must be synthetic.
