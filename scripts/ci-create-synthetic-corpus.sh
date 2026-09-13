#!/usr/bin/env bash
set -euo pipefail

: "${HISTORIAN_CORPUS:=${RUNNER_TEMP:-/tmp}/historian-synthetic-corpus}"

mkdir -p "$HISTORIAN_CORPUS"

cat > "$HISTORIAN_CORPUS/2030-01-01-synthetic-source.md" <<'EOF'
title: "Synthetic Historian Evidence"
alpha source line
beta source line
gamma source line
delta source line
EOF

cat > "$HISTORIAN_CORPUS/2030-01-02-synthetic-unrelated.md" <<'EOF'
title: "Synthetic Wrong Document"
unrelated source line
another unrelated source line
final unrelated source line
EOF

printf '%s\n' "$HISTORIAN_CORPUS"
