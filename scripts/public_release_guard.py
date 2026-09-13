"""Fail closed on prohibited public-source material; never print matched contents.

Default: scan tracked and non-ignored untracked working-tree files. --tree scans every
file in an extracted distribution. This is a regression guard, not a history scrub or
a substitute for reviewing the provenance of new fixtures.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKERS = frozenset(json.loads((Path(__file__).with_name("private-marker-digests.json")).read_text()))
CASE_FILES = frozenset({
    "cases/README.md", "cases/build_queue.py", "cases/audit_queue.py",
    "cases/case-queue.json",
    "cases/synthetic/2030-01-01-synthetic-observatory.md",
    "cases/synthetic/2030-02-01-synthetic-observatory.md",
    "cases/synthetic/2030-01-01-synthetic-recycling.md",
    "cases/synthetic/2030-02-01-synthetic-recycling.md",
})
RULES = {
    "home-directory": re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+"),
    "conversation-identifier": re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I),
    "export-record": re.compile(r'''["'](?:conversation_id|chat_messages|mapping)["']\s*:'''),
    "private-key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    "credential": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})\b"),
    "credential-assignment": re.compile(r'''(?im)\b(?:password|api_key|access_token|client_secret)\s*[:=]\s*["'][^"'\r\n]{8,}["']'''),
    "credential-url": re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@", re.I),
    "private-network": re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"),
}
PROHIBITED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".zip", ".gz", ".tar", ".mbox", ".eml", ".pem", ".key"}


def findings(path, data):
    """Return rule identifiers only, never matched values."""
    found = set()
    p = Path(path)
    if p.parts[0] == "cases" and path not in CASE_FILES:
        found.add("unapproved-case-artifact")
    if p.suffix.lower() in PROHIBITED_SUFFIXES or p.name == ".env" or p.name.startswith(".env."):
        found.add("prohibited-file-class")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return found | {"unreviewed-binary"}
    if "\x00" in text:
        found.add("unreviewed-binary")
    for name, rule in RULES.items():
        if rule.search(text) or rule.search(path):
            found.add(name)
    # Hash both whole hyphenated IDs/slugs and individual words. The denylist does not
    # republish the removed identifiers or private names in plaintext.
    for token in re.findall(r"[\w.-]+|\w+", text.lower() + " " + path.lower()):
        for part in (token, *re.findall(r"\w+", token)):
            if hashlib.sha256(part.encode()).hexdigest() in MARKERS:
                found.add("known-private-marker")
    return found


def scan(root, paths):
    result = []
    for name in sorted(set(paths)):
        path = root / name
        if path.is_symlink():
            result.append({"path": name, "rules": ["symlink"]})
        elif path.is_file():
            rules = findings(name, path.read_bytes())
            if rules:
                result.append({"path": name, "rules": sorted(rules)})
        elif path.exists():
            result.append({"path": name, "rules": ["unscannable-entry"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, help="scan an extracted distribution instead of Git files")
    args = parser.parse_args()
    root = args.tree.resolve() if args.tree else ROOT
    if args.tree:
        if not root.is_dir():
            parser.error("tree must be an existing directory")
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_dir() or p.is_symlink()]
    else:
        paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
        ).decode().split("\0")
        paths = [p for p in paths if p]
    result = scan(root, paths)
    print(json.dumps({"scope": "extracted-tree" if args.tree else "working-tree",
                      "status": "FAIL" if result else "PASS", "findings": result}, indent=2))
    return int(bool(result))


if __name__ == "__main__":
    raise SystemExit(main())
