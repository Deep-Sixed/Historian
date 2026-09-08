-- redacted Historian — capability roles for `evecor_historian`
--
-- The architecture depends on identities being INCAPABLE of reaching certain stores.
-- In-process capability classes express that boundary; these grants enforce it.
--
-- APPEND-ONLY: no application role receives UPDATE or DELETE anywhere.
--
-- NO PASSWORDS HERE, EVER. Roles are created NOLOGIN and given LOGIN + a SCRAM password
-- by 03-credentials.sql.tmpl, rendered at deploy time from redacted.

BEGIN;

CREATE ROLE historian_extractor        NOLOGIN;
CREATE ROLE historian_evidence_verifier NOLOGIN;
CREATE ROLE historian_case_designer     NOLOGIN;
CREATE ROLE historian_typed_ingestor  NOLOGIN;
CREATE ROLE historian_human_reviewer  NOLOGIN;
CREATE ROLE historian_runtime         NOLOGIN;
CREATE ROLE historian_packet_builder  NOLOGIN;
CREATE ROLE historian_adjudicator     NOLOGIN;
CREATE ROLE historian_gold_compiler   NOLOGIN;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO
    historian_extractor, historian_evidence_verifier, historian_case_designer,
    historian_typed_ingestor, historian_human_reviewer, historian_runtime,
    historian_packet_builder, historian_adjudicator, historian_gold_compiler;

-- ------------------------------------------------------------------ shared read set
-- historian_adjudicator is DELIBERATELY EXCLUDED. It sees packets and nothing else.
-- The previous revision granted it evidence_ref/question/taxonomy alongside every other
-- role, which contradicted the "packet only" design; the packet is now self-contained so
-- the grant is no longer needed either.
GRANT SELECT ON evidence_ref, question, frame_taxonomy, taxonomy_entry
    TO historian_extractor, historian_evidence_verifier, historian_case_designer,
       historian_typed_ingestor, historian_human_reviewer, historian_runtime,
       historian_packet_builder, historian_gold_compiler;

-- ------------------------------------------------------- historian_extractor (models)
-- Proposals ONLY. No INSERT grant on any assertion table, so a model-owned process cannot
-- create an AssertedRelation at all - not even one claiming a human origin (G-S2, G-S3).
GRANT INSERT, SELECT ON claim_proposal TO historian_extractor;
GRANT INSERT, SELECT ON proposed_relation, proposed_relation_evidence,
                        proposal_disposition_event, source_role_proposal,
                        source_role_proposal_evidence, routing_proposal,
                        routing_proposal_alternate, evidence_candidate
    TO historian_extractor;

-- NO INSERT on evidence_ref. A fabricated ref was proven to reach gold end-to-end, and
-- EvidenceRef already MEANS "source-backed", so letting a model create one made the type
-- lie about its own epistemic class. The extractor proposes LOCATIONS; only the verifier,
-- which reads the actual source, creates trusted evidence.
REVOKE INSERT, UPDATE, DELETE ON evidence_ref FROM historian_extractor;

-- ------------------------------------------------- historian_evidence_verifier
-- Reads candidates and the source adapter; writes evidence_ref and nothing else.
-- PostgreSQL cannot read RAG v1, so the database enforces WHO may create evidence and
-- the verifier process enforces the content check.
GRANT SELECT ON evidence_candidate TO historian_evidence_verifier;
GRANT INSERT, SELECT ON evidence_ref TO historian_evidence_verifier;

-- ---------------------------------------------------- historian_case_designer
-- Ordinary seed construction. historian_owner stays a migration/provisioning authority,
-- not an application workflow identity.
GRANT INSERT, SELECT ON gold_case_seed, gold_case_seed_evidence, gold_case_seed_invariant,
                        seed_finalization
    TO historian_case_designer;
REVOKE INSERT, UPDATE, DELETE ON seed_finalization FROM historian_case_designer;
REVOKE EXECUTE ON FUNCTION finalize_seed(text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION finalize_seed(text) TO historian_case_designer;

-- ------------------------------------------------------- historian_typed_ingestor
GRANT INSERT, SELECT ON asserted_relation TO historian_typed_ingestor;


-- ------------------------------------------------------- historian_human_reviewer
-- HUMAN_REVIEWED_PROPOSAL ONLY. It may NOT write HUMAN_BLIND_ADJUDICATION: allowing a
-- normal review path to stamp the blind origin would be self-certified blindness, the
-- same flaw class as the original bare-string MODEL bypass.
GRANT INSERT, SELECT ON asserted_relation, asserted_relation_review
    TO historian_human_reviewer;
GRANT SELECT ON proposed_relation TO historian_human_reviewer;

-- historian_blind_compiler was REMOVED. HUMAN_BLIND_ADJUDICATION is not an assertion
-- origin in v0: a blind_adjudication_id FK proved only that the cited adjudication
-- exists, never that it established that particular subject/relation/object, so the role
-- existed to write a label the database could not enforce.

-- ------------------------------------------------------------- historian_runtime
GRANT SELECT ON proposed_relation, proposed_relation_evidence, asserted_relation,
                source_role_proposal, source_role_proposal_evidence, routing_proposal,
                routing_proposal_alternate, asserted_relation_review, claim_proposal
    TO historian_runtime;
GRANT INSERT, SELECT ON resolution, resolution_evidence, resolution_asserted_dep,
                        resolution_proposed_dep, resolution_source_role_dep,
                        resolution_claim_dep
    TO historian_runtime;
-- the runtime may CITE a claim proposal, never author one: claims are inference and
-- inference is written by the extractor identity
REVOKE INSERT ON claim_proposal FROM historian_runtime;
GRANT SELECT ON resolution_support TO historian_runtime;

-- --------------------------------------------------------- historian_packet_builder
GRANT SELECT ON gold_case_seed, gold_case_seed_evidence TO historian_packet_builder;
GRANT INSERT, SELECT ON adjudication_packet, adjudication_packet_evidence
    TO historian_packet_builder;
GRANT SELECT ON packet_finalization TO historian_packet_builder;

-- NO INSERT on packet_finalization for anyone. Granting it would make finalize_packet()
-- OPTIONAL: a builder could stamp evidence_count=1 with any non-empty hash, after which
-- blind_packet exposes the packet and require_finalized_packet() is satisfied - both only
-- test that a finalization ROW EXISTS, never that it came from the verifier. An
-- incomplete or even empty packet could then be adjudicated. The SECURITY DEFINER
-- function is the sole writer.
REVOKE INSERT, UPDATE, DELETE ON packet_finalization FROM
    historian_extractor, historian_evidence_verifier, historian_case_designer,
    historian_typed_ingestor, historian_human_reviewer, historian_runtime,
    historian_packet_builder, historian_adjudicator, historian_gold_compiler;

-- PostgreSQL grants EXECUTE to PUBLIC by default, so an explicit grant is not enough.
REVOKE EXECUTE ON FUNCTION finalize_packet(text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION finalize_packet(text) TO historian_packet_builder;

-- ------------------------------------------------------------ historian_adjudicator
-- A GROUP role. Each adjudicating human gets their OWN login role that is a member of it
-- and a row in adjudicator_principal, because a shared credential cannot supply human
-- provenance (G-S6). See 03-credentials.sql.tmpl.
--
-- Reads the BLIND VIEWS only - never the base packet tables, which carry seed_id.
-- Writes adjudications and CANNOT READ THEM BACK: SELECT on blind_adjudication would let
-- an adjudicator see previous humans' verdicts and resolution_text, an avoidable
-- contamination channel across related or repeated cases.
-- the blind views expose FINALIZED packets only, so an adjudicator cannot see a packet
-- whose evidence set could still change under them
GRANT SELECT ON blind_packet, blind_packet_evidence TO historian_adjudicator;
GRANT INSERT ON blind_adjudication TO historian_adjudicator;
GRANT SELECT ON adjudicator_principal TO historian_adjudicator;

-- ---------------------------------------------------------- historian_gold_compiler
GRANT SELECT ON gold_case_seed, gold_case_seed_evidence, gold_case_seed_invariant,
                adjudication_packet, adjudication_packet_evidence, blind_adjudication
    TO historian_gold_compiler;
GRANT INSERT, SELECT ON evaluation_gold TO historian_gold_compiler;
GRANT SELECT ON evaluation_gold_resolved, evaluation_gold_invariant, gold_coverage
    TO historian_gold_compiler;
GRANT SELECT ON reseed_worklist TO historian_case_designer, historian_gold_compiler;
GRANT SELECT ON packet_finalization, seed_finalization TO historian_gold_compiler;

-- ------------------------------------------------------------------- append-only
DO $$
DECLARE r text; t text;
BEGIN
  FOREACH r IN ARRAY ARRAY['historian_extractor','historian_evidence_verifier',
                           'historian_case_designer','historian_typed_ingestor',
                           'historian_human_reviewer','historian_runtime',
                           'historian_packet_builder','historian_adjudicator',
                           'historian_gold_compiler']
  LOOP
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public'
    LOOP
      EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON public.%I FROM %I', t, r);
    END LOOP;
  END LOOP;
END $$;

-- --------------------------------------- row-level policy: origin must match writer
ALTER TABLE asserted_relation ENABLE ROW LEVEL SECURITY;

CREATE POLICY typed_ingestor_typed_only ON asserted_relation
    FOR INSERT TO historian_typed_ingestor
    WITH CHECK (origin = 'TYPED_SOURCE');

CREATE POLICY human_reviewer_reviewed_only ON asserted_relation
    FOR INSERT TO historian_human_reviewer
    WITH CHECK (origin = 'HUMAN_REVIEWED_PROPOSAL');

CREATE POLICY read_assertions ON asserted_relation
    FOR SELECT TO historian_typed_ingestor, historian_human_reviewer, historian_runtime
    USING (true);

COMMIT;
