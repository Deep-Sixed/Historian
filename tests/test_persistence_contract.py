import json
from dataclasses import replace

import pytest

from historian.persistence.catalog import CATALOG
from historian.persistence.contract import (
    Boundary,
    ConformanceHarness,
    Observation,
    Status,
)
from historian.persistence.locator import locator_from_record, locator_to_record
from historian.persistence.profiles import POSTGRESQL
from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceMaterialState,
)


class StubProbe:
    """Harness unit-test double, never PostgreSQL conformance evidence."""
    def execute(self, test):
        inv = next(i for i in CATALOG if i.id == test.invariant_id)
        return Observation(test.expected, inv.permitted_boundaries[0], 'unit test only')


def test_complete_evidence_is_bound_to_exact_profile_and_run():
    report = ConformanceHarness(CATALOG).run(POSTGRESQL, StubProbe())
    assert report.status is Status.CONFORMS
    assert len(report.evidence) == sum(len(i.conformance_tests) for i in CATALOG)
    assert all((e.profile_name, e.profile_version, e.run_id) ==
               (POSTGRESQL.name, POSTGRESQL.version, report.run_id) for e in report.evidence)
    assert report.contract_version == '1'


@pytest.mark.parametrize('mode,expected', [
    ('missing', Status.NOT_TESTED), ('failure', Status.DOES_NOT_CONFORM),
    ('wrong_boundary', Status.DOES_NOT_CONFORM),
])
def test_one_missing_or_bad_probe_prevents_conformance(mode, expected):
    class Probe(StubProbe):
        def execute(self, test):
            if test.id != 'PV02.bypass':
                return super().execute(test)
            if mode == 'missing':
                raise NotImplementedError('sensitive connection details must not leak')
            if mode == 'wrong_boundary':
                return Observation(test.expected, Boundary.TRUSTED_SERVICE, 'wrong boundary')
            return Observation('accepted', Boundary.DATABASE, 'unauthorized write succeeded')
    report = ConformanceHarness(CATALOG).run(POSTGRESQL, Probe())
    assert report.status is expected
    assert 'sensitive' not in repr(report)


def test_empty_claimed_coverage_does_not_skip_any_invariants():
    report = ConformanceHarness(CATALOG).run(
        replace(POSTGRESQL, claimed_invariant_coverage=()), StubProbe())
    assert {e.invariant_id for e in report.evidence} == {i.id for i in CATALOG}


def test_failure_takes_precedence_over_unavailable_proof():
    class Probe(StubProbe):
        def execute(self, test):
            if test.id == 'PV02.bypass':
                return Observation('accepted', Boundary.DATABASE, 'violation')
            raise NotImplementedError
    assert ConformanceHarness(CATALOG).run(POSTGRESQL, Probe()).status is Status.DOES_NOT_CONFORM


def test_profile_version_is_not_engine_wide():
    changed = replace(POSTGRESQL, version=2)
    assert ConformanceHarness(CATALOG).run(changed, StubProbe()).profile_version == 2
    with pytest.raises(ValueError):
        replace(POSTGRESQL, version=0)


def test_catalog_cannot_silently_drop_proof_or_crosswire_tests():
    with pytest.raises(ValueError):
        ConformanceHarness(())
    with pytest.raises(ValueError):
        ConformanceHarness((CATALOG[0], CATALOG[0]))
    with pytest.raises(ValueError):
        ConformanceHarness((replace(CATALOG[0], conformance_tests=()),))
    with pytest.raises(ValueError):
        ConformanceHarness((replace(CATALOG[0], conformance_tests=CATALOG[1].conformance_tests),))


@pytest.mark.parametrize('system,parts', [
    ('JSON_POINTER', (CoordinatePart('path', '/tweet/full_text'),)),
    ('BYTE_RANGE', (CoordinatePart('start', '0'), CoordinatePart('end', '42'))),
    ('FUTURE_COORDINATE', (CoordinatePart('unicode', 'é/雪'), CoordinatePart('empty', ''))),
])
def test_locator_wire_roundtrip_preserves_open_ended_provenance(system, parts):
    locator = EvidenceLocator('FUTURE_SOURCE', 'account-1', 'record-1', 'a' * 64,
                              SourceCoordinate(system, parts), 'b' * 64,
                              SourceMaterialState.REDACTED, 'redaction-1')
    wire = json.loads(json.dumps(locator_to_record(locator)))
    assert locator_from_record(wire) == locator
    assert [p['name'] for p in wire['coordinate_parts']] == sorted(p.name for p in parts)
    assert locator_from_record({**wire, 'source_instance_id': 'account-2'}) != locator


def test_duplicate_coordinate_names_fail_closed():
    with pytest.raises(ValueError):
        SourceCoordinate('future', (CoordinatePart('a', '1'), CoordinatePart('a', '2')))
