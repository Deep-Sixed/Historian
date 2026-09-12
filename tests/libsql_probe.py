"""Profile probes through real kernel identities and durable libSQL storage."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import libsql

from historian.libsql_store.repository import canonical
from historian.persistence.contract import Access, Boundary, Observation

ROLES = {
    "extractor": 10001,
    "verifier": 10002,
    "designer": 10003,
    "typed": 10004,
    "reviewer": 10005,
    "runtime": 10006,
    "builder": 10007,
    "adjudicator": 10008,
    "gold": 10009,
}


def locator(
    instance="account-A", version="v1", coordinate="JSON_POINTER", path="/tweet/text"
):
    return {
        "source_system": "FUTURE_SOURCE",
        "source_instance_id": instance,
        "record_id": "record-1",
        "version_hash": hashlib.sha256(version.encode()).hexdigest(),
        "coordinate_system": coordinate,
        "coordinate_parts": [{"name": "path", "value": path}],
        "content_hash": hashlib.sha256(version.encode()).hexdigest(),
        "material_state": "ORIGINAL",
        "redaction_ref": None,
    }


class LibSQLProbe:
    def __init__(self, database, socket_path, corpus):
        self.database, self.socket, self.corpus = (
            str(database),
            str(socket_path),
            Path(corpus),
        )
        self.rid = ""

    def worker(self, uid, payload):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("libsql_process.py"))],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
            user=uid,
            group=uid,
            extra_groups=[],
        )
        if result.returncode:
            raise RuntimeError("actor process failed")
        result = json.loads(result.stdout)
        assert result["uid"] == uid
        return result

    def call(self, actor_role, operation, **data):
        result = self.worker(
            ROLES.get(actor_role, 10099),
            {
                "kind": "service",
                "socket": self.socket,
                "operation": operation,
                "data": data,
            },
        )
        assert result.get("principal") == f"uid:{ROLES.get(actor_role, 10099)}"
        return result

    def ok(self, role, operation, **data):
        result = self.call(role, operation, **data)
        assert result["ok"], (
            f"fixture/authorized operation failed: {operation}: {result.get('error')}"
        )
        return result["result"]

    def sql(self, *statements):
        return self.worker(
            10000, {"kind": "sql", "database": self.database, "statements": statements}
        )

    def accepted(self, result):
        return "accepted" if result["ok"] else "rejected"

    def db_result(self, result, access, expected_error=None):
        # Missing DB/connection errors are not evidence of an intended rejection.
        if not result["ok"] and (
            expected_error is None or expected_error not in result.get("detail", "")
        ):
            raise RuntimeError("unexpected storage error")
        return Observation(
            self.accepted(result),
            Boundary.DATABASE,
            "Raw libSQL SQL under service UID; no service validation on this path",
            access,
            "uid:10000",
            "trusted storage owner (constraint probe)",
        )

    def service_result(self, result, access, observed=None):
        if not result["ok"] and result.get("error") != "forbidden":
            raise RuntimeError("unexpected service error")
        return Observation(
            observed or self.accepted(result),
            Boundary.TRUSTED_SERVICE,
            "Unix socket request authenticated using SO_PEERCRED",
            access,
            result["principal"],
            result["capability"],
        )

    def assertion_db_result(self, result, access):
        if not result["ok"] and result.get("error") != "assertion_origin_binding":
            raise RuntimeError("assertion origin-binding rejection not proven")
        return Observation(
            self.accepted(result),
            Boundary.DATABASE,
            "SO_PEERCRED-derived assertion context persisted through service; libSQL constraint enforces origin compatibility",
            access,
            result["principal"],
            result["capability"],
        )

    def setup(self):
        self.rid = uuid4().hex
        self.q, self.q2 = self.rid + "-q", self.rid + "-q2"
        self.e, self.e2 = self.rid + "-e", self.rid + "-e2"
        self.seed, self.packet = self.rid + "-seed", self.rid + "-packet"
        self.ok("designer", "question", id=self.q, text="question")
        self.ok("designer", "question", id=self.q2, text="other")
        self.ok("verifier", "evidence", id=self.e, locator=locator(), quote="original")
        self.ok(
            "verifier",
            "evidence",
            id=self.e2,
            locator=locator(version="v2"),
            quote="revised",
        )
        self.ok(
            "designer",
            "seed",
            id=self.seed,
            question_id=self.q,
            question_text="question",
            evidence_ids=[self.e],
        )
        self.ok("builder", "packet", id=self.packet, seed_id=self.seed)

    def publish(self, **overrides):
        return self.ok(
            "runtime",
            "publish",
            **dict(
                id=self.rid,
                question_id=self.q,
                conclusion="answer",
                evidence_ids=[self.e],
                **overrides,
            ),
        )

    def execute(self, test):
        self.setup()
        s = test.scenario
        normal, bypass, tx = Access.NORMAL, Access.BYPASS, Access.TRANSACTION
        if s in ("seed_same_question", "seed_different_text"):
            text = "question" if s == "seed_same_question" else "cross-wired"
            return self.db_result(
                self.sql(("INSERT INTO seed VALUES (?,?,?)", (self.rid, self.q, text))),
                normal if s == "seed_same_question" else bypass,
                "FOREIGN KEY",
            )
        if s in ("claim_same_question", "claim_cross_question"):
            question = self.q if s == "claim_same_question" else self.q2
            self.ok(
                "extractor",
                "claim",
                id=self.rid,
                evidence_id=self.e,
                question_id=question,
                text="c",
            )
            result = self.sql(
                ("INSERT INTO resolution VALUES (?,?,?,NULL)", (self.rid, self.q, "a")),
                (
                    "INSERT INTO resolution_claim VALUES (?,?,?)",
                    (self.rid, self.q, self.rid),
                ),
            )
            return self.db_result(
                result, normal if s == "claim_same_question" else bypass, "FOREIGN KEY"
            )
        if s in ("route_same_question", "route_cross_question"):
            self.ok(
                "extractor",
                "route",
                id=self.rid,
                question_id=self.q if s == "route_same_question" else self.q2,
                frame="F",
            )
            return self.db_result(
                self.sql(
                    (
                        "INSERT INTO resolution VALUES (?,?,?,?)",
                        (self.rid, self.q, "a", self.rid),
                    )
                ),
                normal if s == "route_same_question" else bypass,
                "FOREIGN KEY",
            )
        if s in ("new_identity", "duplicate_identity"):
            self.publish()
            if s == "new_identity":
                result = self.sql(
                    ("SELECT id FROM published_resolution WHERE id=?", (self.rid,))
                )
            else:
                result = self.sql(
                    (
                        "INSERT INTO resolution VALUES (?,?,?,NULL)",
                        (self.rid, self.q, "a"),
                    )
                )
            return self.db_result(
                result, normal if s == "new_identity" else tx, "UNIQUE constraint"
            )
        if s in (
            "resolution_complete",
            "append_published_dependency",
            "existing_dependency",
            "missing_dependency",
        ):
            if s == "missing_dependency":
                result = self.sql(
                    (
                        "INSERT INTO resolution VALUES (?,?,?,NULL)",
                        (self.rid, self.q, "a"),
                    ),
                    (
                        "INSERT INTO resolution_evidence VALUES (?,?)",
                        (self.rid, "missing"),
                    ),
                )
            else:
                self.publish()
                if s == "append_published_dependency":
                    result = self.sql(
                        (
                            "INSERT INTO resolution_evidence VALUES (?,?)",
                            (self.rid, self.e2),
                        )
                    )
                else:
                    result = self.sql(
                        (
                            "SELECT evidence_id FROM resolution_evidence WHERE resolution_id=?",
                            (self.rid,),
                        )
                    )
                    assert result["rows"] == [[[self.e]]]
            return self.db_result(
                result,
                bypass
                if s in ("append_published_dependency", "missing_dependency")
                else normal,
                "published" if s == "append_published_dependency" else "FOREIGN KEY",
            )
        if s == "new_evidence_version":
            before = self.ok("verifier", "get_evidence", id=self.e)
            new_id = self.rid + "-new"
            self.ok(
                "verifier",
                "evidence",
                id=new_id,
                locator=locator(version="new"),
                quote="new",
            )
            after = self.ok("verifier", "get_evidence", id=self.e)
            new = self.ok("verifier", "get_evidence", id=new_id)
            return Observation(
                "accepted"
                if before == after and new["locator"] == locator(version="new")
                else "lost",
                Boundary.DATABASE,
                "Reopened connections read two durable revisions",
                normal,
                "uid:10002",
                "verifier through isolated service",
            )
        if s in ("update_evidence", "delete_evidence", "truncate_evidence"):
            statement = (
                "UPDATE evidence SET quote='changed' WHERE id=?"
                if s == "update_evidence"
                else "DELETE FROM evidence WHERE id=?"
                if s == "delete_evidence"
                else "DELETE FROM evidence"
            )
            return self.db_result(
                self.sql((statement, () if s == "truncate_evidence" else (self.e,))),
                bypass,
                "immutable",
            )
        if s in ("verifier_identity", "forged_verifier_identity"):
            result = self.call(
                "verifier",
                "evidence",
                id=self.rid,
                locator=locator(),
                quote="q",
                verified_by="owner",
            )
            writer = self.ok("verifier", "get_evidence", id=self.rid)["writer"]
            return self.service_result(
                result,
                normal if s == "verifier_identity" else bypass,
                "authenticated" if writer == "uid:10002" else "forged",
            )
        if s == "extractor_candidate":
            return self.service_result(
                self.call(
                    "extractor", "candidate", id=self.rid, locator=locator(), quote="q"
                ),
                normal,
            )
        if s == "extractor_evidence":
            return self.service_result(
                self.call(
                    "extractor", "evidence", id=self.rid, locator=locator(), quote="q"
                ),
                Access.UNAUTHORIZED,
            )
        if s == "extractor_assume_verifier":
            result = self.call(
                "extractor",
                "evidence",
                id=self.rid,
                locator=locator(),
                quote="q",
                role="verifier",
                uid=10002,
            )
            return self.service_result(result, bypass)
        if s == "unauthenticated_connection":
            return self.service_result(
                self.call(
                    "unknown", "evidence", id=self.rid, locator=locator(), quote="q"
                ),
                bypass,
            )
        if s.startswith(("locator_", "coordinate_")):
            first = locator()
            if s == "coordinate_roundtrip":
                first = locator(coordinate="FUTURE_COORDINATE", path="雪/é")
            self.ok("verifier", "evidence", id=self.rid, locator=first, quote="q")
            got = self.ok("verifier", "get_evidence", id=self.rid)["locator"]
            distinct = s in ("locator_instance_collision", "coordinate_distinction")
            if distinct:
                second = (
                    locator(instance="account-B")
                    if s == "locator_instance_collision"
                    else locator(path="/other")
                )
                self.ok(
                    "verifier",
                    "evidence",
                    id=self.rid + "-B",
                    locator=second,
                    quote="q",
                )
                got2 = self.ok("verifier", "get_evidence", id=self.rid + "-B")[
                    "locator"
                ]
                observed = (
                    "distinct"
                    if got == first and got2 == second and got != got2
                    else "lost"
                )
            else:
                observed = "lossless" if got == first else "lost"
            return Observation(
                observed,
                Boundary.DATABASE,
                "Durable locator roundtrip over distinct connections",
                tx if distinct else normal,
                "uid:10002",
                "verifier",
            )
        if s.startswith("transaction_"):
            return self.transaction_probe(s)
        if s == "blind_view":
            result = self.call("adjudicator", "blind_packet", id=self.packet)
            assert result["result"] == [locator()]
            return self.service_result(result, normal)
        if s == "blind_read_proposals":
            return self.service_result(
                self.call("adjudicator", "raw_sql", sql="SELECT * FROM claim"), bypass
            )
        if s == "finalized_packet":
            result = self.sql(("SELECT id FROM packet_seal WHERE id=?", (self.packet,)))
            assert result["rows"] == [[[self.packet]]]
            return self.db_result(result, normal)
        if s == "forge_finalization":
            # A valid sealed seed, but an incomplete packet: raw seal insertion must validate it.
            result = self.sql(
                ("INSERT INTO packet VALUES (?,?)", (self.rid, self.seed)),
                ("INSERT INTO packet_seal VALUES (?)", (self.rid,)),
            )
            return self.db_result(result, bypass, "packet differs from seed")
        if s in ("source_verified", "source_mismatch"):
            raw = b"authority passage\n"
            result = self.call(
                "verifier",
                "verify_source",
                id=self.rid,
                source_id="2026-01-01-source",
                version_hash=hashlib.sha256(raw).hexdigest(),
                start=1,
                end=1,
                quote="authority" if s == "source_verified" else "fabrication",
            )
            if s == "source_mismatch":
                assert result.get("error") == "ValueError"
                assert self.ok("verifier", "get_evidence", id=self.rid) is None
                return Observation(
                    "rejected",
                    Boundary.TRUSTED_SERVICE,
                    "Source anchor mismatch; no persisted evidence",
                    Access.UNAUTHORIZED,
                    result["principal"],
                    result["capability"],
                )
            return self.service_result(result, normal)
        if s in ("typed_assertion", "typed_forge_human"):
            result = self.call(
                "typed",
                "assertion",
                id=self.rid,
                subject_id=self.e,
                object_id=self.e2,
                origin="TYPED_SOURCE"
                if s == "typed_assertion"
                else "HUMAN_REVIEWED_PROPOSAL",
            )
            return self.assertion_db_result(
                result, normal if s == "typed_assertion" else bypass
            )
        if s in (
            "eligible_gold",
            "insufficient_gold",
            "human_identity",
            "forged_human_identity",
        ):
            verdict = "PACKET_INSUFFICIENT" if s == "insufficient_gold" else "RESOLVED"
            result = self.call(
                "adjudicator",
                "adjudicate",
                id=self.rid,
                packet_id=self.packet,
                verdict=verdict,
                conclusion=None if verdict == "PACKET_INSUFFICIENT" else "answer",
                human_id="forged",
            )
            assert result["ok"]
            if s.endswith("identity"):
                writer = self.ok("gold", "get_adjudication", id=self.rid)[0]
                return self.service_result(
                    result,
                    normal if s == "human_identity" else bypass,
                    "authenticated" if writer == "uid:10008" else "forged",
                )
            return self.db_result(
                self.sql(("INSERT INTO gold VALUES (?,?)", (self.rid, self.rid))),
                normal if s == "eligible_gold" else bypass,
                "ineligible adjudication",
            )
        if s in ("candidate_binding", "candidate_crosswire"):
            first = locator()
            self.ok("extractor", "candidate", id=self.rid, locator=first, quote="q")
            data = first if s == "candidate_binding" else locator(instance="other")
            values = (
                self.rid,
                data["source_system"],
                data["source_instance_id"],
                data["record_id"],
                data["version_hash"],
                data["coordinate_system"],
                canonical(data["coordinate_parts"]),
                data["content_hash"],
                data["material_state"],
                data["redaction_ref"],
                canonical(data),
                "q",
                "v",
                self.rid,
            )
            return self.db_result(
                self.sql(
                    (
                        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        values,
                    )
                ),
                normal if s == "candidate_binding" else bypass,
                "FOREIGN KEY",
            )
        raise NotImplementedError(s)

    def transaction_probe(self, scenario):
        # Trusted storage connection owns the transaction; a separate actor process observes it.
        # This test runs as provisioning root, never exposes a connection to an ordinary caller.
        from historian.libsql_store.repository import connect

        c = connect(self.database)
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT INTO resolution VALUES (?,?,?,NULL)",
                (self.rid, self.q, "answer"),
            )
            c.execute(
                "INSERT INTO resolution_evidence VALUES (?,?)", (self.rid, self.e)
            )
            if scenario == "transaction_visibility":
                rows = self.sql(("SELECT id FROM resolution WHERE id=?", (self.rid,)))[
                    "rows"
                ]
                observed = "absent" if rows == [[]] else "visible"
                c.rollback()
            elif scenario == "transaction_rollback":
                try:
                    c.execute(
                        "INSERT INTO resolution_evidence VALUES (?,?)",
                        (self.rid, "missing"),
                    )
                except (libsql.Error, ValueError) as exc:
                    assert "FOREIGN KEY" in str(exc)
                    c.rollback()
                else:
                    c.rollback()
                    raise AssertionError("missing dependency was accepted")
                rows = self.sql(
                    ("SELECT id FROM resolution WHERE id=?", (self.rid,)),
                    (
                        "SELECT evidence_id FROM resolution_evidence WHERE resolution_id=?",
                        (self.rid,),
                    ),
                )["rows"]
                observed = "absent" if rows == [[], []] else "partial"
            else:
                c.execute("INSERT INTO resolution_seal VALUES (?)", (self.rid,))
                c.commit()
                rows = self.sql(
                    ("SELECT id FROM published_resolution WHERE id=?", (self.rid,)),
                    (
                        "SELECT evidence_id FROM resolution_evidence WHERE resolution_id=?",
                        (self.rid,),
                    ),
                )["rows"]
                observed = (
                    "complete" if rows == [[[self.rid]], [[self.e]]] else "partial"
                )
        finally:
            c.close()
        return Observation(
            observed,
            Boundary.DATABASE,
            "Real libSQL transaction with separate process observer",
            Access.TRANSACTION,
            "uid:0 (trusted provisioning probe)",
            "storage-owner constraint probe",
        )
