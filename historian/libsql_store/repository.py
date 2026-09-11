"""Durable operations. Only the isolated service may possess this connection."""

import json
from contextlib import contextmanager
from pathlib import Path

import libsql

from historian.persistence.locator import locator_from_record, locator_to_record


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def connect(path):
    connection = libsql.connect(str(path), isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


@contextmanager
def transaction(connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def initialize(path):
    c = connect(path)
    c.executescript(Path(__file__).with_name("schema.sql").read_text())
    # Revision is INSERT with a new durable ID. Protect every committed row at SQL level.
    tables = [
        r[0]
        for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    for table in tables:
        for operation in ("UPDATE", "DELETE"):
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation}
                BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END""")
    c.close()


class Repository:
    def __init__(self, path):
        self.connection = connect(path)

    def close(self):
        self.connection.close()

    def insert_evidence(self, data, principal):
        locator = locator_to_record(locator_from_record(data["locator"]))
        c = self.connection
        c.execute(
            """INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                locator["source_system"],
                locator["source_instance_id"],
                locator["record_id"],
                locator["version_hash"],
                locator["coordinate_system"],
                canonical(locator["coordinate_parts"]),
                locator["content_hash"],
                locator["material_state"],
                locator["redaction_ref"],
                canonical(locator),
                data["quote"],
                principal,
                data.get("candidate_id"),
            ),
        )
        return data["id"]

    def publish(self, data):
        c = self.connection
        with transaction(c):
            c.execute(
                "INSERT INTO resolution VALUES (?,?,?,?)",
                (
                    data["id"],
                    data["question_id"],
                    data["conclusion"],
                    data.get("route_id"),
                ),
            )
            for evidence in data.get("evidence_ids", []):
                c.execute(
                    "INSERT INTO resolution_evidence VALUES (?,?)",
                    (data["id"], evidence),
                )
            for claim in data.get("claim_ids", []):
                c.execute(
                    "INSERT INTO resolution_claim VALUES (?,?,?)",
                    (data["id"], data["question_id"], claim),
                )
            c.execute("INSERT INTO resolution_seal VALUES (?)", (data["id"],))
        return data["id"]

    def create_seed(self, data):
        c = self.connection
        with transaction(c):
            c.execute(
                "INSERT INTO seed VALUES (?,?,?)",
                (data["id"], data["question_id"], data["question_text"]),
            )
            for eid in data["evidence_ids"]:
                c.execute("INSERT INTO seed_evidence VALUES (?,?)", (data["id"], eid))
            c.execute("INSERT INTO seed_seal VALUES (?)", (data["id"],))
        return data["id"]

    def create_packet(self, data):
        c = self.connection
        with transaction(c):
            c.execute("INSERT INTO packet VALUES (?,?)", (data["id"], data["seed_id"]))
            for (eid,) in c.execute(
                "SELECT evidence_id FROM seed_evidence WHERE seed_id=?",
                (data["seed_id"],),
            ).fetchall():
                c.execute("INSERT INTO packet_evidence VALUES (?,?)", (data["id"], eid))
            c.execute("INSERT INTO packet_seal VALUES (?)", (data["id"],))
        return data["id"]

    def insert_assertion(self, data, principal, capability):
        self.connection.execute(
            "INSERT INTO assertion VALUES (?,?,?,?,?,?)",
            (
                data["id"],
                data["subject_id"],
                data["object_id"],
                data["origin"],
                principal,
                capability,
            ),
        )
        return data["id"]
