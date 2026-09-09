"""The verifier's CONTENT check, exercised against the real RAG v1 corpus.

The role tests prove only that the verifier IDENTITY may create evidence. They say nothing
about whether the implemented verifier actually reads the source and rejects false
locations — the suite previously logged in as the verifier and inserted rows directly,
testing around the very component whose job is the check.

Every negative asserts ZERO evidence rows for that candidate. "An exception was raised
somewhere" is not fail-closed; "nothing was written" is.
"""

import hashlib
import os
import subprocess
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from historian.capability import EvidenceVerificationError, EvidenceVerifier
from historian.sources import RagV1SourceReader, SourceRegistry

pytestmark = pytest.mark.pg

CORPUS = Path(os.environ.get(
    "HISTORIAN_CORPUS",
    "/example/corpus",
))
SECRET = Path("/example/corpus")
DOC = os.environ.get("HISTORIAN_TEST_DOC", "2026-07-08-decommissioning-redacted-memory")
RUN = uuid.uuid4().hex[:8]
rid = lambda n: f"{n}-{RUN}"


def _secret(name):
    if val := os.environ.get(name):
        return val
    if not SECRET.exists():
        if os.environ.get("HISTORIAN_RUN_PG") == "1":
            pytest.fail("redacted-secret unavailable and no environment credential supplied")
        pytest.skip("redacted-secret unavailable")
    r = subprocess.run([str(SECRET), "get", name], capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        if os.environ.get("HISTORIAN_RUN_PG") == "1":
            pytest.fail(f"credential {name} unavailable")
        pytest.skip(f"vault entry {name} unavailable")
    return r.stdout.strip()


def conn(role, entry):
    return psycopg.connect(
        " ".join([
            f"host={os.environ.get('HISTORIAN_PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('HISTORIAN_PGPORT', '5444')}",
            f"dbname={os.environ.get('HISTORIAN_PGDATABASE', 'evecor_historian')}",
            f"user={role}",
            f"password={_secret(entry)}",
        ]),
        autocommit=True,
    )


class Candidate:
    """Row shape the verifier consumes."""
    def __init__(self, row):
        (self.id, self.proposed_source_system, self.proposed_source_id,
         self.proposed_version_hash, self.proposed_line_start,
         self.proposed_line_end, self.proposed_quote) = row


class PgCandidates:
    def __init__(self, c): self._c = c
    def get_candidate(self, cid):
        row = self._c.execute(
            "SELECT id, proposed_source_system::text, proposed_source_id, "
            "proposed_version_hash, proposed_line_start, proposed_line_end, "
            "proposed_quote FROM evidence_candidate WHERE id=%s", (cid,)).fetchone()
        if row is None:
            raise KeyError(cid)
        return Candidate(row)


class PgEvidence:
    def __init__(self, c): self._c = c
    def put_evidence(self, r):
        self._c.execute(
            """INSERT INTO evidence_ref(id,source_id,source_system,source_version_hash,
               line_start,line_end,passage_hash,quote,derived_from_candidate_id,verified_by)
               VALUES (%(id)s,%(source_id)s,%(source_system)s,%(source_version_hash)s,
                       %(line_start)s,%(line_end)s,%(passage_hash)s,%(quote)s,
                       %(derived_from_candidate_id)s,%(verified_by)s)""", r)


@pytest.fixture(scope="module")
def reader():
    if not CORPUS.is_dir():
        if os.environ.get("HISTORIAN_RUN_PG") == "1":
            pytest.fail(f"RAG v1 corpus unavailable: {CORPUS}")
        pytest.skip("RAG v1 corpus unavailable")
    return RagV1SourceReader(CORPUS)


@pytest.fixture(scope="module")
def real(reader):
    """A truthful locator into a real corpus document."""
    version = reader.version_of(DOC)
    assert version, f"{DOC} not present in the corpus"
    text = reader.read_lines(DOC, version, 2, 4)
    assert text
    return {"version": version, "text": text, "quote": text.splitlines()[0]}


def propose(cid, *, source_id, version, start, end, quote, system="RAG_V1"):
    with conn("historian_extractor", "HISTORIAN_EXTRACTOR") as c:
        c.execute("""INSERT INTO evidence_candidate
            (id,proposed_source_system,proposed_source_id,proposed_version_hash,
             proposed_line_start,proposed_line_end,proposed_quote,extractor_id,
             extraction_run_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'model-x','run-1')""",
                  (cid, system, source_id, version, start, end, quote))
    return cid


def verify(cid, eid, reader):
    with conn("historian_evidence_verifier", "HISTORIAN_EVIDENCE_VERIFIER") as c:
        registry = SourceRegistry(reader)
        v = EvidenceVerifier(PgCandidates(c), PgEvidence(c), registry, "verifier-1")
        return v.verify(cid, eid)


def evidence_rows(cid):
    with conn("historian_owner", "HISTORIAN_OWNER") as c:
        return c.execute("SELECT count(*) FROM evidence_ref "
                         "WHERE derived_from_candidate_id=%s", (cid,)).fetchone()[0]


# ------------------------------------------------------------------ the happy path


def test_a_truthful_candidate_becomes_evidence(reader, real):
    cid, eid = propose(rid("C-ok"), source_id=DOC, version=real["version"],
                       start=2, end=4, quote=real["quote"]), rid("E-ok")
    ref = verify(cid, eid, reader)
    assert ref["passage_hash"] == hashlib.sha256(real["text"].encode()).hexdigest()
    assert evidence_rows(cid) == 1


def test_persisted_hash_matches_the_actual_source_bytes(reader, real):
    with conn("historian_owner", "HISTORIAN_OWNER") as c:
        row = c.execute("SELECT passage_hash, source_id, source_version_hash, "
                        "line_start, line_end FROM evidence_ref WHERE id=%s",
                        (rid("E-ok"),)).fetchone()
    text = reader.read_lines(row[1], row[2], row[3], row[4])
    assert row[0] == hashlib.sha256(text.encode()).hexdigest()


def test_verified_by_is_the_authenticated_principal(reader, real):
    """The verifier passed 'verifier-1'; the database records who actually connected."""
    with conn("historian_owner", "HISTORIAN_OWNER") as c:
        who = c.execute("SELECT verified_by FROM evidence_ref WHERE id=%s",
                        (rid("E-ok"),)).fetchone()[0]
    assert who == "historian_evidence_verifier"
    assert who != "verifier-1"


# --------------------------------------------------- negatives, all must write nothing


def test_nonexistent_document_fails_closed(reader, real):
    cid = propose(rid("C-nodoc"), source_id="document-that-does-not-exist",
                  version=real["version"], start=1, end=2, quote="x")
    with pytest.raises(EvidenceVerificationError, match="does not exist in source"):
        verify(cid, rid("E-nodoc"), reader)
    assert evidence_rows(cid) == 0


def test_wrong_document_fails_closed(reader, real):
    """A real document, but not the one whose version hash is cited."""
    cid = propose(rid("C-wrongdoc"), source_id="2026-07-14-redacted-v0-8-4-review",
                  version=real["version"], start=2, end=4, quote=real["quote"])
    with pytest.raises(EvidenceVerificationError):
        verify(cid, rid("E-wrongdoc"), reader)
    assert evidence_rows(cid) == 0


def test_wrong_version_hash_fails_closed(reader, real):
    cid = propose(rid("C-ver"), source_id=DOC, version="0" * 64, start=2, end=4,
                  quote=real["quote"])
    with pytest.raises(EvidenceVerificationError):
        verify(cid, rid("E-ver"), reader)
    assert evidence_rows(cid) == 0


def test_out_of_range_span_fails_closed(reader, real):
    cid = propose(rid("C-span"), source_id=DOC, version=real["version"],
                  start=900000, end=900001, quote=real["quote"])
    with pytest.raises(EvidenceVerificationError):
        verify(cid, rid("E-span"), reader)
    assert evidence_rows(cid) == 0


def test_wrong_anchor_fails_closed(reader, real):
    """Right document, right version, right span - but the quote is not there."""
    cid = propose(rid("C-anchor"), source_id=DOC, version=real["version"],
                  start=2, end=4, quote="this text is not at those lines")
    with pytest.raises(EvidenceVerificationError, match="anchor"):
        verify(cid, rid("E-anchor"), reader)
    assert evidence_rows(cid) == 0


def test_shifted_span_produces_a_different_hash(reader, real):
    """Silently reading neighbouring lines must not yield the same evidence."""
    other = reader.read_lines(DOC, real["version"], 3, 5)
    assert other != real["text"]
    assert (hashlib.sha256(other.encode()).hexdigest()
            != hashlib.sha256(real["text"].encode()).hexdigest())


# ------------------------------------- provenance is not forgeable at the SQL boundary


def test_verifier_cannot_cite_a_candidate_it_did_not_realise(reader, real):
    """The probe that opened this round: cite a real candidate, record a different
    document, version and span."""
    cid = propose(rid("C-xwire"), source_id=DOC, version=real["version"],
                  start=2, end=4, quote=real["quote"])
    with conn("historian_evidence_verifier", "HISTORIAN_EVIDENCE_VERIFIER") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO evidence_ref(id,source_id,source_system,
                source_version_hash,line_start,line_end,passage_hash,quote,
                derived_from_candidate_id,verified_by)
                VALUES (%s,'doc-B','RAG_V1','version-B',900,950,%s,'bar',%s,'x')""",
                      (rid("E-xwire"), hashlib.sha256(b"bar").hexdigest(), cid))
    assert evidence_rows(cid) == 0


def test_candidate_source_system_is_part_of_the_binding(reader, real):
    cid = propose(rid("C-sys"), source_id=DOC, version=real["version"], start=2, end=4,
                  quote=real["quote"], system="RAG_V1")
    with conn("historian_evidence_verifier", "HISTORIAN_EVIDENCE_VERIFIER") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO evidence_ref(id,source_id,source_system,
                source_version_hash,line_start,line_end,passage_hash,quote,
                derived_from_candidate_id,verified_by)
                VALUES (%s,%s,'LEDGER',%s,2,4,%s,%s,%s,'x')""",
                      (rid("E-sys"), DOC, real["version"],
                       hashlib.sha256(real["text"].encode()).hexdigest(),
                       real["quote"], cid))
    assert evidence_rows(cid) == 0


# ---------------------- source system must SELECT the adapter, not merely label the row


def test_wrong_source_system_fails_closed(reader, real):
    """A candidate claiming LEDGER while naming a real RAG document must NOT verify.

    Without adapter dispatch the bytes would be read from RAG, verification would
    succeed, and the candidate FK would faithfully persist LEDGER provenance the bytes
    never supported.
    """
    cid = propose(rid("C-sysmis"), source_id=DOC, version=real["version"], start=2, end=4,
                  quote=real["quote"], system="LEDGER")
    with pytest.raises(EvidenceVerificationError, match="no reader registered"):
        verify(cid, rid("E-sysmis"), reader)
    assert evidence_rows(cid) == 0


def test_registry_has_no_default_reader(reader):
    from historian.sources import SourceRegistry, SourceUnavailable
    reg = SourceRegistry(reader)
    with pytest.raises(SourceUnavailable):
        reg.reader_for("OTHER")
    assert reg.reader_for("RAG_V1") is reader


def test_registry_key_cannot_be_supplied_by_the_caller(reader):
    """SourceRegistry(LEDGER=rag_reader) would let the registry lie about its backend:
    the lookup resolves LEDGER, the RAG reader supplies the bytes, the EvidenceRef records
    LEDGER. The keyword form is not a representable API shape."""
    from historian.sources import SourceRegistry
    with pytest.raises(TypeError):
        SourceRegistry(LEDGER=reader)


def test_registry_derives_the_key_from_the_reader(reader):
    from historian.sources import SourceRegistry
    reg = SourceRegistry(reader)
    assert reg.reader_for(reader.source_system) is reader


def test_registry_refuses_a_duplicate_backend(reader):
    from historian.sources import RagV1SourceReader, SourceRegistry
    with pytest.raises(ValueError, match="duplicate reader"):
        SourceRegistry(reader, RagV1SourceReader(CORPUS))


def test_registry_refuses_a_reader_that_declares_nothing(reader):
    from historian.sources import SourceRegistry

    class Anonymous:
        def read_lines(self, *a):
            return "whatever it likes"

    with pytest.raises(ValueError, match="declares no source_system"):
        SourceRegistry(Anonymous())


# ---------------------------------------- the candidate's quote is bound relationally


def test_quote_cannot_drift_from_the_candidate(reader, real):
    """Direct SQL under the verifier identity: correct locator, altered anchor."""
    cid = propose(rid("C-quote"), source_id=DOC, version=real["version"], start=2, end=4,
                  quote=real["quote"])
    with conn("historian_evidence_verifier", "HISTORIAN_EVIDENCE_VERIFIER") as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO evidence_ref(id,source_id,source_system,
                source_version_hash,line_start,line_end,passage_hash,quote,
                derived_from_candidate_id,verified_by)
                VALUES (%s,%s,'RAG_V1',%s,2,4,%s,'a different anchor',%s,'x')""",
                      (rid("E-quote"), DOC, real["version"],
                       hashlib.sha256(real["text"].encode()).hexdigest(), cid))
    assert evidence_rows(cid) == 0


# ------------------------------------- the reader cannot escape the corpus namespace


@pytest.mark.parametrize("bad_id", [
    "../etc/passwd", "../../other-project/document", "/absolute/path",
    "subdir/document", "..", "2026-01-01-x/../../escape", "not-a-document-id"])
def test_path_traversal_is_refused(reader, real, bad_id):
    """source_id originates in a candidate a MODEL may write, so the trusted verifier
    must not be steerable outside the corpus - regardless of what exists on disk."""
    assert reader.version_of(bad_id) is None
    assert reader.read_lines(bad_id, real["version"], 1, 2) is None


def test_traversal_candidate_writes_no_evidence(reader, real):
    cid = propose(rid("C-trav"), source_id="../../etc/passwd", version=real["version"],
                  start=1, end=1, quote="root")
    with pytest.raises(EvidenceVerificationError, match="does not exist in source"):
        verify(cid, rid("E-trav"), reader)
    assert evidence_rows(cid) == 0
