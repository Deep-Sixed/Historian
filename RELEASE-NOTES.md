# Historian v0.1.0a1

First private alpha release in the pre-1.0 series.

- Reject caller frames from a mismatched taxonomy version before selecting authority.
- Require all declared Twitter media payloads; thumbnails do not stand in for videos.
- Index archive metadata once per source generation and re-read requested media.
- Default the new application CLI to the Linux peer-credential libSQL service.
- Add exact-schema checks, exclusive service locking, offline backup/restore, a systemd
  example and installed-wheel validation.

Persistence v1 is unchanged. libsql-linux-peercred-service-v1 v2 conforms to all 43
shared probes with 124 successful supplemental boundary checks. PostgreSQL v1 retains
its five known PV05/PV11/PV12 failures; green regression CI does not claim conformance.

The artifacts include wheel, source distribution, checksums, exact profile reports and
release/CI identity. Install and operate according to docs/release-operations.md.
This is a Linux deployment profile, not a generic embedded database security claim.
No production installation or database is changed by this release. Automatic PostgreSQL
migration and a complete end-to-end operator workflow are not included. See
docs/road-to-1.0.md for the evidence still required before 1.0.

Co-authored-by: Codex <codex@openai.com>
