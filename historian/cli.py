"""Application entry point for the Linux peer-credential persistence service."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="historian")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profile", help="Show the default deployment profile identity")
    serve = commands.add_parser("serve", help="Run the default libSQL service as UID 10000")
    serve.add_argument("--database", default="/var/lib/historian/private/historian.db")
    serve.add_argument("--socket", default="/run/historian/historian.sock")
    serve.add_argument("--corpus", required=True)
    request = commands.add_parser("request", help="Invoke an operation as the current OS UID")
    request.add_argument("operation")
    request.add_argument("--socket", default="/run/historian/historian.sock")
    request.add_argument("--data-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "profile":
        from historian.libsql_store.profile import LIBSQL
        print(json.dumps({"backend": LIBSQL.backend_family, "profile": LIBSQL.name,
                          "version": LIBSQL.version, "digest": LIBSQL.digest}))
        return 0
    if sys.platform != "linux":
        parser.error("the default profile requires Linux SO_PEERCRED; no fallback backend")
    if args.command == "serve":
        from historian.libsql_store.service import serve as run_service
        run_service(args.database, args.socket, args.corpus)
        return 0
    from historian.libsql_store.client import request as call
    data = json.loads(args.data_file.read_text())
    if not isinstance(data, dict):
        parser.error("request data must be a JSON object")
    result = call(args.socket, args.operation, data)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1
