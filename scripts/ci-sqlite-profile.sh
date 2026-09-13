#!/usr/bin/env bash
# Disposable proof deployment; no host database mounts or production credentials.
set -euo pipefail
image="historian-sqlite-proof:${GITHUB_SHA:-local}"
container="historian-sqlite-proof-${GITHUB_RUN_ID:-$$}"
report_dir="${HISTORIAN_SQLITE_ARTIFACT_DIR:-/tmp/historian-sqlite-artifacts}"
mkdir -p "$report_dir"
rm -f "$report_dir/historian-sqlite-conformance.json" "$report_dir/historian-sqlite-boundaries.json"
docker build -f deployment/sqlite/Dockerfile -t "$image" .
cleanup() {
  docker cp "$container:/tmp/historian-sqlite-conformance.json" "$report_dir/" 2>/dev/null || true
  docker cp "$container:/tmp/historian-sqlite-boundaries.json" "$report_dir/" 2>/dev/null || true
  docker cp "$container:/tmp/historian-sqlite-application.json" "$report_dir/" 2>/dev/null || true
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker run --name "$container" --user 0 --entrypoint python \
  -e HISTORIAN_RUN_SQLITE=1 "$image" -m pytest -q -s tests/test_sqlite_profile.py tests/test_sqlite_storage.py tests/test_sqlite_application.py
