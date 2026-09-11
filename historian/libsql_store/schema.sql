PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS question(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), text TEXT NOT NULL, UNIQUE(id,text));
CREATE TABLE IF NOT EXISTS candidate(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), locator TEXT NOT NULL, quote TEXT NOT NULL,
 UNIQUE(id,locator,quote));
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), source_system TEXT NOT NULL, source_instance_id TEXT NOT NULL,
 record_id TEXT NOT NULL, version_hash TEXT NOT NULL, coordinate_system TEXT NOT NULL,
 coordinate_parts TEXT NOT NULL CHECK(json_valid(coordinate_parts)),
 content_hash TEXT NOT NULL, material_state TEXT NOT NULL, redaction_ref TEXT,
 locator TEXT NOT NULL CHECK(json_valid(locator)), quote TEXT NOT NULL, verified_by TEXT NOT NULL,
 candidate_id TEXT, FOREIGN KEY(candidate_id,locator,quote) REFERENCES candidate(id,locator,quote));
CREATE TABLE IF NOT EXISTS claim(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 question_id TEXT NOT NULL REFERENCES question(id), text TEXT NOT NULL, UNIQUE(id,question_id));
CREATE TABLE IF NOT EXISTS route(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), question_id TEXT NOT NULL REFERENCES question(id),
 frame TEXT NOT NULL, UNIQUE(id,question_id));
CREATE TABLE IF NOT EXISTS resolution(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), question_id TEXT NOT NULL REFERENCES question(id),
 conclusion TEXT NOT NULL, route_id TEXT, UNIQUE(id,question_id),
 FOREIGN KEY(route_id,question_id) REFERENCES route(id,question_id));
CREATE TABLE IF NOT EXISTS resolution_evidence(resolution_id TEXT NOT NULL REFERENCES resolution(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(resolution_id,evidence_id));
CREATE TABLE IF NOT EXISTS resolution_claim(resolution_id TEXT NOT NULL, question_id TEXT NOT NULL,
 claim_id TEXT NOT NULL, PRIMARY KEY(resolution_id,claim_id),
 FOREIGN KEY(resolution_id,question_id) REFERENCES resolution(id,question_id),
 FOREIGN KEY(claim_id,question_id) REFERENCES claim(id,question_id));
CREATE TABLE IF NOT EXISTS resolution_seal(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0) REFERENCES resolution(id));
CREATE VIEW IF NOT EXISTS published_resolution AS SELECT r.* FROM resolution r JOIN resolution_seal s ON s.id=r.id;
CREATE TABLE IF NOT EXISTS seed(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0),question_id TEXT NOT NULL,question_text TEXT NOT NULL,
 FOREIGN KEY(question_id,question_text) REFERENCES question(id,text));
CREATE TABLE IF NOT EXISTS seed_evidence(seed_id TEXT NOT NULL REFERENCES seed(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(seed_id,evidence_id));
CREATE TABLE IF NOT EXISTS seed_seal(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0) REFERENCES seed(id));
CREATE TABLE IF NOT EXISTS packet(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0),seed_id TEXT NOT NULL REFERENCES seed_seal(id));
CREATE TABLE IF NOT EXISTS packet_evidence(packet_id TEXT NOT NULL REFERENCES packet(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(packet_id,evidence_id));
CREATE TABLE IF NOT EXISTS packet_seal(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0) REFERENCES packet(id));
CREATE TABLE IF NOT EXISTS assertion(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), subject_id TEXT NOT NULL REFERENCES evidence(id),
 object_id TEXT NOT NULL REFERENCES evidence(id), origin TEXT NOT NULL
 CHECK(origin IN ('TYPED_SOURCE','HUMAN_REVIEWED_PROPOSAL')), writer TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS adjudication(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), packet_id TEXT NOT NULL REFERENCES packet_seal(id),
 human_id TEXT NOT NULL, verdict TEXT NOT NULL CHECK(verdict IN ('RESOLVED','UNRESOLVED','PACKET_INSUFFICIENT')),
 conclusion TEXT, CHECK(verdict!='RESOLVED' OR conclusion IS NOT NULL),
 CHECK(verdict!='PACKET_INSUFFICIENT' OR conclusion IS NULL));
CREATE TABLE IF NOT EXISTS gold(id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0),adjudication_id TEXT NOT NULL REFERENCES adjudication(id));
CREATE TRIGGER IF NOT EXISTS gold_eligible BEFORE INSERT ON gold
 WHEN (SELECT verdict FROM adjudication WHERE id=NEW.adjudication_id)='PACKET_INSUFFICIENT'
 BEGIN SELECT RAISE(ABORT,'ineligible adjudication'); END;
CREATE TRIGGER IF NOT EXISTS resolution_no_late_evidence BEFORE INSERT ON resolution_evidence
 WHEN EXISTS(SELECT 1 FROM resolution_seal WHERE id=NEW.resolution_id)
 BEGIN SELECT RAISE(ABORT,'published'); END;
CREATE TRIGGER IF NOT EXISTS resolution_no_late_claim BEFORE INSERT ON resolution_claim
 WHEN EXISTS(SELECT 1 FROM resolution_seal WHERE id=NEW.resolution_id)
 BEGIN SELECT RAISE(ABORT,'published'); END;
CREATE TRIGGER IF NOT EXISTS seed_no_late_evidence BEFORE INSERT ON seed_evidence
 WHEN EXISTS(SELECT 1 FROM seed_seal WHERE id=NEW.seed_id)
 BEGIN SELECT RAISE(ABORT,'sealed seed'); END;
CREATE TRIGGER IF NOT EXISTS seed_nonempty BEFORE INSERT ON seed_seal
 WHEN NOT EXISTS(SELECT 1 FROM seed_evidence WHERE seed_id=NEW.id)
 BEGIN SELECT RAISE(ABORT,'empty seed'); END;
CREATE TRIGGER IF NOT EXISTS packet_no_late_evidence BEFORE INSERT ON packet_evidence
 WHEN EXISTS(SELECT 1 FROM packet_seal WHERE id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'sealed packet'); END;
CREATE TRIGGER IF NOT EXISTS packet_matches_seed BEFORE INSERT ON packet_seal
 WHEN EXISTS(SELECT evidence_id FROM seed_evidence WHERE seed_id=(SELECT seed_id FROM packet WHERE id=NEW.id)
 EXCEPT SELECT evidence_id FROM packet_evidence WHERE packet_id=NEW.id)
 OR EXISTS(SELECT evidence_id FROM packet_evidence WHERE packet_id=NEW.id EXCEPT
 SELECT evidence_id FROM seed_evidence WHERE seed_id=(SELECT seed_id FROM packet WHERE id=NEW.id))
 BEGIN SELECT RAISE(ABORT,'packet differs from seed'); END;
