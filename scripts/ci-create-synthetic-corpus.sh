#!/usr/bin/env bash
set -euo pipefail

: "${HISTORIAN_CORPUS:=${RUNNER_TEMP:-/tmp}/historian-synthetic-corpus}"

mkdir -p "$HISTORIAN_CORPUS"

cat > "$HISTORIAN_CORPUS/2026-07-08-decommissioning-hindsight-memory.md" <<'EOF'
title: "Synthetic Historian Evidence"
alpha source line
beta source line
gamma source line
delta source line
EOF

cat > "$HISTORIAN_CORPUS/2026-07-14-hindsight-v0-8-4-review.md" <<'EOF'
title: "Synthetic Wrong Document"
unrelated source line
another unrelated source line
final unrelated source line
EOF

printf '%s\n' "$HISTORIAN_CORPUS"
