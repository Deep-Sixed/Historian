"""Role separation must actually BLOCK, under real authentication.

The earlier revision ran against a `trust` instance. Those tests proved:
    "if PostgreSQL accepts that I am role X, the grants for X behave correctly"
They did NOT prove:
    "only the intended component can become role X"
The second statement is what capability separation requires, so the instance now uses
scram-sha-256 and every connection here authenticates with that role's own credential.

Credentials come from KeePassXC via jarvis-secret. There is no credential file.
"""

import hashlib
import subprocess
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from historian.capability import BlindAdjudicator  # noqa: E402
from historian.types import AdjudicationVerdict  # noqa: E402

JARVIS_SECRET = Path("/mnt/jarvis-data/projects/EVECOR/bin/jarvis-secret")
RUN = uuid.uuid4().hex[:8]


def rid(name: str) -> str:
    """Run-scoped id: the tables are append-only and no role can DELETE, so tests must
    not depend on cleanup that is deliberately impossible."""
    return f"{name}-{RUN}"


# Vault entry title per database role. Credentials live ONLY in KeePassXC; there is no
# loose credential file to read, and nothing here ever prints a value.
VAULT_ENTRY = {
    "historian_owner": "HISTORIAN_OWNER",
    "historian_extractor": "HISTORIAN_EXTRACTOR",
    "historian_evidence_verifier": "HISTORIAN_EVIDENCE_VERIFIER",
    "historian_case_designer": "HISTORIAN_CASE_DESIGNER",
    "historian_typed_ingestor": "HISTORIAN_TYPED_INGESTOR",
    "historian_human_reviewer": "HISTORIAN_HUMAN_REVIEWER",
    "historian_runtime": "HISTORIAN_RUNTIME",
    "historian_packet_builder": "HISTORIAN_PACKET_BUILDER",
    "historian_gold_compiler": "HISTORIAN_GOLD_COMPILER",
    "adj_alice": "HISTORIAN_ADJ_ALICE",
    "adj_bob": "HISTORIAN_ADJ_BOB",
}
_CACHE: dict[str, str] = {}


def _secret(name: str) -> str:
    if name in _CACHE:
        return _CACHE[name]
    if not JARVIS_SECRET.exists():
        pytest.skip("jarvis-secret unavailable")
    r = subprocess.run([str(JARVIS_SECRET), "get", name],
                       capture_output=True, text=True, timeout=120)
    val = r.stdout.strip()
    if r.returncode != 0 or not val:
        pytest.skip(f"vault entry {name} unavailable")
    _CACHE[name] = val
    return val


def conn(role: str):
    pw = _secret(VAULT_ENTRY[role])
    return psycopg.connect(
        f"host=127.0.0.1 port=5444 dbname=evecor_historian user={role} password={pw}",
        autocommit=True)


@pytest.fixture(scope="module", autouse=True)
def reachable():
    try:
        with conn("historian_owner"):
            pass
    except pytest.skip.Exception:
        raise
    except Exception as e:                                    # pragma: no cover
        pytest.skip(f"historian db unreachable: {e}")


PASSAGES = {"e1": "first frozen passage\n", "e2": "second frozen passage\n"}


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture(scope="module")
def seeded():
    """Seed two cases. Evidence hashes are REAL sha256 of the passage text, because the
    packet now binds its snapshot CONTENT to the cited evidence, not just its id."""
    with conn("historian_owner") as c:
        c.execute("INSERT INTO frame_taxonomy(version) VALUES ('v1') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO taxonomy_entry(version,frame) VALUES "
                  "('v1','CURRENT_OPERATIONAL_STATE'),('v1','UPSTREAM_PRODUCT_STATE') "
                  "ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO question(id,text) VALUES ('q1','what?') "
                  "ON CONFLICT DO NOTHING")
        # S2 needs its OWN question: a seed's frozen question_text must BE its
        # Question's text, so S2 can no longer borrow q1 and claim different words.
        c.execute("INSERT INTO question(id,text) VALUES ('q2','other') "
                  "ON CONFLICT DO NOTHING")
    # evidence is written by the VERIFIER identity, never the extractor
    with conn("historian_evidence_verifier") as c:
        for eid, txt in PASSAGES.items():
            c.execute("""INSERT INTO evidence_ref
                (id,source_id,source_system,source_version_hash,line_start,line_end,
                 passage_hash,quote,verified_by)
                VALUES (%s,%s,'RAG_V1','vh',1,2,%s,'anchor','verifier-1')
                ON CONFLICT DO NOTHING""", (eid, f"doc-{eid}", sha(txt)))
    with conn("historian_owner") as c:
        c.execute("""INSERT INTO proposed_relation
            (id,subject_ref_id,relation_type,object_ref_id,extractor_id,extraction_run_id)
            VALUES ('P1','e1','AUGMENTS','e2','model-x','run-1') ON CONFLICT DO NOTHING""")
        # A finalized seed rejects new evidence/invariants BEFORE ON CONFLICT is
        # evaluated - correctly - so the fixture must not re-populate an existing seed.
        already = {r[0] for r in c.execute(
            "SELECT seed_id FROM seed_finalization WHERE seed_id IN ('S1','S2')").fetchall()}
        if not already:
            c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
                VALUES ('S1','q1','what?','authority-trap'),('S2','q2','other','other-family')
                ON CONFLICT DO NOTHING""")
            c.execute("""INSERT INTO gold_case_seed_invariant(seed_id,invariant)
                VALUES ('S1','B7_NO_RECENCY_AS_AUTHORITY'),('S2','B1_NO_RELATION_BY_ABSENCE')
                ON CONFLICT DO NOTHING""")
            c.execute("""INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal)
                VALUES ('S1','e1',0),('S1','e2',1),('S2','e2',0)
                ON CONFLICT DO NOTHING""")
    # seeds must be FROZEN before a packet can materialise them
    with conn("historian_case_designer") as c:
        for s in ("S1", "S2"):
            if not c.execute("SELECT 1 FROM seed_finalization WHERE seed_id=%s",
                             (s,)).fetchone():
                c.execute("SELECT finalize_seed(%s)", (s,))
    return True


def build_packet(pid, seed, question, items, finalize=True):
    """items: [(seed_evidence_id, ordinal)] - snapshot text comes from PASSAGES."""
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,%s,%s)", (pid, seed, question))
        for eid, ordinal in items:
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,
                 source_version_hash,line_start,line_end,snapshot_text)
                VALUES (%s,%s,%s,%s,%s,'vh',1,2,%s)""",
                      (pid, ordinal, seed, eid, f"doc-{eid}", PASSAGES[eid]))
        if finalize:
            c.execute("SELECT finalize_packet(%s)", (pid,))
    return pid


class PgBlindPacketStore:
    """Packet view available to a blind adjudicator: id plus frozen evidence snapshot."""

    class Packet:
        def __init__(self, packet_id, evidence_packet):
            self.id = packet_id
            self.evidence_packet = evidence_packet

    def get_packet(self, packet_id: str):
        with conn("adj_alice") as c:
            row = c.execute("SELECT packet_id FROM blind_packet WHERE packet_id=%s",
                            (packet_id,)).fetchone()
            if row is None:
                raise KeyError(packet_id)
            evidence = tuple(r[0] for r in c.execute(
                "SELECT snapshot_text FROM blind_packet_evidence "
                "WHERE packet_id=%s ORDER BY ordinal", (packet_id,)).fetchall())
        return self.Packet(packet_id, evidence)


class PgBlindAdjudicationStore:
    def put_adjudication(self, adj) -> None:
        with conn("adj_alice") as c:
            c.execute("""INSERT INTO blind_adjudication
                (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
                VALUES (%s,%s,'ignored',%s,%s,%s)""",
                      (adj.id, adj.packet_id, adj.verdict.value,
                       adj.resolution_text, adj.rationale))


@pytest.fixture(scope="module")
def packets(seeded):
    """A complete, finalized packet per seed, plus adjudications."""
    p1 = build_packet(rid("PK1"), "S1", "what?", [("e1", 0), ("e2", 1)])
    p2 = build_packet(rid("PK2"), "S2", "other", [("e2", 0)])
    with conn("adj_alice") as c:
        c.execute("INSERT INTO blind_adjudication (id,packet_id,adjudicator_id,verdict,"
                  "resolution_text,rationale) VALUES (%s,%s,'ignored','RESOLVED',"
                  "'answer for S1','r')", (rid("AD1"), p1))
        c.execute("INSERT INTO blind_adjudication (id,packet_id,adjudicator_id,verdict,"
                  "resolution_text,rationale) VALUES (%s,%s,'ignored','UNRESOLVED',"
                  "NULL,'r')", (rid("AD2"), p2))
    return {"PK1": p1, "PK2": p2}


# ===================================================== 1. authentication is enforced


def test_unauthenticated_connection_is_refused(seeded, packets):
    """The bypass the trust instance could not detect."""
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect("host=127.0.0.1 port=5444 dbname=evecor_historian "
                        "user=historian_extractor", connect_timeout=5)


def test_wrong_password_is_refused(seeded, packets):
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect("host=127.0.0.1 port=5444 dbname=evecor_historian "
                        "user=historian_adjudicator password=wrong", connect_timeout=5)


def test_scram_is_the_password_encryption(seeded, packets):
    with conn("historian_owner") as c:
        assert c.execute("show password_encryption").fetchone()[0] == "scram-sha-256"


# ============================================ 2. adjudicator really is packet-only


@pytest.mark.parametrize("table", [
    "evidence_ref", "question", "frame_taxonomy", "taxonomy_entry",
    "gold_case_seed", "gold_case_seed_invariant", "evaluation_gold",
    "resolution", "proposed_relation", "source_role_proposal", "routing_proposal",
    "adjudication_packet", "adjudication_packet_evidence", "blind_adjudication"])
def test_adjudicator_cannot_read(seeded, table):
    with conn("adj_alice") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(f"SELECT * FROM {table} LIMIT 1")


def test_adjudicator_can_read_its_packet_via_the_blind_view(seeded, packets):
    with conn("adj_alice") as c:
        assert c.execute("SELECT packet_id FROM blind_packet WHERE packet_id=%s",
                         (rid("PK1"),)).fetchone()
        assert c.execute("SELECT snapshot_text FROM blind_packet_evidence "
                         "WHERE packet_id=%s AND ordinal=0",
                         (rid("PK1"),)).fetchone()[0] == PASSAGES["e1"]


# ---- HOLE 1: the human identity is bound to the authenticated principal


def test_adjudicator_id_is_derived_from_the_principal(seeded, packets):
    """A submitted adjudicator_id is DISCARDED. SCRAM proves the service role; only the
    registry proves which human."""
    with conn("adj_bob") as c:
        c.execute("""INSERT INTO blind_adjudication
            (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
            VALUES (%s,%s,'alice','RESOLVED','x','r')""", (rid("AD-bob"), rid("PK1")))
    with conn("historian_owner") as c:
        row = c.execute("SELECT adjudicator_id, db_principal FROM blind_adjudication "
                        "WHERE id=%s", (rid("AD-bob"),)).fetchone()
    assert row == ("bob", "adj_bob")          # not the submitted 'alice'


def test_unregistered_principal_cannot_adjudicate(seeded, packets):
    """The shared group credential has no login, and an unregistered principal is refused."""
    with conn("historian_owner") as c:
        with pytest.raises(psycopg.errors.RaiseException,
                           match="not a registered adjudicating human"):
            c.execute("""INSERT INTO blind_adjudication
                (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
                VALUES (%s,%s,'someone','RESOLVED','x','r')""",
                      (rid("AD-unreg"), rid("PK1")))


def test_group_role_has_no_login(seeded, packets):
    with conn("historian_owner") as c:
        assert c.execute("SELECT rolcanlogin FROM pg_roles "
                         "WHERE rolname='historian_adjudicator'").fetchone()[0] is False


# ---- HOLE 3: prior verdicts are not readable by an adjudicator


def test_adjudicator_cannot_read_prior_verdicts(seeded, packets):
    """SELECT on blind_adjudication would expose other humans' verdicts and reasoning."""
    with conn("adj_alice") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT resolution_text FROM blind_adjudication")


def test_adjudicator_cannot_read_the_base_packet_table(seeded, packets):
    """The base table carries seed_id; the blind view does not."""
    with conn("adj_alice") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT seed_id FROM adjudication_packet")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT seed_id FROM adjudication_packet_evidence")


def test_blind_views_expose_no_seed_linkage(seeded, packets):
    with conn("historian_owner") as c:
        for v in ("blind_packet", "blind_packet_evidence"):
            cols = {r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s", (v,)).fetchall()}
            assert "seed_id" not in cols and "seed_evidence_id" not in cols


# ---- HOLE 4: packet snapshots are bound to the seed's selection in SQL


def test_packet_evidence_must_come_from_that_seed(seeded, packets):
    """The packet-builder credential cannot populate a packet with unrelated evidence."""
    pid = rid("PKX1")
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,'S1','what?')", (pid,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,
                 source_version_hash,line_start,line_end,snapshot_text)
                VALUES (%s,0,'S1','e-not-selected','doc-e1','vh',1,2,%s)""",
                      (pid, PASSAGES["e1"]))


def test_packet_evidence_must_match_its_own_packet_seed(seeded, packets):
    """Evidence from seed S2 cannot be attached to a packet built for seed S1."""
    pid = rid("PKX2")
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,'S1','what?')", (pid,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,
                 source_version_hash,line_start,line_end,snapshot_text)
                VALUES (%s,0,'S2','e2','doc-e2','vh',1,2,%s)""",
                      (pid, PASSAGES["e2"]))


def test_snapshot_content_must_be_the_cited_evidence(seeded, packets):
    """PAYLOAD BOUND TO POINTER: naming e1 while freezing other text is impossible."""
    pid = rid("PKX3")
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,'S1','what?')", (pid,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,
                 source_version_hash,line_start,line_end,snapshot_text)
                VALUES (%s,0,'S1','e1','doc-e1','vh',1,2,'text that is not e1')""", (pid,))


def test_snapshot_hash_is_generated_from_the_text(seeded, packets):
    with conn("historian_owner") as c:
        row = c.execute("SELECT snapshot_text, snapshot_hash FROM "
                        "adjudication_packet_evidence WHERE packet_id=%s AND ordinal=0",
                        (packets["PK1"],)).fetchone()
    assert row[1] == sha(row[0])


def test_supplied_snapshot_hash_is_discarded(seeded, packets):
    """The hash is computed by trigger rather than GENERATED - `convert_to` is not
    immutable so it cannot back a generated column - so a supplied value is DISCARDED
    rather than rejected. Same guarantee, different mechanism."""
    pid = rid("PKX4")
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,'S1','what?')", (pid,))
        c.execute("""INSERT INTO adjudication_packet_evidence
            (packet_id,ordinal,seed_id,seed_evidence_id,source_id,source_version_hash,
             line_start,line_end,snapshot_text,snapshot_hash)
            VALUES (%s,0,'S1','e1','doc-e1','vh',1,2,%s,'deadbeef')""",
                  (pid, PASSAGES["e1"]))
        got = c.execute("SELECT snapshot_hash FROM adjudication_packet_evidence "
                        "WHERE packet_id=%s AND ordinal=0", (pid,)).fetchone()[0]
    assert got != "deadbeef"
    assert got == sha(PASSAGES["e1"])


# ---- packet must be the seed's EXACT, FINALIZED materialisation


def test_incomplete_packet_cannot_be_finalized(seeded, packets):
    """S1 selects e1 AND e2. A packet with only e1 is incomplete - the missing item would
    otherwise be invisible to the adjudicator and to the gold chain."""
    with pytest.raises(psycopg.errors.RaiseException, match="is incomplete"):
        build_packet(rid("PKI"), "S1", "what?", [("e1", 0)])


def test_packet_cannot_carry_unselected_evidence(seeded, packets):
    """Caught by the FK before finalization even runs - stronger than the check itself.
    S2 selected only e2, so attaching e1 is rejected at insert time."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        build_packet(rid("PKE"), "S2", "other", [("e2", 0), ("e1", 1)])


def test_misordered_packet_cannot_be_finalized(seeded, packets):
    with pytest.raises(psycopg.errors.RaiseException, match="different order"):
        build_packet(rid("PKO"), "S1", "what?", [("e1", 1), ("e2", 0)])


def test_packet_question_must_be_the_seed_question(seeded, packets):
    """Otherwise the chain can be perfect while the human answered a different question."""
    with conn("historian_packet_builder") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                      "VALUES (%s,'S1','a substituted question')", (rid("PKQ"),))


def test_finalized_packet_cannot_gain_evidence(seeded, packets):
    """Append-only rows do not make an AGGREGATE immutable."""
    with conn("historian_packet_builder") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="is finalized"):
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,
                 source_version_hash,line_start,line_end,snapshot_text)
                VALUES (%s,9,'S1','e2','doc-e2','vh',1,2,%s)""",
                      (packets["PK1"], PASSAGES["e2"]))


def test_unfinalized_packet_cannot_be_adjudicated(seeded, packets):
    pid = build_packet(rid("PKU"), "S2", "other", [("e2", 0)], finalize=False)
    with conn("adj_alice") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="not finalized"):
            c.execute("INSERT INTO blind_adjudication (id,packet_id,adjudicator_id,"
                      "verdict,resolution_text,rationale) VALUES (%s,%s,'x','RESOLVED',"
                      "'t','r')", (rid("ADU"), pid))


def test_blind_views_show_finalized_packets_only(seeded, packets):
    pid = build_packet(rid("PKV"), "S2", "other", [("e2", 0)], finalize=False)
    with conn("adj_alice") as c:
        assert c.execute("SELECT count(*) FROM blind_packet WHERE packet_id=%s",
                         (pid,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM blind_packet WHERE packet_id=%s",
                         (packets["PK1"],)).fetchone()[0] == 1


def test_packet_hash_is_computed_not_supplied(seeded, packets):
    with conn("historian_owner") as c:
        cols = {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='adjudication_packet'").fetchall()}
        assert "packet_hash" not in cols
        h = c.execute("SELECT packet_hash FROM packet_finalization WHERE packet_id=%s",
                      (packets["PK1"],)).fetchone()[0]
    assert len(h) == 64


def test_a_selected_item_cannot_appear_twice(seeded, packets):
    pid = rid("PKD")
    with conn("historian_packet_builder") as c:
        c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                  "VALUES (%s,'S1','what?')", (pid,))
        c.execute("""INSERT INTO adjudication_packet_evidence
            (packet_id,ordinal,seed_id,seed_evidence_id,source_id,source_version_hash,
             line_start,line_end,snapshot_text) VALUES (%s,0,'S1','e1','doc-e1','vh',1,2,%s)""",
                  (pid, PASSAGES["e1"]))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute("""INSERT INTO adjudication_packet_evidence
                (packet_id,ordinal,seed_id,seed_evidence_id,source_id,source_version_hash,
                 line_start,line_end,snapshot_text)
                VALUES (%s,5,'S1','e1','doc-e1','vh',1,2,%s)""", (pid, PASSAGES["e1"]))


# ================================= 4. blindness cannot be self-certified




def test_human_reviewer_can_write_a_reviewed_proposal(seeded, packets):
    with conn("historian_human_reviewer") as c:
        c.execute("""INSERT INTO asserted_relation
            (id,subject_ref_id,relation_type,object_ref_id,origin,human_adjudicator_id,
             derived_from_proposal_id)
            VALUES (%s,'e1','AUGMENTS','e2','HUMAN_REVIEWED_PROPOSAL','charles','P1')""",
                  (rid("A-rev"),))
        assert c.execute("SELECT gold_eligible FROM asserted_relation WHERE id=%s",
                         (rid("A-rev"),)).fetchone()[0] is False






def test_extractor_cannot_insert_any_assertion(seeded, packets):
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("""INSERT INTO asserted_relation
                (id,subject_ref_id,relation_type,object_ref_id,origin,human_adjudicator_id,
                 derived_from_proposal_id)
                VALUES (%s,'e1','AUGMENTS','e2','HUMAN_REVIEWED_PROPOSAL','fake','P1')""",
                      (rid("X"),))


def test_blind_origin_is_absent_from_the_enum(seeded, packets):
    with conn("historian_owner") as c:
        labels = [r[0] for r in c.execute(
            "SELECT unnest(enum_range(NULL::assertion_origin))::text").fetchall()]
    assert "HUMAN_BLIND_ADJUDICATION" not in labels


def test_no_model_origin_exists(seeded, packets):
    with conn("historian_owner") as c:
        labels = [r[0] for r in c.execute(
            "SELECT unnest(enum_range(NULL::assertion_origin))::text").fetchall()]
    assert "MODEL" not in labels and "MODEL_CONSENSUS" not in labels


# ================================= 5. caller-explicit routing cannot be self-certified


def test_routing_proposal_has_no_explicit_flag(seeded, packets):
    with conn("historian_owner") as c:
        cols = {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='routing_proposal'").fetchall()}
    assert "explicitly_specified" not in cols


def test_extractor_cannot_certify_a_caller_explicit_route(seeded, packets):
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.UndefinedColumn):
            c.execute("""INSERT INTO routing_proposal
                (id,question_id,taxonomy_version,proposed_frame,explicitly_specified)
                VALUES (%s,'q1','v1','CURRENT_OPERATIONAL_STATE',true)""", (rid("R-x"),))


def test_routing_proposal_always_names_an_extractor(seeded, packets):
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.NotNullViolation):
            c.execute("""INSERT INTO routing_proposal
                (id,question_id,taxonomy_version,proposed_frame)
                VALUES (%s,'q1','v1','CURRENT_OPERATIONAL_STATE')""", (rid("R-noext"),))


def test_caller_frame_lives_on_the_question(seeded, packets):
    with conn("historian_owner") as c:
        c.execute("""INSERT INTO question(id,text,caller_frame,caller_taxonomy_version)
            VALUES (%s,'explicit','UPSTREAM_PRODUCT_STATE','v1')""", (rid("q-exp"),))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO question(id,text,caller_frame,caller_taxonomy_version)
                VALUES (%s,'bad','INVENTED','v1')""", (rid("q-bad"),))


def test_invented_frame_is_rejected(seeded, packets):
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO routing_proposal
                (id,question_id,taxonomy_version,proposed_frame,extractor_id)
                VALUES (%s,'q1','v1','INVENTED_FRAME','model-x')""", (rid("R-bad"),))


# ================================= 6. provenance is persisted


def test_proposal_evidence_is_persisted(seeded, packets):
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO proposed_relation
            (id,subject_ref_id,relation_type,object_ref_id,extractor_id,extraction_run_id)
            VALUES (%s,'e1','AUGMENTS','e2','model-x','run-9')""", (rid("P"),))
        c.execute("INSERT INTO proposed_relation_evidence(proposal_id,evidence_id,ordinal)"
                  " VALUES (%s,'e1',0)", (rid("P"),))
        n = c.execute("SELECT count(*) FROM proposed_relation_evidence WHERE proposal_id=%s",
                      (rid("P"),)).fetchone()[0]
    assert n == 1


def test_routing_alternates_are_persisted(seeded, packets):
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO routing_proposal
            (id,question_id,taxonomy_version,proposed_frame,extractor_id)
            VALUES (%s,'q1','v1','CURRENT_OPERATIONAL_STATE','model-x')""", (rid("R-alt"),))
        c.execute("""INSERT INTO routing_proposal_alternate
            (routing_proposal_id,frame,taxonomy_version,rationale)
            VALUES (%s,'UPSTREAM_PRODUCT_STATE','v1','considered, rejected')""",
                  (rid("R-alt"),))
        n = c.execute("SELECT count(*) FROM routing_proposal_alternate "
                      "WHERE routing_proposal_id=%s", (rid("R-alt"),)).fetchone()[0]
    assert n == 1


def test_source_role_evidence_is_persisted(seeded, packets):
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO source_role_proposal
            (id,source_ref_id,proposed_role,extractor_id)
            VALUES (%s,'e1','UPSTREAM_VENDOR_MATERIAL','model-x')""", (rid("SR"),))
        c.execute("""INSERT INTO source_role_proposal_evidence
            (source_role_proposal_id,evidence_id,ordinal) VALUES (%s,'e1',0)""",
                  (rid("SR"),))
        n = c.execute("SELECT count(*) FROM source_role_proposal_evidence "
                      "WHERE source_role_proposal_id=%s", (rid("SR"),)).fetchone()[0]
    assert n == 1


# ================================================================ append-only


@pytest.mark.parametrize("role", [
    "historian_extractor", "historian_typed_ingestor", "historian_human_reviewer",
    "historian_runtime", "historian_packet_builder", "adj_alice",
    "historian_gold_compiler"])
def test_no_role_may_update_or_delete(seeded, role):
    # the adjudicator only reaches views, which are not updatable at all - a stronger
    # refusal than a privilege error, so both are accepted
    denied = (psycopg.errors.InsufficientPrivilege,
              psycopg.errors.ObjectNotInPrerequisiteState)
    tbl, col = (("blind_packet", "packet_id") if role == "adj_alice"
                else ("evidence_ref", "id"))
    with conn(role) as c:
        with pytest.raises(denied):
            c.execute(f"UPDATE {tbl} SET {col}={col}")
        with pytest.raises(denied):
            c.execute(f"DELETE FROM {tbl}")


def test_support_profile_view_excludes_routing(seeded, packets):
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO routing_proposal
            (id,question_id,taxonomy_version,proposed_frame,extractor_id)
            VALUES (%s,'q1','v1','CURRENT_OPERATIONAL_STATE','model-x')""", (rid("R-sp"),))
    with conn("historian_runtime") as c:
        c.execute("""INSERT INTO resolution
            (id,question_id,outcome,resolution_method,conclusion,routing_proposal_id)
            VALUES (%s,'q1','RESOLVED','MODEL_INFERENCE','c',%s)""",
                  (rid("R-route"), rid("R-sp")))
        row = c.execute("SELECT support_profile FROM resolution_support "
                        "WHERE resolution_id=%s", (rid("R-route"),)).fetchone()
    assert row[0] == "DIRECT_EVIDENCE_ONLY"


# ---- G-S9 coverage derived from real adjudicated gold


def test_gold_coverage_view_is_keyed_by_seed(seeded, packets):
    """Coverage counts DISTINCT seeds, derived through the whole chain."""
    from historian.coverage import compute_coverage, coverage_from_gold_rows
    with conn("historian_gold_compiler") as c:
        c.execute("INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) "
                  "VALUES (%s,%s,false)", (rid("GC"), rid("AD1")))
        rows = c.execute("SELECT seed_id, family, invariant FROM gold_coverage").fetchall()
    cases = coverage_from_gold_rows(rows)
    assert any(c_.case_id == "S1" and c_.family == "authority-trap" for c_ in cases)
    report = compute_coverage(cases)
    # one real adjudicated case is NOT coverage: 2 cases from 2 families are required
    assert not report.complete


# ---- the finalizer is the ONLY writer of finalization


def test_packet_builder_cannot_forge_a_finalization(seeded, packets):
    """Granting INSERT here would make finalize_packet() OPTIONAL: blind_packet and
    require_finalized_packet() only test that a finalization ROW EXISTS, so a forged row
    would let an incomplete - even empty - packet be adjudicated."""
    pid = build_packet(rid("PKF"), "S2", "other", [("e2", 0)], finalize=False)
    with conn("historian_packet_builder") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO packet_finalization(packet_id,evidence_count,"
                      "packet_hash) VALUES (%s,1,'anything')", (pid,))


@pytest.mark.parametrize("role", ["historian_extractor", "historian_typed_ingestor",
                                  "historian_human_reviewer", "historian_runtime",
                                  "historian_gold_compiler", "adj_alice"])
def test_only_the_packet_builder_may_finalize(seeded, packets, role):
    """PostgreSQL grants EXECUTE to PUBLIC by default, so the REVOKE must be tested."""
    with conn(role) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT finalize_packet(%s)", (packets["PK1"],))


def test_no_role_can_insert_finalization_directly(seeded, packets):
    for role in ("historian_extractor", "historian_runtime", "historian_gold_compiler"):
        with conn(role) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("INSERT INTO packet_finalization(packet_id,evidence_count,"
                          "packet_hash) VALUES (%s,1,'x')", (packets["PK2"],))


# ---- the seed's question must BE the Question


def test_seed_cannot_restate_the_question(seeded, packets):
    """The cross-wire the previous revision only moved upstream: packet==seed proves
    nothing if seed != question."""
    with conn("historian_owner") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
                VALUES (%s,'q1','a different question','f')""", (rid("SQ"),))


def test_seed_with_the_real_question_is_accepted(seeded, packets):
    with conn("historian_owner") as c:
        c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
            VALUES (%s,'q1','what?','f')""", (rid("SOK"),))


# ---- PROBE: can fabricated evidence reach gold without RAG verification?


def test_the_fabrication_attack_is_now_blocked_at_step_one(seeded, packets):
    """Supersedes the earlier probe, which asserted the extractor COULD insert evidence.

    The recorded attack ran: extractor fabricates an EvidenceRef -> seed selects it ->
    packet finalized -> adjudicated -> gold, and it counted toward coverage. It now fails
    at the first step, because creating trusted evidence is no longer a capability the
    extractor holds.
    """
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("""INSERT INTO evidence_ref
                (id,source_id,source_system,source_version_hash,line_start,line_end,
                 passage_hash,quote,verified_by)
                VALUES (%s,'doc-ghost','RAG_V1','vh-ghost',1,1,%s,'x','self')""",
                      (rid("EGHOST"), sha("nonexistent")))




# ==================== evidence trust boundary: models propose, verifiers create


def test_extractor_cannot_create_evidence(seeded, packets):
    """The end-to-end fabrication attack started exactly here."""
    with conn("historian_extractor") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("""INSERT INTO evidence_ref
                (id,source_id,source_system,source_version_hash,line_start,line_end,
                 passage_hash,quote,verified_by)
                VALUES (%s,'ghost','RAG_V1','v',1,1,'h','q','self')""", (rid("EX"),))


def test_extractor_may_propose_a_candidate(seeded, packets):
    """Models keep proposing LOCATIONS; they just cannot bless them."""
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO evidence_candidate
            (id,proposed_source_system,proposed_source_id,proposed_version_hash,
             proposed_line_start,proposed_line_end,proposed_quote,extractor_id,
             extraction_run_id)
            VALUES (%s,'RAG_V1','doc-e1','vh',1,2,'anchor','model-x','run-1')""",
                  (rid("CAND"),))


def test_a_candidate_is_not_evidence(seeded, packets):
    """An unverified candidate cannot be selected by a seed: the FK targets evidence_ref."""
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO evidence_candidate
            (id,proposed_source_system,proposed_source_id,proposed_version_hash,
             proposed_line_start,proposed_line_end,proposed_quote,extractor_id,
             extraction_run_id)
            VALUES (%s,'RAG_V1','doc-ghost','vh',1,1,'q','model-x','run-1')""",
                  (rid("C2"),))
    with conn("historian_case_designer") as c:
        c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
            VALUES (%s,'q1','what?','probe')""", (rid("SC"),))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal) "
                      "VALUES (%s,%s,0)", (rid("SC"), rid("C2")))


@pytest.mark.parametrize("stmt", [
    "INSERT INTO proposed_relation(id,subject_ref_id,relation_type,object_ref_id,"
    "extractor_id,extraction_run_id) VALUES ('vx','e1','AUGMENTS','e2','v','r')",
    "INSERT INTO asserted_relation(id,subject_ref_id,relation_type,object_ref_id,origin,"
    "typed_source_ref) VALUES ('vx','e1','AUGMENTS','e2','TYPED_SOURCE','c')",
    "INSERT INTO gold_case_seed(id,question_id,question_text,family) "
    "VALUES ('vx','q1','what?','f')",
    "INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) "
    "VALUES ('vx','a',false)"])
def test_verifier_is_an_evidence_authority_only(seeded, packets, stmt):
    with conn("historian_evidence_verifier") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(stmt)


# ==================== the seed is a frozen aggregate too


def test_finalized_seed_cannot_gain_evidence(seeded, packets):
    with conn("historian_case_designer") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="is finalized"):
            c.execute("INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal) "
                      "VALUES ('S1','e2',9)")


def test_finalized_seed_cannot_gain_an_invariant(seeded, packets):
    """The dangerous one: gold_coverage reads the seed's CURRENT invariants, so appending
    one would let a completed adjudication silently cover an invariant nobody judged."""
    with conn("historian_case_designer") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="is finalized"):
            c.execute("INSERT INTO gold_case_seed_invariant(seed_id,invariant) "
                      "VALUES ('S1','B2_ORDER_IS_NOT_AUTHORITY')")


def test_packet_cannot_be_built_from_an_unfinalized_seed(seeded, packets):
    with conn("historian_case_designer") as c:
        c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
            VALUES (%s,'q1','what?','probe')""", (rid("SU"),))
        c.execute("INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal) "
                  "VALUES (%s,'e1',0)", (rid("SU"),))
    with conn("historian_packet_builder") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="not finalized"):
            c.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                      "VALUES (%s,%s,'what?')", (rid("PU"), rid("SU")))


def test_empty_seed_cannot_be_finalized(seeded, packets):
    with conn("historian_case_designer") as c:
        c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
            VALUES (%s,'q1','what?','probe')""", (rid("SE"),))
        with pytest.raises(psycopg.errors.RaiseException, match="selects no evidence"):
            c.execute("SELECT finalize_seed(%s)", (rid("SE"),))


def test_seed_without_an_invariant_cannot_be_finalized(seeded, packets):
    with conn("historian_case_designer") as c:
        c.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
            VALUES (%s,'q1','what?','probe')""", (rid("SI"),))
        c.execute("INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal) "
                  "VALUES (%s,'e1',0)", (rid("SI"),))
        with pytest.raises(psycopg.errors.RaiseException, match="defends no invariant"):
            c.execute("SELECT finalize_seed(%s)", (rid("SI"),))


def test_seed_finalization_cannot_be_forged(seeded, packets):
    with conn("historian_case_designer") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO seed_finalization(seed_id,evidence_count,"
                      "invariant_count,seed_hash) VALUES ('S1',1,1,'x')")


@pytest.mark.parametrize("role", ["historian_extractor", "historian_runtime",
                                  "historian_packet_builder", "historian_gold_compiler"])
def test_only_the_case_designer_may_finalize_a_seed(seeded, packets, role):
    with conn(role) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT finalize_seed('S1')")


def test_coverage_counts_finalized_seeds_only(seeded, packets):
    with conn("historian_gold_compiler") as c:
        rows = c.execute("SELECT DISTINCT seed_id FROM gold_coverage").fetchall()
        fin = c.execute("SELECT count(*) FROM seed_finalization").fetchone()[0]
    assert fin >= 1
    with conn("historian_owner") as c:
        for (sid,) in rows:
            assert c.execute("SELECT 1 FROM seed_finalization WHERE seed_id=%s",
                             (sid,)).fetchone(), f"{sid} in coverage but not finalized"


# ---- synthetic principals can exercise the pipeline but never produce gold


def test_synthetic_principals_are_marked(seeded, packets):
    with conn("historian_owner") as c:
        cols = {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='adjudicator_principal'").fetchall()}
    assert "is_synthetic" in cols


def test_synthetic_verdicts_cannot_become_gold(seeded, packets):
    """'We will remember not to count these' is the kind of promise this design keeps
    converting into a constraint."""
    with conn("historian_owner") as c:
        c.execute("""INSERT INTO adjudicator_principal
            (db_principal,human_id,display_name,is_synthetic)
            VALUES (%s,%s,'synthetic test',true) ON CONFLICT DO NOTHING""",
                  (rid("syn-prin"), rid("syn-human")))
    # a real registered principal must write the verdict - the identity trigger refuses
    # any unregistered login, including the owner
    with conn("adj_alice") as c:
        c.execute("""INSERT INTO blind_adjudication
            (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
            VALUES (%s,%s,'ignored','RESOLVED','x','r')""",
                  (rid("syn-ad"), packets["PK1"]))
    with conn("historian_owner") as c:
        # re-attribute to the synthetic human to test the gold guard in isolation
        c.execute("UPDATE blind_adjudication SET adjudicator_id=%s WHERE id=%s",
                  (rid("syn-human"), rid("syn-ad")))
    with conn("historian_gold_compiler") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="SYNTHETIC principal"):
            c.execute("INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) "
                      "VALUES (%s,%s,false)", (rid("syn-gold"), rid("syn-ad")))


def test_no_gold_descends_from_a_synthetic_principal(seeded, packets):
    """Test the ORIGINATING path. Joining coverage back to *any* adjudication on the same
    seed is wrong: a seed may carry both a real gold-producing verdict and a synthetic
    pipeline verdict, and finding the latter proves nothing."""
    with conn("historian_owner") as c:
        rows = c.execute("""SELECT count(*) FROM evaluation_gold g
            JOIN blind_adjudication a ON a.id = g.adjudication_id
            JOIN adjudicator_principal ap ON ap.human_id = a.adjudicator_id
            WHERE ap.is_synthetic""").fetchone()[0]
    assert rows == 0


# ---- PACKET_INSUFFICIENT: the packet is inadequate, which is NOT the same as UNRESOLVED


def test_insufficient_is_a_distinct_verdict(seeded, packets):
    with conn("historian_owner") as c:
        labels = [r[0] for r in c.execute(
            "SELECT unnest(enum_range(NULL::adjudication_verdict))::text").fetchall()]
    assert labels == ["RESOLVED", "UNRESOLVED", "PACKET_INSUFFICIENT"]


def test_insufficient_cannot_carry_a_resolution(seeded, packets):
    """An insufficiency report is about the PACKET; it must not smuggle a conclusion."""
    with conn("adj_alice") as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("""INSERT INTO blind_adjudication(id,packet_id,adjudicator_id,
                verdict,resolution_text,rationale)
                VALUES (%s,%s,'x','PACKET_INSUFFICIENT','the answer is...','r')""",
                      (rid("ins-bad"), packets["PK2"]))


def test_insufficient_produces_no_gold(seeded, packets):
    with conn("adj_alice") as c:
        c.execute("""INSERT INTO blind_adjudication(id,packet_id,adjudicator_id,verdict,
            rationale) VALUES (%s,%s,'x','PACKET_INSUFFICIENT',
            'the supplied span does not contain material bearing on the question')""",
                  (rid("ins"), packets["PK2"]))
    with conn("historian_gold_compiler") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="must be RESEEDED"):
            c.execute("INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) "
                      "VALUES (%s,%s,false)", (rid("ins-gold"), rid("ins")))


def test_insufficient_appears_on_the_reseed_worklist(seeded, packets):
    with conn("historian_case_designer") as c:
        row = c.execute("SELECT seed_id, insufficiency_reason FROM reseed_worklist "
                        "WHERE adjudication_id=%s", (rid("ins"),)).fetchone()
    assert row and row[0] == "S2"
    assert "does not contain material" in row[1]


def test_reseed_worklist_exposes_no_conclusion(seeded, packets):
    """A reseeder must learn what was missing, never what the answer is."""
    with conn("historian_owner") as c:
        cols = {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='reseed_worklist'").fetchall()}
    assert "resolution_text" not in cols
    assert "verdict" not in cols


def test_insufficient_is_not_false_abstention(seeded, packets):
    """UNRESOLVED and PACKET_INSUFFICIENT must never collapse: one is a judgement about
    the evidence, the other a rejection of the packet."""
    with conn("historian_owner") as c:
        n = c.execute("SELECT count(*) FROM blind_adjudication "
                      "WHERE verdict='PACKET_INSUFFICIENT' AND id=%s",
                      (rid("ins"),)).fetchone()[0]
        g = c.execute("SELECT count(*) FROM evaluation_gold_resolved WHERE gold_id=%s",
                      (rid("ins-gold"),)).fetchone()[0]
    assert n == 1 and g == 0


def test_python_blind_adjudicator_packet_insufficient_reaches_reseed_not_gold(seeded,
                                                                              packets):
    """P2 end-to-end: the capability path can persist packet insufficiency."""
    with conn("historian_owner") as c:
        before_resolutions = c.execute("SELECT count(*) FROM resolution").fetchone()[0]

    adj = BlindAdjudicator(PgBlindPacketStore(), PgBlindAdjudicationStore()).adjudicate(
        adjudication_id=rid("ins-capability"),
        packet_id=packets["PK2"],
        adjudicator_id="ignored-by-db",
        verdict=AdjudicationVerdict.PACKET_INSUFFICIENT,
        rationale="the supplied packet lacks the evidence needed to answer")

    assert adj.verdict is AdjudicationVerdict.PACKET_INSUFFICIENT

    with conn("historian_case_designer") as c:
        row = c.execute("SELECT seed_id, insufficiency_reason FROM reseed_worklist "
                        "WHERE adjudication_id=%s",
                        (rid("ins-capability"),)).fetchone()
    assert row and row[0] == "S2"
    assert "lacks the evidence" in row[1]

    with conn("historian_gold_compiler") as c:
        with pytest.raises(psycopg.errors.RaiseException, match="must be RESEEDED"):
            c.execute("INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) "
                      "VALUES (%s,%s,false)",
                      (rid("ins-capability-gold"), rid("ins-capability")))

    with conn("historian_owner") as c:
        after_resolutions = c.execute("SELECT count(*) FROM resolution").fetchone()[0]
        gold_rows = c.execute("SELECT count(*) FROM evaluation_gold WHERE id=%s",
                              (rid("ins-capability-gold"),)).fetchone()[0]
    assert after_resolutions == before_resolutions
    assert gold_rows == 0
