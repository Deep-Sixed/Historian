# From alpha to 1.0

The architecture is settled for the declared Linux profile. The three original
correctness/scale findings are fixed and regression tested. Further persistence
architecture expansion is not a prerequisite for the next release.

The first alpha supplies a tested library, low-level service CLI, installation guidance,
backup/restore, strict schema checks and retained conformance evidence. It is not a
claim that a production host has been provisioned or that historical data has migrated.

Before 1.0, establish evidence from actual use:

- Run a representative private source corpus through intake and adjudication. Confirm
  partial/malformed media failures are actionable and compare expected conclusions.
  Hosted CI cannot exercise the private real-corpus canary.
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
- Decide whether existing PostgreSQL deployments need a dedicated migration tool. Do not
  promise lossless migration of information the old schema never captured.

Use alpha releases for fixes and workflow feedback, beta when the supported workflows
and upgrade contract are stable, and a release candidate after the above evidence is
available. No arbitrary feature quota or date determines 1.0 readiness. Repository
visibility, public licensing/security review, PyPI publication and production rollout
are separate decisions; the initial GitHub pre-release stays private.
