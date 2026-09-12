#!/usr/bin/env bash
# Disposable proof deployment; no host database mounts or production credentials.
set -euo pipefail
image="historian-libsql-proof:${GITHUB_SHA:-local}"
container="historian-libsql-proof-${GITHUB_RUN_ID:-$$}"
report_dir="${HISTORIAN_LIBSQL_ARTIFACT_DIR:-/tmp/historian-libsql-artifacts}"
mkdir -p "$report_dir"
rm -f "$report_dir/historian-libsql-conformance.json" "$report_dir/historian-libsql-boundaries.json"
docker build -f deployment/libsql/Dockerfile -t "$image" .
cleanup() {
  docker cp "$container:/tmp/historian-libsql-conformance.json" "$report_dir/" 2>/dev/null || true
  docker cp "$container:/tmp/historian-libsql-boundaries.json" "$report_dir/" 2>/dev/null || true
  docker cp "$container:/tmp/historian-libsql-application.json" "$report_dir/" 2>/dev/null || true
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker run --name "$container" --user 0 --entrypoint python \
  -e HISTORIAN_RUN_LIBSQL=1 "$image" -m pytest -q -s tests/test_libsql_profile.py tests/test_libsql_storage.py tests/test_libsql_application.py
