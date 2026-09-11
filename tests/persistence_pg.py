"""Disposable PostgreSQL probe adapter. Not a production repository implementation."""
import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg

from historian.capability import EvidenceVerificationError, EvidenceVerifier
from historian.persistence.contract import Access, Boundary, Observation
from historian.sources import RagV1SourceReader, SourceRegistry


class PostgreSQLProbe:
    def __init__(self, connect, packet_id):
        self._connect = connect
        self.packet_id = packet_id

    @contextmanager
    def connect(self, role):
        # Report principals actually authenticated by PostgreSQL, never caller payloads.
        with self._connect(role) as connection:
            principal = connection.execute('SELECT session_user').fetchone()[0]
            self.principals.add(principal)
            self.capabilities.add(role)
            yield connection

    def execute(self, test):
        scenario = test.scenario
        self.principals = set()
        self.capabilities = set()
        self.access = Access.NORMAL
        if scenario.startswith('source_'):
            return self.source(scenario)
        with self._connect('historian_owner') as c:
            version = c.execute('SHOW server_version_num').fetchone()[0]
        if int(version) // 10000 != 18:
            return Observation('', Boundary.DATABASE, 'Profile requires PostgreSQL 18',
                               None, '', '', tested=False)
        try:
            observed = self.probe(scenario)
        except psycopg.Error as exc:
            # Only the intended rejection is proof. An unrelated FK/duplicate/setup error
            # must not turn an authorization probe green.
            expected_sqlstate = {
                'seed_different_text': '23503', 'claim_cross_question': 'P0001',
                'route_cross_question': '23503', 'duplicate_identity': '23505',
                'missing_dependency': '23503', 'candidate_crosswire': '23503',
                'insufficient_gold': 'P0001',
                'update_evidence': '42501', 'delete_evidence': '42501',
                'truncate_evidence': '42501', 'extractor_evidence': '42501',
                'extractor_assume_verifier': '42501', 'blind_read_proposals': '42501',
                'forge_finalization': '42501', 'typed_forge_human': '42501',
            }.get(scenario)
            if expected_sqlstate is None or exc.sqlstate != expected_sqlstate:
                raise
            observed = 'rejected'
        return Observation(observed, Boundary.DATABASE,
                           f'Executed raw SQL {scenario}; server_version_num={version}',
                           self.access, ','.join(sorted(self.principals)),
                           ','.join(sorted(self.capabilities)))

    def resolution(self, c, rid, route=None, question='q1'):
        c.execute('''INSERT INTO resolution
            (id,question_id,outcome,resolution_method,conclusion,routing_proposal_id)
            VALUES (%s,%s,'RESOLVED','DETERMINISTIC_RULE','answer',%s)''',
                  (rid, question, route))

    def evidence(self, c, eid, identity='forged', version='version', quote='quote'):
        c.execute('''INSERT INTO evidence_ref
            (id,source_id,source_system,source_version_hash,line_start,line_end,
             passage_hash,quote,verified_by)
            VALUES (%s,'doc','RAG_V1',%s,1,1,%s,%s,%s)''',
                  (eid, version, hashlib.sha256(quote.encode()).hexdigest(), quote, identity))

    def probe(self, scenario):
        rid = 'pv-' + uuid4().hex
        if scenario in ('seed_same_question', 'seed_different_text'):
            self.access = (Access.NORMAL if scenario == 'seed_same_question' else Access.BYPASS)
            with self.connect('historian_case_designer') as c:
                text = 'what?' if scenario == 'seed_same_question' else 'different'
                c.execute('INSERT INTO gold_case_seed(id,question_id,question_text,family) '
                          "VALUES (%s,'q1',%s,'test')", (rid, text))
        elif scenario in ('claim_same_question', 'claim_cross_question'):
            self.access = Access.NORMAL if scenario == 'claim_same_question' else Access.BYPASS
            with self.connect('historian_extractor') as c:
                q = 'q1' if scenario == 'claim_same_question' else 'q2'
                c.execute('INSERT INTO claim_proposal(id,evidence_id,question_id,claim,extractor_id) '
                          "VALUES (%s,'e1',%s,'claim','extractor')", (rid, q))
            with self.connect('historian_runtime') as c:
                self.resolution(c, rid)
                c.execute('INSERT INTO resolution_claim_dep VALUES (%s,%s)', (rid, rid))
        elif scenario in ('route_same_question', 'route_cross_question'):
            self.access = Access.NORMAL if scenario == 'route_same_question' else Access.BYPASS
            with self.connect('historian_extractor') as c:
                q = 'q1' if scenario == 'route_same_question' else 'q2'
                c.execute('''INSERT INTO routing_proposal
                    (id,question_id,taxonomy_version,proposed_frame,extractor_id)
                    VALUES (%s,%s,'v1','CURRENT_OPERATIONAL_STATE','extractor')''', (rid, q))
            with self.connect('historian_runtime') as c:
                self.resolution(c, rid, route=rid)
        elif scenario in ('new_identity', 'duplicate_identity'):
            self.access = Access.NORMAL if scenario == 'new_identity' else Access.TRANSACTION
            with self.connect('historian_runtime') as c:
                self.resolution(c, rid)
                if scenario == 'duplicate_identity':
                    self.resolution(c, rid)
        elif scenario in ('resolution_complete', 'append_published_dependency',
                          'existing_dependency', 'missing_dependency'):
            self.access = (Access.BYPASS if scenario in
                           ('append_published_dependency', 'missing_dependency') else Access.NORMAL)
            with self.connect('historian_runtime') as c, c.transaction():
                self.resolution(c, rid)
                eid = 'missing-' + rid if scenario == 'missing_dependency' else 'e1'
                c.execute('INSERT INTO resolution_evidence VALUES (%s,%s)', (rid, eid))
            # A new connection after commit is deliberately outside the publication method.
            if scenario == 'append_published_dependency':
                with self.connect('historian_runtime') as c:
                    c.execute("INSERT INTO resolution_evidence VALUES (%s,'e2')", (rid,))
        elif scenario == 'new_evidence_version':
            with self.connect('historian_evidence_verifier') as c:
                self.evidence(c, rid, version='v1', quote='original')
                original = c.execute('SELECT * FROM evidence_ref WHERE id=%s', (rid,)).fetchone()
                self.evidence(c, rid + '-revision', version='v2', quote='revised')
            with self.connect('historian_evidence_verifier') as c:
                unchanged = c.execute('SELECT * FROM evidence_ref WHERE id=%s', (rid,)).fetchone()
                revision = c.execute('SELECT source_version_hash,quote FROM evidence_ref '
                                     'WHERE id=%s', (rid + '-revision',)).fetchone()
            return ('accepted' if original is not None and unchanged == original
                    and revision == ('v2', 'revised') else 'lost')
        elif scenario in ('update_evidence', 'delete_evidence',
                          'truncate_evidence', 'verifier_identity', 'forged_verifier_identity'):
            self.access = Access.NORMAL if scenario == 'verifier_identity' else Access.BYPASS
            with self.connect('historian_evidence_verifier') as c:
                self.evidence(c, rid, 'historian_evidence_verifier' if scenario ==
                              'verifier_identity' else 'pretend-owner')
                if scenario == 'update_evidence':
                    c.execute("UPDATE evidence_ref SET quote='changed' WHERE id=%s", (rid,))
                elif scenario == 'delete_evidence':
                    c.execute('DELETE FROM evidence_ref WHERE id=%s', (rid,))
                elif scenario == 'truncate_evidence':
                    c.execute('TRUNCATE evidence_ref CASCADE')
                elif scenario.endswith('identity'):
                    actual = c.execute('SELECT verified_by FROM evidence_ref WHERE id=%s',
                                       (rid,)).fetchone()[0]
                    return 'authenticated' if actual == 'historian_evidence_verifier' else 'forged'
        elif scenario in ('extractor_candidate', 'extractor_evidence', 'extractor_assume_verifier'):
            self.access = {'extractor_candidate': Access.NORMAL,
                           'extractor_evidence': Access.UNAUTHORIZED,
                           'extractor_assume_verifier': Access.BYPASS}[scenario]
            with self.connect('historian_extractor') as c:
                if scenario == 'extractor_evidence':
                    self.evidence(c, rid)
                elif scenario == 'extractor_assume_verifier':
                    c.execute('SET ROLE historian_evidence_verifier')
                    self.evidence(c, rid)
                else:
                    c.execute('''INSERT INTO evidence_candidate
                        (id,proposed_source_system,proposed_source_id,proposed_version_hash,
                         proposed_line_start,proposed_line_end,proposed_quote,extractor_id,
                         extraction_run_id)
                        VALUES (%s,'RAG_V1','doc','v',1,1,'quote','model','run')''', (rid,))
        elif scenario == 'unauthenticated_connection':
            self.access = Access.BYPASS
            self.principals.add('unauthenticated connection attempt')
            self.capabilities.add('invalid credential for historian_extractor')
            import os
            try:
                with psycopg.connect(host=os.environ['HISTORIAN_PGHOST'],
                                     port=os.environ['HISTORIAN_PGPORT'],
                                     dbname=os.environ['HISTORIAN_PGDATABASE'],
                                     user='historian_extractor', password='deliberately-invalid',
                                     connect_timeout=3):
                    return 'accepted'
            except psycopg.OperationalError as exc:
                # A network outage is not proof of authentication enforcement.
                if 'password authentication failed' not in str(exc):
                    raise
                return 'rejected'
        elif scenario.startswith(('locator_', 'coordinate_')):
            self.access = (Access.TRANSACTION if scenario in
                           ('locator_instance_collision', 'coordinate_distinction') else Access.NORMAL)
            with self.connect('historian_evidence_verifier') as c:
                try:
                    if scenario.startswith('coordinate_'):
                        c.execute("""INSERT INTO evidence_ref
                            (id,source_id,source_system,source_version_hash,coordinate_system,
                             line_start,line_end,passage_hash,quote,verified_by)
                            VALUES (%s,'doc','RAG_V1','v','JSON_POINTER',1,1,'h','q','v')""", (rid,))
                    else:
                        c.execute("""INSERT INTO evidence_ref
                            (id,source_id,source_system,source_version_hash,line_start,line_end,
                             passage_hash,quote,verified_by)
                            VALUES (%s,'tweet:1','TWITTER_EXPORT','v',1,1,'h','q','v')""", (rid,))
                except psycopg.errors.InvalidTextRepresentation:
                    return 'unsupported'
            # A permissive enum alone cannot prove a lossless locator/coordinate round-trip.
            raise NotImplementedError('Full locator storage adapter still required')
        elif scenario.startswith('transaction_'):
            self.access = Access.TRANSACTION
            with self.connect('historian_runtime') as c:
                try:
                    with c.transaction():
                        self.resolution(c, rid)
                        c.execute("INSERT INTO resolution_evidence VALUES (%s,'e1')", (rid,))
                        if scenario == 'transaction_visibility':
                            with self.connect('historian_runtime') as observer:
                                row = observer.execute('SELECT id FROM resolution WHERE id=%s',
                                                       (rid,)).fetchone()
                                return 'visible' if row else 'absent'
                        if scenario == 'transaction_rollback':
                            c.execute('INSERT INTO resolution_evidence VALUES (%s,%s)',
                                      (rid, 'absent-' + rid))
                except psycopg.errors.ForeignKeyViolation:
                    if scenario != 'transaction_rollback':
                        raise
            with self.connect('historian_runtime') as observer:
                row = observer.execute('SELECT id FROM resolution WHERE id=%s', (rid,)).fetchone()
                deps = observer.execute('SELECT count(*) FROM resolution_evidence '
                                        'WHERE resolution_id=%s', (rid,)).fetchone()[0]
            if not row and not deps:
                return 'absent'
            return 'complete' if row and deps == 1 else 'partial'
        elif scenario in ('blind_view', 'blind_read_proposals'):
            self.access = Access.NORMAL if scenario == 'blind_view' else Access.BYPASS
            with self.connect('adj_alice') as c:
                if scenario == 'blind_read_proposals':
                    c.execute('SELECT * FROM proposed_relation')
                else:
                    assert c.execute('SELECT packet_id FROM blind_packet WHERE packet_id=%s',
                                     (self.packet_id,)).fetchone()
        elif scenario in ('finalized_packet', 'forge_finalization'):
            self.access = Access.NORMAL if scenario == 'finalized_packet' else Access.BYPASS
            if scenario == 'forge_finalization':
                with self.connect('historian_packet_builder') as c:
                    c.execute('INSERT INTO packet_finalization(packet_id,evidence_count,packet_hash) '
                              "VALUES (%s,1,'fake')", (self.packet_id,))
            else:
                with self.connect('adj_alice') as c:
                    c.execute('''INSERT INTO blind_adjudication
                        (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
                        VALUES (%s,%s,'ignored','RESOLVED','answer','probe')''',
                              (rid, self.packet_id))
        elif scenario in ('typed_assertion', 'typed_forge_human'):
            self.access = Access.NORMAL if scenario == 'typed_assertion' else Access.BYPASS
            with self.connect('historian_typed_ingestor') as c:
                human = scenario == 'typed_forge_human'
                c.execute("""INSERT INTO asserted_relation
                    (id,subject_ref_id,object_ref_id,relation_type,origin,typed_source_ref,
                     human_adjudicator_id,derived_from_proposal_id)
                    VALUES (%s,'e1','e2','CORRECTS',%s,%s,%s,%s)""",
                          (rid, 'HUMAN_REVIEWED_PROPOSAL' if human else 'TYPED_SOURCE',
                           None if human else 'source', 'alice' if human else None,
                           'P1' if human else None))
        elif scenario in ('eligible_gold', 'insufficient_gold',
                          'human_identity', 'forged_human_identity'):
            self.access = (Access.BYPASS if scenario in
                           ('insufficient_gold', 'forged_human_identity') else Access.NORMAL)
            with self.connect('adj_alice') as c:
                insufficient = scenario == 'insufficient_gold'
                c.execute("""INSERT INTO blind_adjudication
                    (id,packet_id,adjudicator_id,verdict,resolution_text,rationale)
                    VALUES (%s,%s,%s,%s,%s,'probe')""",
                          (rid, self.packet_id,
                           'alice' if scenario == 'human_identity' else 'forged-bob',
                           'PACKET_INSUFFICIENT' if insufficient else 'RESOLVED',
                           None if insufficient else 'answer'))
            if scenario.endswith('identity'):
                with self.connect('historian_gold_compiler') as c:
                    actual = c.execute('SELECT adjudicator_id FROM blind_adjudication '
                                       'WHERE id=%s', (rid,)).fetchone()[0]
                return 'authenticated' if actual == 'alice' else 'forged'
            with self.connect('historian_gold_compiler') as c:
                c.execute('INSERT INTO evaluation_gold(id,adjudication_id,allowed_abstention) '
                          'VALUES (%s,%s,false)', (rid, rid))
        elif scenario in ('candidate_binding', 'candidate_crosswire'):
            self.access = Access.NORMAL if scenario == 'candidate_binding' else Access.BYPASS
            with self.connect('historian_extractor') as c:
                c.execute("""INSERT INTO evidence_candidate
                    (id,proposed_source_system,proposed_source_id,proposed_version_hash,
                     proposed_line_start,proposed_line_end,proposed_quote,extractor_id,
                     extraction_run_id)
                    VALUES (%s,'RAG_V1','doc','v',1,1,'quote','extractor','run')""", (rid,))
            with self.connect('historian_evidence_verifier') as c:
                c.execute("""INSERT INTO evidence_ref
                    (id,source_id,source_system,source_version_hash,line_start,line_end,
                     passage_hash,quote,verified_by,derived_from_candidate_id)
                    VALUES (%s,%s,'RAG_V1','v',1,1,'hash','quote','ignored',%s)""",
                          (rid, 'doc' if scenario == 'candidate_binding' else 'other', rid))
        else:
            raise NotImplementedError(scenario)
        return 'accepted'

    def source(self, scenario):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            raw = b'authority passage\n'
            Path(directory, '2026-01-01-source.md').write_bytes(raw)
            candidate = SimpleNamespace(
                id='candidate', proposed_source_system='RAG_V1',
                proposed_source_id='2026-01-01-source',
                proposed_version_hash=hashlib.sha256(raw).hexdigest(),
                proposed_line_start=1, proposed_line_end=1,
                proposed_quote='authority' if scenario == 'source_verified' else 'fabrication')
            writes = []
            verifier = EvidenceVerifier(
                SimpleNamespace(get_candidate=lambda _: candidate),
                SimpleNamespace(put_evidence=writes.append),
                SourceRegistry(RagV1SourceReader(directory)), 'verifier')
            try:
                verifier.verify('candidate', 'evidence')
                result = 'accepted' if len(writes) == 1 else 'missing'
            except EvidenceVerificationError:
                result = 'rejected' if not writes else 'partial'
            return Observation(result, Boundary.TRUSTED_SERVICE,
                               'Real EvidenceVerifier and RagV1SourceReader on synthetic bytes',
                               Access.NORMAL if scenario == 'source_verified' else Access.UNAUTHORIZED,
                               'verifier', 'trusted EvidenceVerifier service')
