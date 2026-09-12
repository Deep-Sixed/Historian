CREATE TABLE app_object(
 kind TEXT NOT NULL, id TEXT NOT NULL CHECK(length(id)>0), question_id TEXT REFERENCES question(id),
 question_text TEXT, payload TEXT NOT NULL CHECK(json_valid(payload)), writer TEXT NOT NULL,
 PRIMARY KEY(kind,id), UNIQUE(kind,id,question_id),
 CHECK(json_extract(payload,'$.type') IS kind),
 CHECK(json_extract(payload,'$.fields.id') IS id),
 CHECK(kind NOT IN ('Question','ClaimProposal','RoutingProposal','Resolution','GoldCaseSeed') OR question_id IS NOT NULL),
 CHECK(json_extract(payload,'$.fields.question_id') IS NULL OR json_extract(payload,'$.fields.question_id')=question_id),
 FOREIGN KEY(question_id,question_text) REFERENCES question(id,text));
CREATE TABLE app_seal(kind TEXT NOT NULL,id TEXT NOT NULL,PRIMARY KEY(kind,id),
 FOREIGN KEY(kind,id) REFERENCES app_object(kind,id));
CREATE TABLE app_link(
 owner_kind TEXT NOT NULL,owner_id TEXT NOT NULL,relation TEXT NOT NULL,
 target_kind TEXT NOT NULL,target_id TEXT NOT NULL,question_id TEXT,
 PRIMARY KEY(owner_kind,owner_id,relation,target_kind,target_id),
 FOREIGN KEY(owner_kind,owner_id) REFERENCES app_object(kind,id),
 FOREIGN KEY(target_kind,target_id) REFERENCES app_seal(kind,id),
 FOREIGN KEY(owner_kind,owner_id,question_id) REFERENCES app_object(kind,id,question_id),
 FOREIGN KEY(target_kind,target_id,question_id) REFERENCES app_object(kind,id,question_id),
 CHECK(relation NOT IN ('claim_proposal_refs','routing_proposal_ref','previous_resolution_id','replacement_resolution_id') OR question_id IS NOT NULL),
 CHECK(CASE relation
 WHEN 'claim_proposal_refs' THEN target_kind='ClaimProposal'
 WHEN 'routing_proposal_ref' THEN target_kind='RoutingProposal'
 WHEN 'asserted_relation_refs' THEN target_kind='AssertedRelation'
 WHEN 'proposed_relation_refs' THEN target_kind='ProposedRelation'
 WHEN 'source_role_proposal_refs' THEN target_kind='SourceRoleProposal'
 ELSE 1 END));
CREATE TABLE app_evidence(
 owner_kind TEXT NOT NULL,owner_id TEXT NOT NULL,evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY(owner_kind,owner_id,evidence_id),FOREIGN KEY(owner_kind,owner_id) REFERENCES app_object(kind,id));
CREATE TRIGGER app_no_late_link BEFORE INSERT ON app_link
 WHEN EXISTS(SELECT 1 FROM app_seal WHERE kind=NEW.owner_kind AND id=NEW.owner_id)
 BEGIN SELECT RAISE(ABORT,'published'); END;
CREATE TRIGGER app_no_late_evidence BEFORE INSERT ON app_evidence
 WHEN EXISTS(SELECT 1 FROM app_seal WHERE kind=NEW.owner_kind AND id=NEW.owner_id)
 BEGIN SELECT RAISE(ABORT,'published'); END;
CREATE TRIGGER app_resolution_complete BEFORE INSERT ON app_seal WHEN NEW.kind='Resolution'
 BEGIN
 SELECT CASE WHEN EXISTS(
 SELECT value AS field FROM json_each('["claim_proposal_refs","asserted_relation_refs","proposed_relation_refs","source_role_proposal_refs"]')
 WHERE (SELECT count(*) FROM app_link WHERE owner_kind=NEW.kind AND owner_id=NEW.id AND relation=field)
 != json_array_length((SELECT payload FROM app_object WHERE kind=NEW.kind AND id=NEW.id),'$.fields.'||field))
 THEN RAISE(ABORT,'incomplete resolution dependencies') END;
 END;
CREATE VIEW app_resolution_support AS
 SELECT o.id,CASE
 WHEN EXISTS(SELECT 1 FROM app_link WHERE owner_kind=o.kind AND owner_id=o.id AND relation IN ('claim_proposal_refs','proposed_relation_refs','source_role_proposal_refs'))
 THEN CASE WHEN EXISTS(SELECT 1 FROM app_link WHERE owner_kind=o.kind AND owner_id=o.id AND relation='asserted_relation_refs') THEN 'MIXED' ELSE 'PROPOSED_DEPENDENT' END
 ELSE CASE WHEN EXISTS(SELECT 1 FROM app_link WHERE owner_kind=o.kind AND owner_id=o.id AND relation='asserted_relation_refs') THEN 'ASSERTED_RELATION_DEPENDENT' ELSE 'DIRECT_EVIDENCE_ONLY' END END AS support_profile
 FROM app_object o JOIN app_seal s ON s.kind=o.kind AND s.id=o.id WHERE o.kind='Resolution';

CREATE TRIGGER app_complete_links BEFORE INSERT ON app_seal BEGIN
 SELECT CASE WHEN EXISTS(
 SELECT 1 FROM app_object o,json_each(o.payload,'$.fields') f,json_each('{"taxonomy_version":"FrameTaxonomy","proposal_id":"ProposedRelation","superseded_by_proposal_id":"ProposedRelation","derived_from_proposal_id":"ProposedRelation","asserted_relation_id":"AssertedRelation","replacement_assertion_id":"AssertedRelation","resolution_id":"Resolution","replacement_resolution_id":"Resolution","previous_resolution_id":"Resolution","asserted_relation_refs":"AssertedRelation","proposed_relation_refs":"ProposedRelation","claim_proposal_refs":"ClaimProposal","source_role_proposal_refs":"SourceRoleProposal","routing_proposal_ref":"RoutingProposal","seed_id":"GoldCaseSeed","packet_id":"AdjudicationPacket","adjudication_id":"BlindAdjudication"}') mapping
 WHERE o.kind=NEW.kind AND o.id=NEW.id AND f.key=mapping.key AND (
 (SELECT count(*) FROM app_link WHERE owner_kind=NEW.kind AND owner_id=NEW.id AND relation=f.key)
 != CASE WHEN f.type='array' THEN json_array_length(f.value) WHEN f.type='null' THEN 0 ELSE 1 END
 OR EXISTS(SELECT 1 FROM json_each(CASE WHEN f.type='array' THEN f.value ELSE json_array(f.value) END) expected
 WHERE expected.value IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app_link
 WHERE owner_kind=NEW.kind AND owner_id=NEW.id AND relation=f.key AND target_kind=mapping.value AND target_id=expected.value))))
 THEN RAISE(ABORT,'incomplete domain lineage') END;
 SELECT CASE WHEN EXISTS(SELECT value FROM json_tree((SELECT payload FROM app_object WHERE kind=NEW.kind AND id=NEW.id))
 WHERE key='evidence_id' EXCEPT SELECT evidence_id FROM app_evidence WHERE owner_kind=NEW.kind AND owner_id=NEW.id)
 THEN RAISE(ABORT,'incomplete evidence dependencies') END;
 END;
CREATE TRIGGER app_base_bindings BEFORE INSERT ON app_seal BEGIN
 SELECT CASE WHEN NEW.kind='AssertedRelation' AND NOT EXISTS(SELECT 1 FROM assertion a,app_object o
 WHERE a.id=NEW.id AND o.kind=NEW.kind AND o.id=NEW.id
 AND a.origin=json_extract(o.payload,'$.fields.origin.value')
 AND a.subject_id=json_extract(o.payload,'$.fields.subject_ref.fields.evidence_id')
 AND a.object_id=json_extract(o.payload,'$.fields.object_ref.fields.evidence_id'))
 THEN RAISE(ABORT,'assertion storage binding') END;
 SELECT CASE WHEN NEW.kind='BlindAdjudication' AND NOT EXISTS(SELECT 1 FROM adjudication a,app_object o
 WHERE a.id=NEW.id AND o.kind=NEW.kind AND o.id=NEW.id
 AND a.packet_id=json_extract(o.payload,'$.fields.packet_id')
 AND a.human_id=json_extract(o.payload,'$.fields.adjudicator_id')
 AND a.verdict=json_extract(o.payload,'$.fields.verdict.value')
 AND a.conclusion IS json_extract(o.payload,'$.fields.resolution_text'))
 THEN RAISE(ABORT,'adjudication storage binding') END;
 SELECT CASE WHEN NEW.kind='EvaluationGold' AND NOT EXISTS(SELECT 1 FROM gold g
 JOIN adjudication a ON a.id=g.adjudication_id JOIN packet p ON p.id=a.packet_id,app_object o
 WHERE g.id=NEW.id AND o.kind=NEW.kind AND o.id=NEW.id
 AND a.id=json_extract(o.payload,'$.fields.adjudication_id')
 AND p.seed_id=json_extract(o.payload,'$.fields.seed_id')
 AND a.verdict=json_extract(o.payload,'$.fields.expected_outcome.value')
 AND a.conclusion IS json_extract(o.payload,'$.fields.expected_resolution'))
 THEN RAISE(ABORT,'gold storage binding') END;
 END;
CREATE TABLE app_snapshot(
 packet_id TEXT NOT NULL REFERENCES packet(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 ordinal INTEGER NOT NULL CHECK(ordinal>=0), snapshot_text TEXT NOT NULL,
 PRIMARY KEY(packet_id,evidence_id), UNIQUE(packet_id,ordinal),
 FOREIGN KEY(packet_id,evidence_id) REFERENCES packet_evidence(packet_id,evidence_id));
CREATE TRIGGER app_no_late_snapshot BEFORE INSERT ON app_snapshot
 WHEN EXISTS(SELECT 1 FROM app_seal WHERE kind='AdjudicationPacket' AND id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'published'); END;
CREATE TRIGGER app_packet_snapshot_complete BEFORE INSERT ON app_seal
 WHEN NEW.kind='AdjudicationPacket'
 BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM app_snapshot WHERE packet_id=NEW.id)
 != (SELECT count(*) FROM packet_evidence WHERE packet_id=NEW.id)
 THEN RAISE(ABORT,'incomplete packet snapshot') END;
 END;
CREATE TABLE candidate_intake(
 candidate_id TEXT PRIMARY KEY NOT NULL REFERENCES candidate(id),
 extractor_id TEXT, extraction_run_id TEXT, writer TEXT NOT NULL);
