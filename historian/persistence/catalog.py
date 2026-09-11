"""Mandatory product guarantees; probe scenarios are shared by every backend."""
from .contract import Access as A
from .contract import Boundary as B
from .contract import BoundaryTest, PersistenceInvariant

# Explicit proof obligations, not inferred from an invariant's property list. A successful
# happy-path insert alone does not establish uniqueness, immutability or access isolation.
PROBE_PROPERTIES = {
    'PV01': {'normal': ('referential_integrity',), 'bypass': ('referential_integrity',)},
    'PV02': {'normal': ('referential_integrity',), 'bypass': ('referential_integrity',)},
    'PV03': {'normal': ('referential_integrity',), 'bypass': ('referential_integrity',)},
    'PV04': {'normal': (), 'duplicate': ('durable_uniqueness',)},
    'PV05': {'normal': ('atomicity',), 'bypass': ('immutability',)},
    'PV06': {'normal': ('immutability',), 'bypass': ('tamper_resistance',)},
    'PV07': {'normal': ('authenticated_identity',), 'bypass': ('authenticated_identity',)},
    'PV08': {'normal': (), 'negative': ('capability_isolation',),
             'bypass': ('capability_isolation',), 'anonymous': ('authenticated_identity',)},
    'PV09': {'normal': ('referential_integrity',), 'bypass': ('referential_integrity',)},
    'PV10': {'delete': ('tamper_resistance',), 'truncate': ('immutability',)},
    'PV11': {'normal': ('referential_integrity',), 'integrity': ('durable_uniqueness',)},
    'PV12': {'normal': ('referential_integrity',), 'integrity': ('referential_integrity',)},
    'PV13': {'commit': ('atomicity',), 'rollback': ('atomicity',), 'visibility': ('atomicity',)},
    'PV14': {'normal': (), 'bypass': ('capability_isolation',)},
    'PV15': {'normal': ('immutability',), 'bypass': ('capability_isolation',)},
    'PV16': {'normal': ('source_integrity',), 'negative': ('source_integrity',)},
    'PV17': {'normal': ('authenticated_identity',), 'bypass': ('capability_isolation',)},
    'PV18': {'normal': ('referential_integrity',), 'bypass': ('capability_isolation',)},
    'PV19': {'normal': ('referential_integrity',), 'bypass': ('referential_integrity',)},
    'PV20': {'normal': ('authenticated_identity',), 'bypass': ('authenticated_identity',)},
}


def invariant(key, description, properties, probes, boundaries=(B.DATABASE,)):
    return PersistenceInvariant(
        key, description, boundaries, tuple(properties.split(',')),
        ('Input validation may reject earlier; it is not boundary proof.',),
        'Reject without publishing a partial or falsely attributed durable artifact; '
        'retain prior committed history. Unavailable proof is NOT_TESTED.',
        tuple(BoundaryTest(f'{key}.{suffix}', key, access, scenario, expected,
                           PROBE_PROPERTIES[key][suffix])
              for suffix, access, scenario, expected in probes))


CATALOG = (
    invariant('PV01', 'A frozen question cannot be restated by downstream provenance.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'seed_same_question', 'accepted'),
                  ('bypass', A.BYPASS, 'seed_different_text', 'rejected')]),
    invariant('PV02', 'Claims and resolution claim dependencies belong to the same question.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'claim_same_question', 'accepted'),
                  ('bypass', A.BYPASS, 'claim_cross_question', 'rejected')]),
    invariant('PV03', 'Routing and its resolution belong to the same question.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'route_same_question', 'accepted'),
                  ('bypass', A.BYPASS, 'route_cross_question', 'rejected')]),
    invariant('PV04', 'Durable artifact identities cannot be reused or overwritten.',
              'durable_uniqueness', [
                  ('normal', A.NORMAL, 'new_identity', 'accepted'),
                  ('duplicate', A.TRANSACTION, 'duplicate_identity', 'rejected')]),
    invariant('PV05', 'Published resolutions include an immutable complete dependency set.',
              'atomicity,immutability', [
                  ('normal', A.NORMAL, 'resolution_complete', 'accepted'),
                  ('bypass', A.BYPASS, 'append_published_dependency', 'rejected')]),
    invariant('PV06', 'Committed evidence is append-only; revisions use new identities.',
              'immutability,tamper_resistance', [
                  ('normal', A.NORMAL, 'new_evidence_version', 'accepted'),
                  ('bypass', A.BYPASS, 'update_evidence', 'rejected')],
              (B.DATABASE, B.TRUSTED_SERVICE, B.APPROVED_ALTERNATIVE)),
    invariant('PV07', 'Verifier identity is authenticated and cannot be supplied by a caller.',
              'authenticated_identity', [
                  ('normal', A.NORMAL, 'verifier_identity', 'authenticated'),
                  ('bypass', A.BYPASS, 'forged_verifier_identity', 'authenticated')],
              (B.DATABASE, B.TRUSTED_SERVICE)),
    invariant('PV08', 'Specialized writers cannot assume or invoke another capability.',
              'capability_isolation,authenticated_identity', [
                  ('normal', A.NORMAL, 'extractor_candidate', 'accepted'),
                  ('negative', A.UNAUTHORIZED, 'extractor_evidence', 'rejected'),
                  ('bypass', A.BYPASS, 'extractor_assume_verifier', 'rejected'),
                  ('anonymous', A.BYPASS, 'unauthenticated_connection', 'rejected')],
              (B.DATABASE, B.TRUSTED_SERVICE)),
    invariant('PV09', 'Every persisted adjudication dependency refers to an existing artifact.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'existing_dependency', 'accepted'),
                  ('bypass', A.BYPASS, 'missing_dependency', 'rejected')]),
    invariant('PV10', 'Application identities cannot delete or truncate committed evidence.',
              'tamper_resistance,immutability', [
                  ('delete', A.BYPASS, 'delete_evidence', 'rejected'),
                  ('truncate', A.BYPASS, 'truncate_evidence', 'rejected')]),
    invariant('PV11', 'EvidenceLocator round-trips open-ended source and version identity.',
              'referential_integrity,durable_uniqueness', [
                  ('normal', A.NORMAL, 'locator_roundtrip', 'lossless'),
                  ('integrity', A.TRANSACTION, 'locator_instance_collision', 'distinct')]),
    invariant('PV12', 'Coordinates preserve canonical named parts without LINE coercion.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'coordinate_roundtrip', 'lossless'),
                  ('integrity', A.TRANSACTION, 'coordinate_distinction', 'distinct')]),
    invariant('PV13', 'Failed multi-record publication rolls back; partial writes stay invisible.',
              'atomicity', [
                  ('commit', A.TRANSACTION, 'transaction_commit', 'complete'),
                  ('rollback', A.TRANSACTION, 'transaction_rollback', 'absent'),
                  ('visibility', A.TRANSACTION, 'transaction_visibility', 'absent')]),
    invariant('PV14', 'Blind adjudicators cannot read proposals or internal seed metadata.',
              'capability_isolation', [
                  ('normal', A.NORMAL, 'blind_view', 'accepted'),
                  ('bypass', A.BYPASS, 'blind_read_proposals', 'rejected')],
              (B.DATABASE, B.TRUSTED_SERVICE)),
    invariant('PV15', 'Only validated, frozen seed/packet aggregates may reach adjudication.',
              'immutability,capability_isolation', [
                  ('normal', A.NORMAL, 'finalized_packet', 'accepted'),
                  ('bypass', A.BYPASS, 'forge_finalization', 'rejected')]),
    invariant('PV16', 'Verified evidence is checked against the declared source and version.',
              'source_integrity', [
                  ('normal', A.NORMAL, 'source_verified', 'accepted'),
                  ('negative', A.UNAUTHORIZED, 'source_mismatch', 'rejected')],
              (B.TRUSTED_SERVICE,)),
    invariant('PV17', 'Assertion origin must match the authenticated writer capability.',
              'authenticated_identity,capability_isolation', [
                  ('normal', A.NORMAL, 'typed_assertion', 'accepted'),
                  ('bypass', A.BYPASS, 'typed_forge_human', 'rejected')]),
    invariant('PV18', 'Gold must descend from an eligible adjudication, never packet insufficiency.',
              'referential_integrity,capability_isolation', [
                  ('normal', A.NORMAL, 'eligible_gold', 'accepted'),
                  ('bypass', A.BYPASS, 'insufficient_gold', 'rejected')]),
    invariant('PV19', 'Verified evidence preserves the candidate locator and anchor it cites.',
              'referential_integrity', [
                  ('normal', A.NORMAL, 'candidate_binding', 'accepted'),
                  ('bypass', A.BYPASS, 'candidate_crosswire', 'rejected')]),
    invariant('PV20', 'Human adjudication attribution comes from the authenticated principal.',
              'authenticated_identity', [
                  ('normal', A.NORMAL, 'human_identity', 'authenticated'),
                  ('bypass', A.BYPASS, 'forged_human_identity', 'authenticated')],
              (B.DATABASE, B.TRUSTED_SERVICE)),

)
