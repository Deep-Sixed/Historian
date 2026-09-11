"""Persistence v1: guarantees and evidence, independent of backend mechanisms."""
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol
from uuid import uuid4


class Boundary(Enum):
    DATABASE = 'database'
    TRUSTED_SERVICE = 'trusted_service'
    APPROVED_ALTERNATIVE = 'approved_alternative'


class Access(Enum):
    NORMAL = 'normal_authorized'
    UNAUTHORIZED = 'unauthorized_interface'
    BYPASS = 'direct_bypass'
    TRANSACTION = 'transaction_integrity'


class Status(Enum):
    CONFORMS = 'CONFORMS'
    DOES_NOT_CONFORM = 'DOES_NOT_CONFORM'
    NOT_TESTED = 'NOT_TESTED'


@dataclass(frozen=True)
class BoundaryTest:
    id: str
    invariant_id: str
    access: Access
    scenario: str
    expected: str
    proves_properties: tuple[str, ...]


@dataclass(frozen=True)
class PersistenceInvariant:
    id: str
    description: str
    permitted_boundaries: tuple[Boundary, ...]
    required_boundary_properties: tuple[str, ...]
    defense_in_depth: tuple[str, ...]
    failure_semantics: str
    conformance_tests: tuple[BoundaryTest, ...]


@dataclass(frozen=True)
class ThreatModel:
    actors: tuple[tuple[str, str], ...]
    access_assumptions: tuple[str, ...]
    excluded_threats: tuple[str, ...]


@dataclass(frozen=True)
class PersistenceProfile:
    name: str
    version: int
    backend_family: str
    deployment_model: str
    credential_access_model: str
    trusted_boundaries: tuple[Boundary, ...]
    excluded_untrusted_boundaries: tuple[str, ...]
    claimed_invariant_coverage: tuple[str, ...]
    threat_model: ThreatModel

    def __post_init__(self):
        if not self.name or type(self.version) is not int or self.version < 1:
            raise ValueError('exact profile name and positive version required')

    @property
    def digest(self) -> str:
        """Canonical UTF-8 JSON: sorted object keys, preserved sequence order, enum values.

        Every profile field, including the complete threat model, participates. No secret
        values belong in a profile. Sequence reordering deliberately changes the digest.
        """
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, default=lambda value: value.value)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Observation:
    observed: str
    boundary: Boundary
    detail: str
    access: Access | None
    actor: str
    capability_class: str
    tested: bool = True


@dataclass(frozen=True)
class ConformanceEvidence:
    invariant_id: str
    profile_name: str
    profile_version: int
    profile_digest: str
    test_id: str
    expected: str
    observed: str
    boundary: Boundary
    access: Access | None
    expected_access: Access
    actor: str
    capability_class: str
    proves_properties: tuple[str, ...]
    status: Status
    detail: str
    run_id: str


@dataclass(frozen=True)
class ConformanceResult:
    profile_name: str
    profile_version: int
    backend_family: str
    profile_digest: str
    status: Status
    evidence: tuple[ConformanceEvidence, ...]
    run_id: str
    missing_properties: tuple[tuple[str, tuple[str, ...]], ...]
    contract_version: str = '1'


class BackendProbe(Protocol):
    """The implementation must exercise the described boundary, not inspect config only.

    It owns disposable fixtures, authenticated connections and observations. It cannot
    choose expectations, omit required tests or award itself a conformance status.
    """
    def execute(self, test: BoundaryTest) -> Observation: ...


class ConformanceHarness:
    def __init__(self, catalog: tuple[PersistenceInvariant, ...]):
        ids = [i.id for i in catalog]
        tests = [t.id for i in catalog for t in i.conformance_tests]
        if not ids or len(set(ids)) != len(ids) or len(set(tests)) != len(tests):
            raise ValueError('nonempty catalog and unique invariant/test identities required')
        for invariant in catalog:
            if not invariant.conformance_tests or not invariant.permitted_boundaries:
                raise ValueError('every invariant requires probes and permitted boundaries')
            if any(t.invariant_id != invariant.id for t in invariant.conformance_tests):
                raise ValueError('cross-wired test invariant')
        self.catalog = catalog

    def run(self, profile: PersistenceProfile, adapter: BackendProbe) -> ConformanceResult:
        known = {i.id for i in self.catalog}
        if set(profile.claimed_invariant_coverage) - known:
            raise ValueError('profile claims unknown invariants')
        run_id = uuid4().hex
        evidence = []
        missing_properties = []
        digest = profile.digest
        # Coverage claims do not reduce the mandatory catalog.
        for invariant in self.catalog:
            proven = set()
            for test in invariant.conformance_tests:
                try:
                    obs = adapter.execute(test)
                except Exception as exc:  # noqa: BLE001 - unavailable probes cannot earn conformance
                    # Do not serialize connection strings, source payloads or exception text.
                    obs = Observation('', invariant.permitted_boundaries[0],
                                      f'probe unavailable: {type(exc).__name__}',
                                      access=None, actor='', capability_class='', tested=False)
                if not obs.tested:
                    status = Status.NOT_TESTED
                elif (obs.boundary not in invariant.permitted_boundaries
                      or obs.boundary not in profile.trusted_boundaries
                      or obs.observed != test.expected
                      or obs.access is not test.access
                      or not obs.actor.strip() or not obs.capability_class.strip()):
                    status = Status.DOES_NOT_CONFORM
                else:
                    status = Status.CONFORMS
                properties = test.proves_properties if status is Status.CONFORMS else ()
                proven.update(properties)
                evidence.append(ConformanceEvidence(
                    invariant_id=invariant.id, profile_name=profile.name,
                    profile_version=profile.version, profile_digest=digest,
                    test_id=test.id, expected=test.expected, observed=obs.observed,
                    boundary=obs.boundary, access=obs.access, expected_access=test.access,
                    actor=obs.actor, capability_class=obs.capability_class,
                    proves_properties=properties, status=status, detail=obs.detail, run_id=run_id))
            missing = set(invariant.required_boundary_properties) - proven
            if missing:
                missing_properties.append((invariant.id, tuple(sorted(missing))))
        states = {e.status for e in evidence}
        status = (Status.DOES_NOT_CONFORM if Status.DOES_NOT_CONFORM in states else
                  Status.NOT_TESTED if Status.NOT_TESTED in states or missing_properties
                  else Status.CONFORMS)
        return ConformanceResult(profile.name, profile.version, profile.backend_family,
                                 digest, status, tuple(evidence), run_id, tuple(missing_properties))
