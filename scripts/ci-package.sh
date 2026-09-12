#!/usr/bin/env bash
set -euo pipefail
python -m build
package_env=$(mktemp -d)
trap 'rm -rf "$package_env"' EXIT
python -m venv "$package_env/venv"
release_version=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
"$package_env/venv/bin/python" -m pip install "dist/historian-$release_version-py3-none-any.whl"
cd "$package_env"
"$package_env/venv/bin/historian" profile
"$package_env/venv/bin/python" - <<'PY'
import tempfile
from importlib.metadata import version
import historian
assert version("historian") == historian.__version__
from pathlib import Path
from historian.libsql_store.repository import initialize, connect
from historian.libsql_store.operations import snapshot, check
with tempfile.TemporaryDirectory() as root:
    source, backup = Path(root)/'source.db', Path(root)/'backup.db'
    initialize(source)
    c = connect(source)
    c.execute("INSERT INTO question VALUES ('q','packaged question')")
    c.close()
    snapshot(source, backup)
    check(backup)
    c = connect(backup)
    assert c.execute('SELECT text FROM question').fetchone() == ('packaged question',)
    c.close()
PY
