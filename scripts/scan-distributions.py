"""Scan contents of freshly built wheel/sdist artifacts before publication."""

import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
artifacts = sorted((root / "dist").glob("*.whl")) + sorted((root / "dist").glob("*.tar.gz"))
if not artifacts or not any(p.suffix == ".whl" for p in artifacts) or not any(p.name.endswith(".tar.gz") for p in artifacts):
    raise SystemExit("wheel and source distribution required")
for artifact in artifacts:
    with tempfile.TemporaryDirectory() as target:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                archive.extractall(target)
            tree = Path(target)
        else:
            with tarfile.open(artifact) as archive:
                archive.extractall(target, filter="data")
            children = list(Path(target).iterdir())
            if len(children) != 1 or not children[0].is_dir():
                raise SystemExit("unexpected source distribution layout")
            tree = children[0]
        print(artifact.name, flush=True)
        subprocess.run([sys.executable, str(root / "scripts/public_release_guard.py"),
                        "--tree", str(tree)], check=True)
