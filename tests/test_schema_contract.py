from pathlib import Path


SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "01-schema.sql"


def test_schema_binds_resolution_routes_to_the_same_question():
    sql = SCHEMA.read_text()
    assert "CONSTRAINT routing_question_identity UNIQUE (id, question_id)" in sql
    assert "CONSTRAINT resolution_route_answers_same_question FOREIGN KEY" in sql
    assert "(routing_proposal_id, question_id)" in sql
    assert "REFERENCES routing_proposal(id, question_id)" in sql


def test_schema_binds_resolution_claims_to_the_same_question():
    sql = SCHEMA.read_text()
    assert "question_id  text NOT NULL REFERENCES question(id)" in sql
    assert "CONSTRAINT claim_question_identity UNIQUE (id, question_id)" in sql
    assert "CREATE FUNCTION resolution_claim_dep_same_question()" in sql
    assert "CREATE TRIGGER resolution_claim_dep_same_question_trg" in sql
