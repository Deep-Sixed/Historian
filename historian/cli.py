"""Application entry point for the Linux peer-credential persistence service."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="historian")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profile", help="Show the default deployment profile identity")
    serve = commands.add_parser("serve", help="Run the default SQLite service as UID 10000")
    serve.add_argument("--database", default="/var/lib/historian/private/historian.db")
    serve.add_argument("--socket", default="/run/historian/historian.sock")
    serve.add_argument("--corpus", required=True)
    request = commands.add_parser("request", help="Invoke an operation as the current OS UID")
    request.add_argument("operation")
    request.add_argument("--socket", default="/run/historian/historian.sock")
    request.add_argument("--data-file", type=Path, required=True)
    for operation in ("check", "backup", "restore", "upgrade"):
        admin = commands.add_parser(operation, help="Offline service-owner storage operation")
        admin.add_argument("--database", type=Path, required=True)
        if operation in {"backup", "restore"}:
            admin.add_argument("--destination", type=Path, required=True)
    migrate = commands.add_parser(
        "migrate", help="Verified copy of a stopped v3 (libSQL) database to a new v4 file; "
        "dry run unless --apply")
    migrate.add_argument("--source", type=Path, required=True)
    migrate.add_argument("--destination", type=Path, required=True)
    migrate.add_argument("--apply", action="store_true",
                         help="Link the verified copy into --destination (never overwrites)")
    args = parser.parse_args(argv)
    if args.command == "profile":
        from historian.sqlite_store.profile import (
            SQLITE, running_runtime, runtime_is_certified)
        runtime = running_runtime()
        print(json.dumps({"backend": SQLITE.backend_family, "profile": SQLITE.name,
                          "version": SQLITE.version, "digest": SQLITE.digest,
                          "runtime": runtime,
                          "runtime_is_certified": runtime_is_certified(runtime)}))
        return 0
    if sys.platform != "linux":
        parser.error("the default profile requires Linux SO_PEERCRED; no fallback backend")
    if args.command in {"check", "backup", "restore", "upgrade", "migrate"}:
        import os
        if os.getuid() != 10000:
            parser.error("storage operations require service UID 10000")
        if args.command == "migrate":
            from historian.sqlite_store.migrate import migrate as run_migration
            print(json.dumps(run_migration(args.source, args.destination, apply=args.apply),
                             sort_keys=True))
            return 0
        from historian.sqlite_store.operations import check, snapshot, storage_lock
        if args.command == "upgrade":
            from historian.sqlite_store.repository import upgrade_schema
            with storage_lock(args.database):
                upgrade_schema(args.database)
        elif args.command == "check":
            with storage_lock(args.database):
                check(args.database)
        else:
            snapshot(args.database, args.destination)
        print(json.dumps({"ok": True, "operation": args.command}))
        return 0
    if args.command == "serve":
        from historian.sqlite_store.service import serve as run_service
        run_service(args.database, args.socket, args.corpus)
        return 0
    from historian.sqlite_store.client import request as call
    data = json.loads(args.data_file.read_text())
    if not isinstance(data, dict):
        parser.error("request data must be a JSON object")
    result = call(args.socket, args.operation, data)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1
