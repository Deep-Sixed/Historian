-- Frozen v0 -> question-bound provenance hardening.
--
-- Non-destructive by design: this migration preserves append-only rows and refuses to
-- proceed if existing data contains a state the new invariants cannot truthfully carry
-- forward.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM claim_proposal WHERE question_id IS NULL) THEN
        RAISE EXCEPTION 'cannot make claim_proposal.question_id NOT NULL: null rows exist';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM resolution r
          JOIN routing_proposal rp ON rp.id = r.routing_proposal_id
         WHERE rp.question_id <> r.question_id
    ) THEN
        RAISE EXCEPTION 'cannot bind resolution.routing_proposal_id: cross-wired rows exist';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM resolution_claim_dep d
          JOIN resolution r ON r.id = d.resolution_id
          JOIN claim_proposal cp ON cp.id = d.claim_id
         WHERE cp.question_id <> r.question_id
    ) THEN
        RAISE EXCEPTION 'cannot bind resolution_claim_dep.claim_id: cross-wired rows exist';
    END IF;
END $$;

ALTER TABLE claim_proposal
    ALTER COLUMN question_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'routing_question_identity'
    ) THEN
        ALTER TABLE routing_proposal
            ADD CONSTRAINT routing_question_identity UNIQUE (id, question_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'resolution_route_answers_same_question'
    ) THEN
        ALTER TABLE resolution
            ADD CONSTRAINT resolution_route_answers_same_question FOREIGN KEY
                (routing_proposal_id, question_id)
                REFERENCES routing_proposal(id, question_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'claim_question_identity'
    ) THEN
        ALTER TABLE claim_proposal
            ADD CONSTRAINT claim_question_identity UNIQUE (id, question_id);
    END IF;
END $$;

CREATE OR REPLACE FUNCTION resolution_claim_dep_same_question() RETURNS trigger AS $$
DECLARE
    v_resolution_question text;
    v_claim_question text;
BEGIN
    SELECT question_id INTO v_resolution_question
      FROM resolution WHERE id = NEW.resolution_id;
    SELECT question_id INTO v_claim_question
      FROM claim_proposal WHERE id = NEW.claim_id;

    IF v_resolution_question IS DISTINCT FROM v_claim_question THEN
        RAISE EXCEPTION 'claim proposal % belongs to question %, not resolution question %',
                        NEW.claim_id, v_claim_question, v_resolution_question;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

DROP TRIGGER IF EXISTS resolution_claim_dep_same_question_trg ON resolution_claim_dep;
CREATE TRIGGER resolution_claim_dep_same_question_trg
    BEFORE INSERT ON resolution_claim_dep
    FOR EACH ROW EXECUTE FUNCTION resolution_claim_dep_same_question();

COMMIT;
