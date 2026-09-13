"""Subprocess worker launched as the actual profile actor, never a simulated role."""

import json
import os
import sys

from historian.sqlite_store.client import request
from historian.sqlite_store.repository import connect

payload = json.load(sys.stdin)
result = {"uid": os.getuid()}
c = None
try:
    if payload["kind"] == "service":
        result.update(request(payload["socket"], payload["operation"], payload["data"]))
    elif payload["kind"] == "sql":
        c = connect(payload["database"])
        rows = []
        for sql, args in payload["statements"]:
            rows.append(c.execute(sql, args).fetchall())
        result.update(ok=True, rows=rows)
    elif payload["kind"] == "file":
        with open(payload["path"], payload.get("mode", "rb")) as f:
            f.read(1)
        result.update(ok=True)
    elif payload["kind"] == "assume":
        os.setuid(10000)
        result.update(ok=True, assumed_uid=os.getuid())
    elif payload["kind"] == "replace_socket":
        os.unlink(payload["path"])
        result.update(ok=True)
except Exception as exc:  # noqa: BLE001 - collect subprocess failure evidence
    result.update(ok=False, error=type(exc).__name__, detail=str(exc))
finally:
    if c is not None:
        c.close()
print(json.dumps(result))
