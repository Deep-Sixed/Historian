#!/usr/bin/env bash
# libSQL profile v3 -> SQLite profile v4 migration compatibility, both directions.
#
# 1. The last v3 commit, with its own code and libsql 0.1.11, writes a populated database.
# 2. The v4 wheel (no libsql installed) migrates it: dry run, then --apply; verifies it.
# 3. v4 appends, then migrates the result back to a new file (rollback carry-back).
# 4. v3 code with libsql 0.1.11 checks, reads and appends to both v4-written files.
# This is the only place libsql is installed. Synthetic data only.
set -euo pipefail
V3_COMMIT="${HISTORIAN_V3_COMMIT:-36fe35a1af2b73df1907b4c293d09c0f72af96c5}"
PYTHON="${PYTHON:-python3}"
repo=$(pwd)
work=$(mktemp -d)
cleanup() { git -C "$repo" worktree remove --force "$work/v3" 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT

git -C "$repo" cat-file -e "$V3_COMMIT^{commit}" 2>/dev/null \
  || git -C "$repo" fetch --quiet --depth=1 origin "$V3_COMMIT"
git -C "$repo" worktree add --quiet --detach "$work/v3" "$V3_COMMIT"

"$PYTHON" -m venv "$work/v3env"
"$work/v3env/bin/python" -m pip install --quiet "libsql==0.1.11"
"$PYTHON" -m venv "$work/v4env"
"$work/v4env/bin/python" -m pip install --quiet "$repo"

mkdir -m 700 "$work/old" "$work/new" "$work/back"
fixture="$repo/tests/migration_fixture.py"
# -P: never import from the current directory or the script's directory.
v3() { (cd "$work" && PYTHONPATH="$work/v3" "$work/v3env/bin/python" -P "$@"); }
v4() { (cd "$work" && "$work/v4env/bin/python" -P "$@"); }

v3 - <<'PY'
import libsql, historian.libsql_store.repository as r
assert "libsql" in r.connect.__code__.co_names, "v3 code must use the libSQL driver"
print("v3 writer: libsql", getattr(libsql, "__version__", "0.1.11"))
PY
v4 - <<'PY'
import importlib.util, historian.libsql_store.repository as r
assert importlib.util.find_spec("libsql") is None
assert "sqlite3" in r.connect.__code__.co_names
PY

v3 "$fixture" create "$work/old/historian.db" "$work/corpus" > "$work/v3-summary.json"
sha256sum "$work/old/historian.db" > "$work/source.sha256"

WORK="$work" v4 - <<'PY'
import json, os
from pathlib import Path
from historian.libsql_store.migrate import migrate
from historian.libsql_store.operations import check
from historian.libsql_store.profile import PREVIOUS_PROFILE, SQLITE
work = Path(os.environ["WORK"])
old, new, back = work/"old/historian.db", work/"new/historian.db", work/"back/historian.db"
dry = migrate(old, new)
assert dry["dry_run"] and not new.exists()
applied = migrate(old, new, apply=True)
assert applied["tables"] == dry["tables"] and applied["total_rows"] > 0
assert applied["source"]["profile"] == PREVIOUS_PROFILE
assert applied["destination"]["profile"]["digest"] == SQLITE.digest
check(new)
v3_counts = json.loads((work/"v3-summary.json").read_text())
assert {k: v["rows"] for k, v in applied["tables"].items()} == v3_counts
try:
    migrate(old, new, apply=True)
except ValueError:
    pass
else:
    raise AssertionError("existing destination was overwritten")
print(json.dumps({"migrated_rows": applied["total_rows"], "tables": len(applied["tables"])}))
PY
sha256sum --check --quiet "$work/source.sha256"   # source bytes untouched

# Post-cutover writes under v4, then carry them back to a new file for v3.
v4 "$fixture" append "$work/new/historian.db" "$work/corpus" > /dev/null
WORK="$work" v4 - <<'PY'
import os
from pathlib import Path
from historian.libsql_store.migrate import migrate
work = Path(os.environ["WORK"])
migrate(work/"new/historian.db", work/"back/historian.db", apply=True)
PY

for target in new back; do
  WORK="$work" TARGET="$target" v3 - <<'PY'
import os
from historian.libsql_store.operations import check
check(os.path.join(os.environ["WORK"], os.environ["TARGET"], "historian.db"))
PY
  v3 "$fixture" summary "$work/$target/historian.db" > "$work/$target-summary.json"
done
cmp "$work/new-summary.json" "$work/back-summary.json"
# libSQL 0.1.11 can keep writing to the carried-back file.
v3 "$fixture" append "$work/back/historian.db" "$work/corpus" > /dev/null
WORK="$work" v3 - <<'PY'
import os
from historian.libsql_store.operations import check
check(os.path.join(os.environ["WORK"], "back", "historian.db"))
PY
echo "libSQL v3 -> SQLite v4 migration and v3 carry-back: OK"
