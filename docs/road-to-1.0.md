# From alpha to 1.0

The architecture is settled for the declared Linux profile. The three original
correctness/scale findings are fixed and regression tested. Further persistence
architecture expansion is not a prerequisite for the next release.

The first alpha supplies a tested library, low-level service CLI, installation guidance,
backup/restore, strict schema checks and retained conformance evidence. It is not a
claim that a production host has been provisioned or that historical data has migrated.

Public-tree sanitization and the writable-history/tag/release scrub are complete.
First resolve the [remaining GitHub-retained history](history-sanitization.md)
before creating a release or tag. Then establish
evidence from actual use before 1.0:

- Run a representative private source corpus through intake and adjudication. Confirm
  partial/malformed media failures are actionable and compare expected conclusions.
  Keep raw inputs and results outside Git; publish only reviewed aggregate evidence.
  Hosted CI uses synthetic cases and does not satisfy this gate.
- Measure ingestion time, memory and query latency at the intended archive size. The
  quadratic metadata reload is fixed by a deterministic load-count regression; that
  does not establish a production capacity number.
- Rehearse installation, restart, verified backup, restore and rollback on the actual
  deployment host, including its UID isolation and caller inability to bypass the service.
- Establish the supported upgrade compatibility window, dependency/update policy, and
  recovery objectives. Unknown schemas currently fail closed; future schema changes
  require separately tested migration paths.
- Validate the operator workflow. The CLI exposes persistence operations, not a complete
  end-to-end import/adjudication product command. Add a higher-level workflow only after
  alpha use identifies the specific missing steps.
- Reconcile any external legacy data export through a separately validated import or
  verified re-ingestion. The supported runtime remains SQLite-only.

Use alpha releases for fixes and workflow feedback, beta when the supported workflows
and upgrade contract are stable, and a release candidate after the above evidence is
available. No arbitrary feature quota or date determines 1.0 readiness. Repository
visibility, public licensing/security review, PyPI publication and production rollout
are separate decisions. The repository is public; source fixtures must be synthetic.
