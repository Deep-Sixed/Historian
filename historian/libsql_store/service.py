"""Linux Unix-socket service: kernel peer UID selects a fixed capability.

No bearer secret, client-selected role, remote listener or raw SQL endpoint exists.
The database directory must be owned by service UID 10000 and mode 0700.
"""

import argparse
import json
import os
import socket
import socketserver
import struct
import stat
from pathlib import Path

from historian.libsql_store.repository import Repository, canonical, initialize, transaction
from historian.libsql_store.operations import storage_lock
from historian.persistence.locator import locator_from_record, locator_to_record
from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceMaterialState,
    sha256_text,
)
from historian.sources import RagV1SourceReader

SERVICE_UID = 10000
CAPABILITIES = {
    10001: "extractor",
    10002: "verifier",
    10003: "designer",
    10004: "typed",
    10005: "reviewer",
    10006: "runtime",
    10007: "builder",
    10008: "adjudicator",
    10009: "gold",
}
ALLOWED = {
    "get_candidate": {"verifier"},
    "candidate": {"extractor"},
    "claim": {"extractor"},
    "route": {"extractor"},
    "evidence": {"verifier"},
    "verify_source": {"verifier"},
    "get_evidence": {"verifier", "runtime"},
    "question": {"designer"},
    "seed": {"designer"},
    "packet": {"builder"},
    "publish": {"runtime"},
    "get_resolution": {"runtime"},
    "assertion": {"typed", "reviewer"},
    "blind_packet": {"adjudicator"},
    "adjudicate": {"adjudicator"},
    "gold": {"gold"},
    "get_adjudication": {"gold"},
}
MAX_REQUEST = 1024 * 1024


def dispatch(repository, operation, data, role, principal, corpus):
    if operation in {"put_object", "get_object", "get_packet_snapshot"}:
        from historian.libsql_store.domain import dispatch as domain_dispatch
        return domain_dispatch(repository,operation,data,role,principal,corpus)
    if role not in ALLOWED.get(operation, set()):
        raise PermissionError("capability denied")
    c = repository.connection
    if operation == "question":
        c.execute("INSERT INTO question VALUES (?,?)", (data["id"], data["text"]))
    elif operation == "get_candidate":
        row = c.execute("SELECT locator,quote FROM candidate WHERE id=?", (data['id'],)).fetchone()
        if row is None:
            raise KeyError(data['id'])
        return {'id':data['id'],'locator':json.loads(row[0]),'quote':row[1]}
    elif operation == "candidate":
        loc = locator_to_record(locator_from_record(data["locator"]))
        with transaction(c):
            c.execute("INSERT INTO candidate VALUES (?,?,?)", (data["id"], canonical(loc), data["quote"]))
            c.execute("INSERT INTO candidate_intake VALUES (?,?,?,?)",
                      (data["id"],data.get("extractor_id"),data.get("extraction_run_id"),principal))
    elif operation == "evidence":
        return repository.insert_evidence(data, principal)
    elif operation == "verify_source":
        text = RagV1SourceReader(corpus).read_lines(
            data["source_id"], data["version_hash"], data["start"], data["end"]
        )
        if not text or data["quote"] not in text:
            raise ValueError("source mismatch")
        loc = EvidenceLocator(
            "RAG_V1",
            "configured-corpus",
            data["source_id"],
            data["version_hash"],
            SourceCoordinate(
                "LINE",
                (
                    CoordinatePart("start", str(data["start"])),
                    CoordinatePart("end", str(data["end"])),
                ),
            ),
            sha256_text(text),
            SourceMaterialState.ORIGINAL,
        )
        return repository.insert_evidence(
            {**data, "locator": locator_to_record(loc)}, principal
        )
    elif operation == "get_evidence":
        row = c.execute(
            "SELECT locator,quote,verified_by FROM evidence WHERE id=?", (data["id"],)
        ).fetchone()
        return (
            None
            if row is None
            else {"locator": json.loads(row[0]), "quote": row[1], "writer": row[2]}
        )
    elif operation == "claim":
        c.execute(
            "INSERT INTO claim VALUES (?,?,?,?)",
            (data["id"], data["evidence_id"], data["question_id"], data["text"]),
        )
    elif operation == "route":
        c.execute(
            "INSERT INTO route VALUES (?,?,?)",
            (data["id"], data["question_id"], data["frame"]),
        )
    elif operation == "publish":
        return repository.publish(data)
    elif operation == "get_resolution":
        row = c.execute(
            "SELECT * FROM published_resolution WHERE id=?", (data["id"],)
        ).fetchone()
        return None if row is None else list(row)
    elif operation == "seed":
        return repository.create_seed(data)
    elif operation == "packet":
        return repository.create_packet(data)
    elif operation == "assertion":
        return repository.insert_assertion(data, principal, role)
    elif operation == "blind_packet":
        exists = c.execute(
            "SELECT id FROM packet_seal WHERE id=?", (data["id"],)
        ).fetchone()
        if not exists:
            raise ValueError("packet not finalized")
        # Deliberately no seed IDs, proposals, prior verdicts, internal metadata or gold.
        return [
            json.loads(r[0])
            for r in c.execute(
                "SELECT e.locator FROM evidence e JOIN packet_evidence pe ON pe.evidence_id=e.id "
                "WHERE pe.packet_id=? ORDER BY e.id",
                (data["id"],),
            ).fetchall()
        ]
    elif operation == "adjudicate":
        c.execute(
            "INSERT INTO adjudication VALUES (?,?,?,?,?)",
            (
                data["id"],
                data["packet_id"],
                principal,
                data["verdict"],
                data.get("conclusion"),
            ),
        )
    elif operation == "get_adjudication":
        return c.execute(
            "SELECT human_id,verdict FROM adjudication WHERE id=?", (data["id"],)
        ).fetchone()
    elif operation == "gold":
        c.execute(
            "INSERT INTO gold VALUES (?,?)", (data["id"], data["adjudication_id"])
        )
    return data["id"]


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        _, uid, _ = struct.unpack(
            "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        principal = f"uid:{uid}"
        role = CAPABILITIES.get(uid, "unassigned")
        repository = None
        try:
            raw = self.rfile.readline(MAX_REQUEST + 1)
            if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                raise ValueError("request size/framing")
            request = json.loads(raw)
            if role == "unassigned":
                raise PermissionError("unknown peer")
            repository = Repository(self.server.database)
            result = dispatch(
                repository,
                request["operation"],
                request.get("data", {}),
                role,
                principal,
                self.server.corpus,
            )
            response = {"ok": True, "result": result}
        except PermissionError:
            response = {"ok": False, "error": "forbidden"}
        except Exception as exc:  # noqa: BLE001 - sanitize errors at the process boundary
            # No SQL payloads, sources, paths or secrets in remote error responses.
            error = type(exc).__name__
            # libsql 0.1.11 exposes constraint violations as ValueError. Match the
            # entire named-CHECK signature; unrelated storage failures prove nothing.
            if type(exc) is ValueError and str(exc) == (
                "CHECK constraint failed: assertion_origin_binding"
            ):
                error = "assertion_origin_binding"
            response = {"ok": False, "error": error}
        finally:
            if repository is not None:
                repository.close()
        response.update(principal=principal, capability=role)
        self.wfile.write((json.dumps(response) + "\n").encode())


def serve(database, socket_path, corpus):
    if os.getuid() != SERVICE_UID:
        raise RuntimeError("profile requires service UID 10000")
    parent = Path(database).parent
    if parent.stat().st_uid != SERVICE_UID or parent.stat().st_mode & 0o077:
        raise RuntimeError("database directory must be service-owned and private")
    socket_dir = Path(socket_path).parent
    if socket_dir.stat().st_uid != SERVICE_UID or socket_dir.stat().st_mode & 0o022:
        raise RuntimeError(
            "socket directory must be service-owned and not caller-writable"
        )
    os.umask(0o077)
    with storage_lock(database):
        initialize(database)
        # The exclusive database lock excludes another instance of this service.
        # Never remove a non-socket file or another owner's socket.
        if Path(socket_path).exists():
            st = Path(socket_path).lstat()
            if not stat.S_ISSOCK(st.st_mode) or st.st_uid != SERVICE_UID:
                raise RuntimeError("socket path is not a service-owned socket")
            with socket.socket(socket.AF_UNIX) as probe:
                try:
                    probe.connect(str(socket_path))
                except ConnectionRefusedError:
                    Path(socket_path).unlink()
                else:
                    raise RuntimeError("socket is already serving")
        try:
            with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
                os.chmod(socket_path, 0o666)
                server.database = database
                server.corpus = corpus
                server.serve_forever()
        finally:
            Path(socket_path).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args()
    serve(args.database, args.socket, args.corpus)
