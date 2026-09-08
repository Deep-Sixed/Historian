-- EVECOR Historian — schema for database `evecor_historian`
--
-- The invariants are enforced here, not only in application code. Where a forbidden
-- state can be made unrepresentable by a constraint, that is preferred: a CHECK cannot
-- be forgotten by a new code path, and a missing INSERT grant cannot be argued with.
--
-- Append-only: UPDATE and DELETE are revoked from every application role (02-roles.sql).
-- Revisions, reviews, retractions, dispositions and replacements are all NEW ROWS.

BEGIN;

-- ---------------------------------------------------------------- enumerated domains

CREATE TYPE relation_type AS ENUM (
    'SUPERSEDES','CORRECTS','AUGMENTS','CONTRADICTS','CONFIRMS','NARROWS');
-- UNRESOLVED_WITH is deliberately absent: unresolvedness is a resolution OUTCOME.

CREATE TYPE assertion_origin AS ENUM (
    'TYPED_SOURCE','HUMAN_REVIEWED_PROPOSAL');
-- No MODEL / MODEL_CONSENSUS: a model-authored assertion has no encoding (G-S2, G-S3).
--
-- HUMAN_BLIND_ADJUDICATION IS DELIBERATELY ABSENT IN v0. A blind_adjudication_id foreign
-- key proves only that the cited adjudication EXISTS - not that it established this
-- particular subject/relation_type/object. That is the gold cross-wiring bug relocated
-- into the assertion path: any real adjudication id would license any relation triple.
-- Rather than ship an epistemic label the database cannot enforce, the origin is removed
-- until it is needed. When it is, the correct shape is a structured
-- BlindRelationAdjudication whose human verdict itself carries subject_ref,
-- relation_type and object_ref, with the assertion DERIVED from that row and
-- human_adjudicator_id derived too - never supplied alongside it.

CREATE TYPE review_origin        AS ENUM ('TYPED_SOURCE','HUMAN');
CREATE TYPE proposal_disposition AS ENUM ('ACTIVE','REJECTED','SUPERSEDED_BY_PROPOSAL');
CREATE TYPE assertion_review_verdict AS ENUM ('AFFIRMED','REJECTED','RETRACTED');
CREATE TYPE resolution_outcome   AS ENUM ('RESOLVED','UNRESOLVED');
CREATE TYPE resolution_method    AS ENUM ('DETERMINISTIC_RULE','MODEL_INFERENCE','HUMAN_ADJUDICATION');
CREATE TYPE review_verdict       AS ENUM ('ACCEPTED','REJECTED');
CREATE TYPE adjudication_mode    AS ENUM ('BLIND');   -- only BLIND is representable (G-S5)

-- An adjudicator's verdict domain is WIDER than a resolution outcome.
--
-- PACKET_INSUFFICIENT is NOT UNRESOLVED. It means "I cannot adjudicate this question from
-- the evidence supplied" - a statement about the PACKET, not about the evidence's
-- relationship to itself. Without it, a packet whose mechanically-selected span omitted
-- the material the question needs would return UNRESOLVED, and the measurement could not
-- distinguish "the Historian correctly found genuine ambiguity" from "the case designer
-- handed over the wrong 25 lines". That would contaminate the behavioural result in the
-- opposite direction to answer-leakage, and just as fatally.
--
-- The remedy must NOT be curating evidence toward an answer - that destroys the shallow
-- construction the queue depends on. It is to let the blind human reject the packet
-- without ever being told what the answer was.
CREATE TYPE adjudication_verdict AS ENUM ('RESOLVED','UNRESOLVED','PACKET_INSUFFICIENT');
CREATE TYPE source_system        AS ENUM ('RAG_V1','LEDGER','OTHER');
CREATE TYPE coordinate_system    AS ENUM ('LINE');    -- canonical for v0
CREATE TYPE source_role          AS ENUM (
    'LOCAL_OPERATIONAL_DECISION','UPSTREAM_VENDOR_MATERIAL','INCIDENT_RECORD',
    'ARCHITECTURAL_ANALYSIS','COMPARATIVE_REVIEW','UNKNOWN');

-- ------------------------------------------------------------------------- evidence

-- A model may PROPOSE where evidence lives. It may not create trusted evidence.
-- EvidenceRef already means "a source-backed, re-verifiable passage"; letting an
-- extractor write one directly made the type's name a lie, and a fabricated ref was
-- proven to reach gold end-to-end.
CREATE TABLE evidence_candidate (
    id                       text PRIMARY KEY,
    proposed_source_system   source_system NOT NULL,
    proposed_source_id       text NOT NULL,
    proposed_version_hash    text NOT NULL,
    proposed_line_start      integer NOT NULL CHECK (proposed_line_start >= 1),
    proposed_line_end        integer NOT NULL,
    proposed_quote           text NOT NULL,
    extractor_id             text NOT NULL CHECK (extractor_id <> ''),
    extraction_run_id        text NOT NULL CHECK (extraction_run_id <> ''),
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT candidate_span_ordered CHECK (proposed_line_end >= proposed_line_start),
    -- FK target: a resulting EvidenceRef must realise THIS locator, not merely name a
    -- candidate that happens to exist.
    -- proposed_quote is INCLUDED: without it the composite FK lets the quote drift, so
    -- a verifier could cite candidate C1 at the correct locator while recording a
    -- different anchor. passage_hash is deliberately NOT included - discovering the
    -- actual hash is the verifier's job, and binding it would require the candidate to
    -- already know the answer.
    CONSTRAINT candidate_locator UNIQUE
        (id, proposed_source_system, proposed_source_id, proposed_version_hash,
         proposed_line_start, proposed_line_end, proposed_quote)
);
COMMENT ON TABLE evidence_candidate IS
'A LOCATION a model proposes. Carries no trust. Only historian_evidence_verifier, which
reads the actual source, may turn one into an evidence_ref.';


CREATE TABLE evidence_ref (
    id                  text PRIMARY KEY,
    source_id           text NOT NULL,
    source_system       source_system NOT NULL,
    source_version_hash text NOT NULL CHECK (source_version_hash <> ''),
    coordinate_system   coordinate_system NOT NULL DEFAULT 'LINE',
    line_start          integer NOT NULL CHECK (line_start >= 1),
    line_end            integer NOT NULL,
    turn                integer,        -- optional, pending parser audit
    message             integer,        -- optional, pending parser audit
    passage_hash        text NOT NULL CHECK (passage_hash <> ''),
    quote               text NOT NULL CHECK (quote <> ''),
    derived_from_candidate_id text,
    verified_by         text NOT NULL CHECK (verified_by <> ''),
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- The verifier determines the CONTENT (hash, bytes). It must not be able to change
    -- WHICH candidate it claims to have verified: without this the FK proved only that
    -- the cited candidate exists, so a verifier could point at candidate C1 while
    -- recording an entirely different document, version and span.
    CONSTRAINT evidence_realises_its_candidate FOREIGN KEY
        (derived_from_candidate_id, source_system, source_id, source_version_hash,
         line_start, line_end, quote)
        REFERENCES evidence_candidate
        (id, proposed_source_system, proposed_source_id, proposed_version_hash,
         proposed_line_start, proposed_line_end, proposed_quote),
    CONSTRAINT span_ordered CHECK (line_end >= line_start),
    -- FK target: lets packet evidence bind its snapshot CONTENT to this exact passage,
    -- not merely name its id. A pointer without its payload proves nothing.
    CONSTRAINT evidence_identity UNIQUE
        (id, source_id, source_version_hash, line_start, line_end, passage_hash)
);
COMMENT ON TABLE evidence_ref IS
'A SOURCE-BACKED passage. Writable only by historian_evidence_verifier, whose process
re-reads the source at this version and position and recomputes the hash before writing.
The database enforces WHO may create one; the verifier process enforces the content check -
PostgreSQL cannot read RAG v1 itself, and pretending otherwise would be the same
self-certification pattern this design keeps removing.

VERIFICATION MEANS: this passage exists at this source, version and position, with these
bytes. IT DOES NOT MEAN the passage is authoritative, complete, current, or true. For the
ledger in particular, verifying that a claim exists proves nothing about a claim that does
not - the documented recording gap makes absence uninformative.';

-- verified_by is OVERWRITTEN from the authenticated login. A writable column repeats the
-- self-reported-identity defect in service form: the verifier could name a different
-- verifier. session_user rather than current_user, because SET ROLE cannot change it.
CREATE FUNCTION bind_verifier_identity() RETURNS trigger AS $$
BEGIN
    NEW.verified_by := session_user;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

COMMENT ON COLUMN evidence_ref.source_version_hash IS
'Required. Document id plus quote does not identify WHICH VERSION was cited; we have a live
case where a document''s indexed representation differs from the original archive.';

CREATE TRIGGER bind_verifier_identity_trg BEFORE INSERT ON evidence_ref
    FOR EACH ROW EXECUTE FUNCTION bind_verifier_identity();

CREATE TABLE question (
    id                     text PRIMARY KEY,
    text                   text NOT NULL,
    UNIQUE (id, text),   -- FK target: a seed's frozen copy must BE this question's text
    version                integer NOT NULL DEFAULT 1,
    caller_frame           text,
    caller_taxonomy_version text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT caller_frame_paired CHECK (
        (caller_frame IS NULL) = (caller_taxonomy_version IS NULL))
);
-- composite FK added after taxonomy_entry exists (see end of file): a caller-supplied
-- frame must be a real member of a real taxonomy version, exactly like an inferred one.
COMMENT ON COLUMN question.caller_frame IS
'An EXPLICIT frame supplied by the caller asking the question. It lives here, on the
question, because the inference layer must not be able to certify its own route as
caller-explicit. routing_proposal is now unconditionally inferential.';

-- ------------------------------------------------------------------ frame taxonomy

CREATE TABLE frame_taxonomy (
    version    text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE taxonomy_entry (
    version text NOT NULL REFERENCES frame_taxonomy(version),
    frame   text NOT NULL,
    PRIMARY KEY (version, frame),
    CONSTRAINT unknown_is_implicit CHECK (frame <> 'UNKNOWN_OR_AMBIGUOUS')
);

-- ------------------------------------------------------- proposals (append-only)

CREATE TABLE proposed_relation (
    id                text PRIMARY KEY,
    subject_ref_id    text NOT NULL REFERENCES evidence_ref(id),
    relation_type     relation_type NOT NULL,
    object_ref_id     text NOT NULL REFERENCES evidence_ref(id),
    extractor_id      text NOT NULL CHECK (extractor_id <> ''),
    extraction_run_id text NOT NULL CHECK (extraction_run_id <> ''),
    created_at        timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE proposed_relation IS
'No disposition column and no support-count column. Disposition is a separate append-only
event; support is DERIVED by counting distinct extraction_run_id per claim. 100 agreeing
model proposals are still 100 proposals (G-S3).';

CREATE TABLE proposed_relation_evidence (
    proposal_id text NOT NULL REFERENCES proposed_relation(id),
    evidence_id text NOT NULL REFERENCES evidence_ref(id),
    ordinal     integer NOT NULL,
    PRIMARY KEY (proposal_id, evidence_id)
);
COMMENT ON TABLE proposed_relation_evidence IS
'WHY the model proposed this. For a Historian that is provenance, not decoration - without
it the persisted record cannot reproduce the in-memory epistemic state.';

CREATE TABLE proposal_disposition_event (
    id                        text PRIMARY KEY,
    proposal_id               text NOT NULL REFERENCES proposed_relation(id),
    disposition               proposal_disposition NOT NULL,
    rationale                 text NOT NULL,
    superseded_by_proposal_id text REFERENCES proposed_relation(id),
    created_at                timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT supersession_names_successor CHECK (
        disposition <> 'SUPERSEDED_BY_PROPOSAL' OR superseded_by_proposal_id IS NOT NULL)
);

CREATE TABLE source_role_proposal (
    id            text PRIMARY KEY,
    source_ref_id text NOT NULL REFERENCES evidence_ref(id),
    proposed_role source_role NOT NULL,
    extractor_id  text NOT NULL CHECK (extractor_id <> ''),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_role_proposal_evidence (
    source_role_proposal_id text NOT NULL REFERENCES source_role_proposal(id),
    evidence_id             text NOT NULL REFERENCES evidence_ref(id),
    ordinal                 integer NOT NULL,
    PRIMARY KEY (source_role_proposal_id, evidence_id)
);

CREATE TABLE routing_proposal (
    id               text PRIMARY KEY,
    question_id      text NOT NULL REFERENCES question(id),
    taxonomy_version text NOT NULL,
    proposed_frame   text NOT NULL,
    extractor_id     text NOT NULL CHECK (extractor_id <> ''),
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- G-S7: the frame must exist in the referenced taxonomy. Composite FK, not a check
    -- in application code that a later path could skip.
    CONSTRAINT frame_in_taxonomy FOREIGN KEY (taxonomy_version, proposed_frame)
        REFERENCES taxonomy_entry(version, frame)
);
COMMENT ON TABLE routing_proposal IS
'ALWAYS inferential. There is no explicitly_specified column: a boolean the extractor could
set would be self-certification, the same flaw class as a self-reported blindness flag.
Caller-explicit routing lives on question.caller_frame and is a DIFFERENT provenance class.';

CREATE TABLE routing_proposal_alternate (
    routing_proposal_id text NOT NULL REFERENCES routing_proposal(id),
    frame               text NOT NULL,
    taxonomy_version    text NOT NULL,
    rationale           text NOT NULL,
    PRIMARY KEY (routing_proposal_id, frame),
    CONSTRAINT alternate_in_taxonomy FOREIGN KEY (taxonomy_version, frame)
        REFERENCES taxonomy_entry(version, frame)
);
COMMENT ON TABLE routing_proposal_alternate IS
'Frames CONSIDERED but not selected. Without these, "converged across the frames
considered" is unverifiable and an incomplete frame set reads as agreement.';

-- -------------------------------------------------------- assertions (append-only)

CREATE TABLE asserted_relation (
    id                       text PRIMARY KEY,
    subject_ref_id           text NOT NULL REFERENCES evidence_ref(id),
    relation_type            relation_type NOT NULL,
    object_ref_id            text NOT NULL REFERENCES evidence_ref(id),
    origin                   assertion_origin NOT NULL,
    typed_source_ref         text,
    human_adjudicator_id     text,
    derived_from_proposal_id text REFERENCES proposed_relation(id),
    created_at               timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT typed_source_shape CHECK (
        origin <> 'TYPED_SOURCE' OR
        (typed_source_ref IS NOT NULL AND derived_from_proposal_id IS NULL)),
    CONSTRAINT reviewed_proposal_shape CHECK (
        origin <> 'HUMAN_REVIEWED_PROPOSAL' OR
        (human_adjudicator_id IS NOT NULL AND derived_from_proposal_id IS NOT NULL)),


    -- G-S4: derived, not settable. A stored boolean is a field someone can set.
    gold_eligible boolean GENERATED ALWAYS AS (
        origin <> 'HUMAN_REVIEWED_PROPOSAL' AND derived_from_proposal_id IS NULL) STORED
);
COMMENT ON TABLE asserted_relation IS
'ASSERTED means an identifiable source or named human EXPLICITLY asserted this. It does NOT
mean the relation is objectively true, and ABSENCE of a row proves nothing about whether the
relation or event exists - the EVECOR ledger has a documented recording gap.';

CREATE TABLE asserted_relation_review (
    id                       text PRIMARY KEY,
    asserted_relation_id     text NOT NULL REFERENCES asserted_relation(id),
    origin                   review_origin NOT NULL,
    verdict                  assertion_review_verdict NOT NULL,
    rationale                text NOT NULL,
    typed_source_ref         text,
    reviewer_id              text,
    replacement_assertion_id text REFERENCES asserted_relation(id),
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT typed_review_shape CHECK (origin <> 'TYPED_SOURCE' OR typed_source_ref IS NOT NULL),
    CONSTRAINT human_review_shape CHECK (origin <> 'HUMAN' OR reviewer_id IS NOT NULL)
);
COMMENT ON TABLE asserted_relation_review IS
'Retraction is a LIFECYCLE event, not a CONTRADICTS relation. The original assertion stays.';

-- ------------------------------------------------------ resolutions (append-only)

CREATE TABLE resolution (
    id                     text PRIMARY KEY,
    question_id            text NOT NULL REFERENCES question(id),
    outcome                resolution_outcome NOT NULL,
    resolution_method      resolution_method NOT NULL,
    conclusion             text,
    unresolved_reason      text,
    routing_proposal_id    text REFERENCES routing_proposal(id),
    previous_resolution_id text REFERENCES resolution(id),
    revision_reason        text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT resolved_has_conclusion CHECK (
        outcome <> 'RESOLVED' OR conclusion IS NOT NULL),
    CONSTRAINT unresolved_says_why CHECK (
        outcome <> 'UNRESOLVED' OR unresolved_reason IS NOT NULL),
    CONSTRAINT unresolved_has_no_conclusion CHECK (
        outcome <> 'UNRESOLVED' OR conclusion IS NULL)
);

CREATE TABLE resolution_evidence (
    resolution_id text NOT NULL REFERENCES resolution(id),
    evidence_id   text NOT NULL REFERENCES evidence_ref(id),
    PRIMARY KEY (resolution_id, evidence_id));

CREATE TABLE resolution_asserted_dep (
    resolution_id text NOT NULL REFERENCES resolution(id),
    assertion_id  text NOT NULL REFERENCES asserted_relation(id),
    PRIMARY KEY (resolution_id, assertion_id));

CREATE TABLE resolution_proposed_dep (
    resolution_id text NOT NULL REFERENCES resolution(id),
    proposal_id   text NOT NULL REFERENCES proposed_relation(id),
    PRIMARY KEY (resolution_id, proposal_id));

CREATE TABLE resolution_source_role_dep (
    resolution_id     text NOT NULL REFERENCES resolution(id),
    source_role_id    text NOT NULL REFERENCES source_role_proposal(id),
    PRIMARY KEY (resolution_id, source_role_id));

-- A claim - what a model says a source SAYS - is inference, and a RESOLVED conclusion is
-- literally the text of one. It therefore needs its own identity and its own dependency
-- edge. The adjudicator previously synthesised 'claim:<evidence_id>' strings and wrote
-- them into resolution_proposed_dep, whose FK targets proposed_relation(id): the row could
-- never have been inserted. A claim is not a relation and does not borrow its edge.
CREATE TABLE claim_proposal (
    id           text PRIMARY KEY,
    evidence_id  text NOT NULL REFERENCES evidence_ref(id),
    question_id  text REFERENCES question(id),
    claim        text NOT NULL CHECK (claim <> ''),
    extractor_id text NOT NULL CHECK (extractor_id <> ''),
    created_at   timestamptz NOT NULL DEFAULT now());

CREATE TABLE resolution_claim_dep (
    resolution_id text NOT NULL REFERENCES resolution(id),
    claim_id      text NOT NULL REFERENCES claim_proposal(id),
    PRIMARY KEY (resolution_id, claim_id));

-- support_profile is DERIVED, never stored. Routing is excluded on purpose: it selects
-- WHICH authority rules apply, not what supports the conclusion, and including it would
-- make every routed resolution PROPOSED_DEPENDENT.
CREATE VIEW resolution_support AS
SELECT r.id AS resolution_id,
       CASE
         WHEN p.n > 0 AND a.n > 0 THEN 'MIXED'
         WHEN p.n > 0             THEN 'PROPOSED_DEPENDENT'
         WHEN a.n > 0             THEN 'ASSERTED_RELATION_DEPENDENT'
         ELSE 'DIRECT_EVIDENCE_ONLY'
       END AS support_profile
FROM resolution r
LEFT JOIN LATERAL (SELECT count(*) n FROM resolution_asserted_dep d WHERE d.resolution_id=r.id) a ON true
LEFT JOIN LATERAL (SELECT (SELECT count(*) FROM resolution_proposed_dep d WHERE d.resolution_id=r.id)
                        + (SELECT count(*) FROM resolution_source_role_dep s WHERE s.resolution_id=r.id)
                        + (SELECT count(*) FROM resolution_claim_dep c WHERE c.resolution_id=r.id) n) p ON true;

CREATE TABLE resolution_review (
    id                        text PRIMARY KEY,
    resolution_id             text NOT NULL REFERENCES resolution(id),
    reviewer_id               text NOT NULL CHECK (reviewer_id <> ''),
    verdict                   review_verdict NOT NULL,
    rationale                 text NOT NULL,
    replacement_resolution_id text REFERENCES resolution(id),
    created_at                timestamptz NOT NULL DEFAULT now(),
    -- rejection establishes only that the resolution is not accepted; it does not
    -- establish what the correct answer is, so a replacement is optional
    CONSTRAINT accepted_has_no_replacement CHECK (
        verdict <> 'ACCEPTED' OR replacement_resolution_id IS NULL)
);

-- ---------------------------------------------------------------- gold (append-only)

CREATE TABLE gold_case_seed (
    id            text PRIMARY KEY,
    question_id   text NOT NULL REFERENCES question(id),
    question_text text NOT NULL,
    family        text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- FK target: a packet must carry THIS seed's question, not an independently
    -- writable string. Otherwise the chain adjudication -> packet -> seed can be
    -- structurally perfect while the human answered a different question.
    CONSTRAINT seed_question_identity UNIQUE (id, question_text),
    -- ...and the seed's frozen copy must itself BE the Question's text, or the
    -- cross-wire simply moves one table upstream: packet==seed proves nothing if
    -- seed != question.
    CONSTRAINT seed_question_is_the_question FOREIGN KEY (question_id, question_text)
        REFERENCES question(id, text)
);
COMMENT ON TABLE gold_case_seed IS
'Internal test-design object. Has no column able to hold an expected answer.';

CREATE TABLE gold_case_seed_evidence (
    seed_id     text NOT NULL REFERENCES gold_case_seed(id),
    evidence_id text NOT NULL REFERENCES evidence_ref(id),
    ordinal     integer NOT NULL,
    PRIMARY KEY (seed_id, evidence_id),
    UNIQUE (seed_id, ordinal));

CREATE TABLE gold_case_seed_invariant (
    seed_id   text NOT NULL REFERENCES gold_case_seed(id),
    invariant text NOT NULL,
    PRIMARY KEY (seed_id, invariant));

CREATE TABLE adjudication_packet (
    id            text PRIMARY KEY,
    seed_id       text NOT NULL,
    UNIQUE (id, seed_id),   -- target for the packet_belongs_to_that_seed FK
    question_text text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- the packet's question IS the seed's question, enforced relationally
    CONSTRAINT packet_question_is_seed_question FOREIGN KEY (seed_id, question_text)
        REFERENCES gold_case_seed(id, question_text)
);
COMMENT ON TABLE adjudication_packet IS
'No packet_hash column: a caller-supplied hash proves nothing. The hash is computed during
finalization over the canonical question + ordered evidence, and lives in packet_finalization.';
COMMENT ON TABLE adjudication_packet IS
'The ONLY thing a blind adjudicator sees. No family column, no invariant column, no expected
outcome column - contamination prevented by absence.';

-- SELF-CONTAINED. The packet carries the verified evidence snapshot itself, so the
-- adjudicator needs no access to evidence_ref, question, or the taxonomy - and therefore
-- no access to any table that could leak Historian state. Previously the packet stored
-- only an evidence_id, which forced a broad evidence_ref grant that contradicted the
-- "packet only" design.
CREATE TABLE adjudication_packet_evidence (
    packet_id           text NOT NULL REFERENCES adjudication_packet(id),
    ordinal             integer NOT NULL,
    -- INTERNAL LINKAGE, never shown to an adjudicator. Proves at the DATABASE layer that
    -- this snapshot materialises an evidence item the SEED selected, rather than relying
    -- on a trusted PacketBuilder. The packet-builder credential can insert rows, so
    -- without this the packet could be populated with unrelated evidence.
    seed_id             text NOT NULL,
    seed_evidence_id    text NOT NULL,
    source_id           text NOT NULL,
    source_version_hash text NOT NULL CHECK (source_version_hash <> ''),
    line_start          integer NOT NULL CHECK (line_start >= 1),
    line_end            integer NOT NULL,
    snapshot_text       text NOT NULL CHECK (snapshot_text <> ''),
    -- GENERATED: two independently writable values could disagree.
    -- Computed by trigger, not GENERATED. The cast form (snapshot_text::bytea) expects
    -- bytea ESCAPE FORMAT, so it succeeds on plain ASCII fixtures and fails on real corpus
    -- text containing backslashes - a bug only real data exposed. convert_to() is correct
    -- but not immutable, so it cannot back a generated column. A BEFORE INSERT trigger
    -- gives the same guarantee: any caller-supplied value is discarded.
    snapshot_hash       text,
    PRIMARY KEY (packet_id, ordinal),
    CONSTRAINT snapshot_span_ordered CHECK (line_end >= line_start),
    CONSTRAINT evidence_selected_by_that_seed FOREIGN KEY (seed_id, seed_evidence_id)
        REFERENCES gold_case_seed_evidence(seed_id, evidence_id),
    CONSTRAINT packet_belongs_to_that_seed FOREIGN KEY (packet_id, seed_id)
        REFERENCES adjudication_packet(id, seed_id),
    -- PAYLOAD BOUND TO POINTER. snapshot_hash is generated from snapshot_text, and this
    -- FK requires it to equal the cited passage's hash with matching source, version and
    -- line span. Naming e1 while freezing unrelated text is therefore impossible.
    CONSTRAINT snapshot_is_that_evidence FOREIGN KEY
        (seed_evidence_id, source_id, source_version_hash, line_start, line_end, snapshot_hash)
        REFERENCES evidence_ref (id, source_id, source_version_hash, line_start, line_end, passage_hash),
    -- one packet row per selected evidence item; no repeats at different ordinals
    CONSTRAINT one_row_per_selected_evidence UNIQUE (packet_id, seed_evidence_id));

-- HOLE 1: the human's identity must not be caller-supplied. SCRAM proves the connection
-- is the historian_adjudicator SERVICE role; it says nothing about which human is at the
-- keyboard. A registered mapping turns the authenticated principal into the recorded
-- adjudicator, so adjudicator_id is DERIVED exactly like routing and gold_eligible.
CREATE TABLE adjudicator_principal (
    db_principal   text PRIMARY KEY,     -- matches current_user
    human_id       text NOT NULL UNIQUE,
    display_name   text NOT NULL,
    registered_at  timestamptz NOT NULL DEFAULT now(),
    is_synthetic   boolean NOT NULL DEFAULT false,
    CONSTRAINT principal_nonempty CHECK (db_principal <> '' AND human_id <> '')
);
COMMENT ON COLUMN adjudicator_principal.is_synthetic IS
'A synthetic principal exists to exercise the pipeline before real human time is spent on
it. Its verdicts are PERMANENTLY ineligible as gold - enforced below, not by convention,
because "we will remember not to count these" is exactly the kind of promise this design
keeps converting into a constraint.';
COMMENT ON TABLE adjudicator_principal IS
'One row per ADJUDICATING HUMAN, each with their own database login. A shared
historian_adjudicator credential cannot satisfy G-S6, which requires human provenance and
not merely provenance to a service account.';

-- -------------------------------------------------------------- seed finalization
-- The same aggregate-mutability defect the packet had, one level upstream. Without this,
-- evidence or invariants could be appended to a seed AFTER a human answered it - and
-- because gold_coverage derives from the seed's CURRENT invariant rows, appending an
-- invariant would let one old adjudication silently "cover" a new one, manufacturing
-- behavioural coverage with no additional adjudicated case.
CREATE TABLE seed_finalization (
    seed_id         text PRIMARY KEY REFERENCES gold_case_seed(id),
    evidence_count  integer NOT NULL CHECK (evidence_count > 0),
    invariant_count integer NOT NULL CHECK (invariant_count > 0),
    seed_hash       text NOT NULL CHECK (seed_hash <> ''),
    finalized_at    timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION finalize_seed(p_seed_id text) RETURNS text AS $$
DECLARE v_ec int; v_ic int; v_hash text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM gold_case_seed WHERE id = p_seed_id) THEN
        RAISE EXCEPTION 'no such seed %', p_seed_id;
    END IF;
    SELECT count(*) INTO v_ec FROM gold_case_seed_evidence WHERE seed_id = p_seed_id;
    SELECT count(*) INTO v_ic FROM gold_case_seed_invariant WHERE seed_id = p_seed_id;
    IF v_ec = 0 THEN RAISE EXCEPTION 'seed % selects no evidence', p_seed_id; END IF;
    IF v_ic = 0 THEN RAISE EXCEPTION 'seed % defends no invariant', p_seed_id; END IF;

    SELECT encode(sha256(convert_to(
        (SELECT question_id || '|' || question_text || '|' || family
           FROM gold_case_seed WHERE id = p_seed_id) ||
        coalesce((SELECT string_agg(format('|E%s:%s', ordinal, evidence_id), ''
                                    ORDER BY ordinal)
                    FROM gold_case_seed_evidence WHERE seed_id = p_seed_id), '') ||
        coalesce((SELECT string_agg(format('|I%s', invariant), '' ORDER BY invariant)
                    FROM gold_case_seed_invariant WHERE seed_id = p_seed_id), ''),
        'UTF8')), 'hex') INTO v_hash;

    INSERT INTO seed_finalization(seed_id, evidence_count, invariant_count, seed_hash)
         VALUES (p_seed_id, v_ec, v_ic, v_hash);
    RETURN v_hash;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE FUNCTION seed_is_frozen() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM seed_finalization WHERE seed_id = NEW.seed_id) THEN
        RAISE EXCEPTION 'seed % is finalized; its content cannot change after a human has '
                        'answered it', NEW.seed_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE TRIGGER seed_evidence_frozen_trg BEFORE INSERT ON gold_case_seed_evidence
    FOR EACH ROW EXECUTE FUNCTION seed_is_frozen();
CREATE TRIGGER seed_invariant_frozen_trg BEFORE INSERT ON gold_case_seed_invariant
    FOR EACH ROW EXECUTE FUNCTION seed_is_frozen();

-- a packet may only be built from a FROZEN seed
CREATE FUNCTION require_finalized_seed() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM seed_finalization WHERE seed_id = NEW.seed_id) THEN
        RAISE EXCEPTION 'seed % is not finalized; a packet built from a mutable seed is '
                        'not a materialisation of anything', NEW.seed_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- ------------------------------------------------------------ packet finalization
-- Append-only rows do not make an AGGREGATE immutable. Without this, evidence could be
-- added to a packet AFTER a verdict, and the blind view would then show a different
-- packet than the human actually saw. Finalization freezes the aggregate and is the
-- point at which exactness is proven.
CREATE TABLE packet_finalization (
    packet_id      text PRIMARY KEY REFERENCES adjudication_packet(id),
    evidence_count integer NOT NULL CHECK (evidence_count > 0),
    packet_hash    text NOT NULL CHECK (packet_hash <> ''),
    finalized_at   timestamptz NOT NULL DEFAULT now()
);

-- Verifies the packet is the seed's EXACT materialisation, then freezes it.
CREATE FUNCTION finalize_packet(p_packet_id text) RETURNS text AS $$
DECLARE
    v_seed text; v_missing int; v_extra int; v_misordered int; v_count int; v_hash text;
BEGIN
    SELECT seed_id INTO v_seed FROM adjudication_packet WHERE id = p_packet_id;
    IF v_seed IS NULL THEN RAISE EXCEPTION 'no such packet %', p_packet_id; END IF;

    -- every evidence item the seed selected must be present
    SELECT count(*) INTO v_missing FROM gold_case_seed_evidence se
     WHERE se.seed_id = v_seed
       AND NOT EXISTS (SELECT 1 FROM adjudication_packet_evidence pe
                        WHERE pe.packet_id = p_packet_id
                          AND pe.seed_evidence_id = se.evidence_id);
    IF v_missing > 0 THEN
        RAISE EXCEPTION 'packet % is incomplete: % evidence item(s) selected by seed % are '
                        'absent', p_packet_id, v_missing, v_seed;
    END IF;

    -- and nothing else
    SELECT count(*) INTO v_extra FROM adjudication_packet_evidence pe
     WHERE pe.packet_id = p_packet_id
       AND NOT EXISTS (SELECT 1 FROM gold_case_seed_evidence se
                        WHERE se.seed_id = v_seed AND se.evidence_id = pe.seed_evidence_id);
    IF v_extra > 0 THEN
        RAISE EXCEPTION 'packet % carries % evidence row(s) the seed did not select',
                        p_packet_id, v_extra;
    END IF;

    -- ordinals must match the seed's ordering exactly
    SELECT count(*) INTO v_misordered
      FROM adjudication_packet_evidence pe
      JOIN gold_case_seed_evidence se
        ON se.seed_id = v_seed AND se.evidence_id = pe.seed_evidence_id
     WHERE pe.packet_id = p_packet_id      -- THIS packet only; without it the check
       AND pe.ordinal <> se.ordinal;       -- scans every packet and reports false
                                           -- mismatches from unrelated ones
    IF v_misordered > 0 THEN
        RAISE EXCEPTION 'packet % presents % evidence item(s) in a different order than '
                        'seed %', p_packet_id, v_misordered, v_seed;
    END IF;

    SELECT count(*) INTO v_count FROM adjudication_packet_evidence
     WHERE packet_id = p_packet_id;

    -- canonical hash over question + ordered evidence identity
    SELECT encode(sha256(convert_to(
             (SELECT question_text FROM adjudication_packet WHERE id = p_packet_id) ||
             coalesce(string_agg(format('|%s|%s|%s|%s|%s|%s',
                        ordinal, source_id, source_version_hash,
                        line_start, line_end, snapshot_hash),
                      '' ORDER BY ordinal), ''), 'UTF8')), 'hex')
      INTO v_hash
      FROM adjudication_packet_evidence WHERE packet_id = p_packet_id;

    INSERT INTO packet_finalization(packet_id, evidence_count, packet_hash)
         VALUES (p_packet_id, v_count, v_hash);
    RETURN v_hash;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- a finalized packet cannot gain evidence
CREATE FUNCTION packet_is_frozen() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM packet_finalization WHERE packet_id = NEW.packet_id) THEN
        RAISE EXCEPTION 'packet % is finalized; its evidence set cannot change',
                        NEW.packet_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE FUNCTION compute_snapshot_hash() RETURNS trigger AS $$
BEGIN
    NEW.snapshot_hash := encode(sha256(convert_to(NEW.snapshot_text, 'UTF8')), 'hex');
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE TRIGGER compute_snapshot_hash_trg BEFORE INSERT ON adjudication_packet_evidence
    FOR EACH ROW EXECUTE FUNCTION compute_snapshot_hash();

CREATE TRIGGER packet_is_frozen_trg BEFORE INSERT ON adjudication_packet_evidence
    FOR EACH ROW EXECUTE FUNCTION packet_is_frozen();

CREATE TRIGGER require_finalized_seed_trg BEFORE INSERT ON adjudication_packet
    FOR EACH ROW EXECUTE FUNCTION require_finalized_seed();

-- and an unfinalized packet cannot be adjudicated
CREATE FUNCTION require_finalized_packet() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM packet_finalization WHERE packet_id = NEW.packet_id) THEN
        RAISE EXCEPTION 'packet % is not finalized; what the adjudicator saw would not be '
                        'reconstructable', NEW.packet_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- HOLE 3: what a blind adjudicator may see. seed_id, family and invariants are absent,
-- so the adjudicator is not asked to trust that a seed id is a meaningless name.
CREATE VIEW blind_packet AS
SELECT p.id AS packet_id, p.question_text, f.packet_hash, f.evidence_count
FROM adjudication_packet p
JOIN packet_finalization f ON f.packet_id = p.id;   -- FINALIZED ONLY

CREATE VIEW blind_packet_evidence AS
SELECT pe.packet_id, pe.ordinal, pe.source_id, pe.source_version_hash,
       pe.line_start, pe.line_end, pe.snapshot_text, pe.snapshot_hash
FROM adjudication_packet_evidence pe
JOIN packet_finalization f ON f.packet_id = pe.packet_id;

CREATE TABLE blind_adjudication (
    id                          text PRIMARY KEY,
    packet_id                   text NOT NULL REFERENCES adjudication_packet(id),
    adjudicator_id              text NOT NULL REFERENCES adjudicator_principal(human_id),
    db_principal                text NOT NULL,
    adjudication_mode           adjudication_mode NOT NULL DEFAULT 'BLIND',
    verdict                     adjudication_verdict NOT NULL,
    resolution_text             text,
    rationale                   text NOT NULL,
    proposal_exposure_declared  boolean NOT NULL DEFAULT false,
    system_output_seen_declared boolean NOT NULL DEFAULT false,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT resolved_adjudication_has_text CHECK (
        verdict <> 'RESOLVED' OR resolution_text IS NOT NULL),
    -- an insufficiency report is about the PACKET; it must not smuggle a conclusion
    CONSTRAINT insufficient_carries_no_resolution CHECK (
        verdict <> 'PACKET_INSUFFICIENT' OR resolution_text IS NULL)
);
COMMENT ON COLUMN blind_adjudication.proposal_exposure_declared IS
'AUDIT ONLY. Not the enforcement mechanism - blindness is enforced by role separation.';

-- adjudicator_id is OVERWRITTEN from the authenticated principal on every insert, so a
-- submitted value is ignored rather than trusted.
CREATE FUNCTION bind_adjudicator_identity() RETURNS trigger AS $$
DECLARE h text;
BEGIN
    -- session_user, NOT current_user: this runs SECURITY DEFINER, so current_user is the
    -- function owner. session_user is the AUTHENTICATED LOGIN and cannot be changed by
    -- SET ROLE, which is exactly the property an identity binding needs.
    SELECT human_id INTO h FROM adjudicator_principal WHERE db_principal = session_user;
    IF h IS NULL THEN
        RAISE EXCEPTION 'principal % is not a registered adjudicating human; a shared '
                        'service credential cannot supply human provenance', session_user;
    END IF;
    NEW.adjudicator_id := h;
    NEW.db_principal   := session_user;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE TRIGGER bind_adjudicator_identity_trg BEFORE INSERT ON blind_adjudication
    FOR EACH ROW EXECUTE FUNCTION bind_adjudicator_identity();

CREATE TRIGGER require_finalized_packet_trg BEFORE INSERT ON blind_adjudication
    FOR EACH ROW EXECUTE FUNCTION require_finalized_packet();

-- REDUCED TO WHAT CANNOT BE DERIVED. seed_id, expected_outcome and expected_resolution
-- are NOT stored: they are followed through adjudication -> packet -> seed. Storing them
-- as writable columns let a client holding the gold-compiler credential cross-wire a
-- verdict from seed B onto seed A, or record an expected answer that differs from the
-- adjudication - exactly what the Python fix prevented, still reachable over SQL.
CREATE TABLE evaluation_gold (
    id                 text PRIMARY KEY,
    adjudication_id    text NOT NULL UNIQUE REFERENCES blind_adjudication(id),
    allowed_abstention boolean NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- The chain, derived rather than asserted. defends_invariants comes from the SEED, so the
-- gold compiler cannot invent them.
CREATE VIEW evaluation_gold_resolved AS
SELECT g.id                AS gold_id,
       g.adjudication_id,
       s.id                AS seed_id,
       s.family,
       a.verdict::text::resolution_outcome AS expected_outcome,
       a.resolution_text   AS expected_resolution,
       g.allowed_abstention,
       a.adjudicator_id
FROM evaluation_gold g
JOIN blind_adjudication  a ON a.id = g.adjudication_id
JOIN adjudication_packet p ON p.id = a.packet_id
JOIN gold_case_seed      s ON s.id = p.seed_id
WHERE a.verdict <> 'PACKET_INSUFFICIENT';

CREATE VIEW evaluation_gold_invariant AS
SELECT g.id AS gold_id, i.invariant
FROM evaluation_gold g
JOIN blind_adjudication  a ON a.id = g.adjudication_id
JOIN adjudication_packet p ON p.id = a.packet_id
JOIN gold_case_seed_invariant i ON i.seed_id = p.seed_id;

-- false abstention is a hard failure (B4): a RESOLVED verdict may not permit abstention.
-- Enforced with a trigger because the verdict lives on the adjudication row.
CREATE FUNCTION gold_abstention_guard() RETURNS trigger AS $$
DECLARE v adjudication_verdict; syn boolean;
BEGIN
    SELECT p.is_synthetic INTO syn
      FROM blind_adjudication a
      JOIN adjudicator_principal p ON p.human_id = a.adjudicator_id
     WHERE a.id = NEW.adjudication_id;
    IF syn THEN
        RAISE EXCEPTION 'adjudication % came from a SYNTHETIC principal and can never '
                        'become gold; behavioural coverage requires an independent human',
                        NEW.adjudication_id;
    END IF;
    SELECT verdict INTO v FROM blind_adjudication WHERE id = NEW.adjudication_id;
    IF v = 'PACKET_INSUFFICIENT' THEN
        RAISE EXCEPTION 'adjudication % reported the packet inadequate; the case must be '
                        'RESEEDED, and it contributes no gold and no coverage',
                        NEW.adjudication_id;
    END IF;
    IF v = 'RESOLVED' AND NEW.allowed_abstention THEN
        RAISE EXCEPTION 'gold for a RESOLVED adjudication cannot allow abstention (B4)';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE TRIGGER gold_abstention_guard_trg BEFORE INSERT ON evaluation_gold
    FOR EACH ROW EXECUTE FUNCTION gold_abstention_guard();

-- deferred: question.caller_frame needs taxonomy_entry to exist
ALTER TABLE question
    ADD CONSTRAINT caller_frame_in_taxonomy
    FOREIGN KEY (caller_taxonomy_version, caller_frame)
    REFERENCES taxonomy_entry(version, frame);

-- Cases a blind adjudicator reported unanswerable FROM THE PACKET. Deliberately exposes
-- the sufficiency rationale and NOT any conclusion, so a reseeder learns what was missing
-- without learning what the answer is.
CREATE VIEW reseed_worklist AS
SELECT s.id AS seed_id, s.family, p.id AS packet_id, a.id AS adjudication_id,
       a.rationale AS insufficiency_reason, a.created_at
FROM blind_adjudication a
JOIN adjudication_packet p ON p.id = a.packet_id
JOIN gold_case_seed      s ON s.id = p.seed_id
WHERE a.verdict = 'PACKET_INSUFFICIENT';

-- G-S9: coverage derived from REAL adjudicated gold, keyed by SEED. Counting caller-made
-- labels would let two strings masquerade as two independently adjudicated cases - the
-- exact illusion the invariant matrix exists to prevent. Multiple adjudications or gold
-- artifacts for one seed still count as ONE case.
CREATE VIEW gold_coverage AS
SELECT DISTINCT s.id AS seed_id, s.family, i.invariant
FROM evaluation_gold g
JOIN blind_adjudication  a ON a.id = g.adjudication_id
JOIN adjudication_packet p ON p.id = a.packet_id
JOIN gold_case_seed      s ON s.id = p.seed_id
JOIN seed_finalization   f ON f.seed_id = s.id      -- FROZEN seeds only
JOIN adjudicator_principal ap ON ap.human_id = a.adjudicator_id AND NOT ap.is_synthetic
JOIN gold_case_seed_invariant i ON i.seed_id = s.id;

COMMIT;
