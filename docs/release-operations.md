# Pre-1.0 installation and operations

Supported persistence deployment: Linux, Python 3.14.5, libSQL 0.1.11, local disk,
fixed service UID 10000 and capability UIDs 10001–10009. See the complete
[profile and threat model](libsql-profile-v3.md). Python 3.13 is a tested fallback;
non-Linux installations can use the pure adjudication library but cannot run the service.

## Install

Download the wheel and SHA256SUMS from the GitHub release and verify the
checksum. Install into a dedicated Python 3.14.5 virtual environment at
`/opt/historian/venv`, using `python -m pip install /path/to/historian-*.whl`.
Run `historian profile`. The wheel includes the storage schema; no source checkout
or current-directory dependency is required. PyPI publication and production rollout require separate release decisions.

Before provisioning, inspect `getent passwd` and `getent group` for UID/GID conflicts.
Reserve UID/GID 10000 for the service and 10001–10009 for the profile's capabilities:
extractor, verifier, designer, typed ingestor, reviewer, runtime, packet builder,
adjudicator, gold compiler. Do not reuse an existing unrelated account. Each account
must be isolated from every other capability, with no sudo, setuid, ptrace, container
control, unrestricted credentials, or shared database mounts. Merely changing a JSON
role field never grants authority. The service account is trusted, not an ordinary caller.

Provision a service-owned 0700 `/var/lib/historian` directory and a service-owned
0700 `corpus` subdirectory containing the approved source files. Install the supplied
`deployment/systemd/historian.service` as an operator, then enable/start it. It creates
private storage and the service-owned 0755 runtime socket directory. This unit is a
starting configuration, not a certification of your host's entire security boundary.
Run service requests from the actual capability accounts. `historian request` reads a
JSON object from `--data-file` and returns nonzero on a service rejection. Protect files
containing source text according to their sensitivity. The API is a low-level persistence
interface; this release does not supply a complete interactive ingestion/adjudication UI.

## Backup and restore

Stop callers and `systemctl stop historian`. As UID 10000, create a private backup
directory and run (substitute your protected paths):

```sh
historian check --database /var/lib/historian/private/historian.db
historian backup --database /var/lib/historian/private/historian.db --destination /protected/backups/historian-001.db
historian restore --database /protected/backups/historian-001.db --destination /protected/restore/historian.db
historian check --database /protected/restore/historian.db
```

Both source and destination directories must be owner-private. Backup and restore use
libSQL `VACUUM INTO` for a coherent snapshot, check exact schema, integrity and foreign
keys, fsync the output, and refuse an existing destination. They take the same exclusive
lock as the service. They are operator commands, never socket capabilities. Retain the
original source archives separately: database backups cannot replace evidence sources.
Protect backup storage with the same access restrictions as the live database.

Test restoration into a fresh private directory before trusting a backup. Point the
stopped service's `--database` argument at the verified restored path (and update the
unit's permitted writable paths if necessary). Keep the old file untouched for rollback.
Never copy only a live main database file and discard its WAL/SHM sidecars.

## Upgrade and rollback

Keep the previous wheel, validated backup and release evidence. Stop the service,
back up, install the new wheel in a separate environment, and run `historian check`.
Startup rejects any schema differing from this release's schema, including missing
immutability triggers. The reviewed PR #8 schema requires the explicit additive upgrade before startup; older
experimental schemas are not silently converted. See [migration](migration.md).

Switch the unit to the new environment and start it. Verify an authorized request,
an unauthorized rejection, and existing records from the appropriate capability UID.
Rollback means stopping it, restoring the prior backup to a new path and returning to
the prior wheel. Test this process on representative data before a production rollout.

## Release gate

Each release must pass core, Source Adapter, application and libSQL suites and an
installed-wheel smoke test. Preserve the profile report, supplemental boundary evidence,
commit SHA, wheel/sdist, and checksums. libSQL v3 must pass all 43 probes and 124 boundary
checks plus the domain capability matrix. No retired database runs in CI.
Hosted CI uses synthetic evidence and does not establish real-corpus readiness.
Pre-releases remain explicitly pre-release. See public-release-safety.md for the
separate historical source and release-artifact scrub.
