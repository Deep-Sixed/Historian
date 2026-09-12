import json
from dataclasses import asdict, replace

import pytest

from historian.persistence.catalog import CATALOG
from historian.persistence.contract import (
    Access,
    Boundary,
    ConformanceHarness,
    Observation,
    Status,
)
from historian.persistence.locator import locator_from_record, locator_to_record
from historian.libsql_store.profile import LIBSQL as PROFILE
from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceMaterialState,
)


class StubProbe:
    """Harness unit-test double, never deployment conformance evidence."""
    def execute(self, test):
        inv = next(i for i in CATALOG if i.id == test.invariant_id)
        return Observation(test.expected, inv.permitted_boundaries[0], 'unit test only',
                           test.access, 'unit-principal', 'unit-capability')


def test_complete_evidence_is_bound_to_exact_profile_and_run():
    report = ConformanceHarness(CATALOG).run(PROFILE, StubProbe())
    assert report.status is Status.CONFORMS
    assert len(report.evidence) == sum(len(i.conformance_tests) for i in CATALOG)
    assert all((e.profile_name, e.profile_version, e.run_id) ==
               (PROFILE.name, PROFILE.version, report.run_id) for e in report.evidence)
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
                return replace(super().execute(test), boundary=Boundary.TRUSTED_SERVICE)
            return replace(super().execute(test), observed='accepted')
    report = ConformanceHarness(CATALOG).run(PROFILE, Probe())
    assert report.status is expected
    assert 'sensitive' not in repr(report)


def test_empty_claimed_coverage_does_not_skip_any_invariants():
    report = ConformanceHarness(CATALOG).run(
        replace(PROFILE, claimed_invariant_coverage=()), StubProbe())
    assert {e.invariant_id for e in report.evidence} == {i.id for i in CATALOG}


def test_failure_takes_precedence_over_unavailable_proof():
    class Probe(StubProbe):
        def execute(self, test):
            if test.id == 'PV02.bypass':
                return replace(super().execute(test), observed='accepted')
            raise NotImplementedError
    assert ConformanceHarness(CATALOG).run(PROFILE, Probe()).status is Status.DOES_NOT_CONFORM


def test_profile_version_is_not_engine_wide():
    changed = replace(PROFILE, version=2)
    assert ConformanceHarness(CATALOG).run(changed, StubProbe()).profile_version == 2
    with pytest.raises(ValueError):
        replace(PROFILE, version=0)


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


@pytest.mark.parametrize('field,value', [
    ('access', Access.NORMAL), ('actor', ''), ('capability_class', ''),
])
def test_bypass_requires_observed_path_and_principal(field, value):
    class Probe(StubProbe):
        def execute(self, test):
            obs = super().execute(test)
            return replace(obs, **{field: value}) if test.id == 'PV08.bypass' else obs
    report = ConformanceHarness(CATALOG).run(PROFILE, Probe())
    assert report.status is Status.DOES_NOT_CONFORM
    evidence = next(e for e in report.evidence if e.test_id == 'PV08.bypass')
    assert evidence.expected_access is Access.BYPASS
    assert getattr(evidence, field) == value  # never label the actual path from the request
    assert evidence.proves_properties == ()


def test_required_property_without_a_proving_test_is_not_tested():
    catalog = (replace(CATALOG[0], required_boundary_properties=(
        *CATALOG[0].required_boundary_properties, 'new_security_property')), *CATALOG[1:])
    report = ConformanceHarness(catalog).run(PROFILE, StubProbe())
    assert report.status is Status.NOT_TESTED
    assert report.missing_properties == (('PV01', ('new_security_property',)),)


def test_proof_declarations_are_required_even_when_all_results_match():
    weakened = replace(CATALOG[0], conformance_tests=tuple(
        replace(t, proves_properties=()) for t in CATALOG[0].conformance_tests))
    report = ConformanceHarness((weakened, *CATALOG[1:])).run(PROFILE, StubProbe())
    assert report.status is Status.NOT_TESTED
    assert report.missing_properties == (('PV01', ('referential_integrity',)),)


def test_failed_probe_does_not_contribute_property_coverage():
    class Probe(StubProbe):
        def execute(self, test):
            obs = super().execute(test)
            return replace(obs, observed='accepted') if test.id == 'PV04.duplicate' else obs
    report = ConformanceHarness(CATALOG).run(PROFILE, Probe())
    assert report.status is Status.DOES_NOT_CONFORM
    assert ('PV04', ('durable_uniqueness',)) in report.missing_properties


@pytest.mark.parametrize('change', [
    {'credential_access_model': 'shared unrestricted credential'},
    {'deployment_model': 'different deployment'},
    {'trusted_boundaries': (Boundary.DATABASE,)},
    {'excluded_untrusted_boundaries': ('different exclusion',)},
    {'claimed_invariant_coverage': ()},
    {'backend_family': 'different backend'},
    {'threat_model': replace(PROFILE.threat_model, access_assumptions=('different access',))},
    {'threat_model': replace(PROFILE.threat_model, actors=(('caller', 'owner access'),))},
    {'threat_model': replace(PROFILE.threat_model, excluded_threats=('different threat',))},
])
def test_same_profile_version_cannot_reuse_a_changed_definition_digest(change):
    altered = replace(PROFILE, **change)
    assert (altered.name, altered.version) == (PROFILE.name, PROFILE.version)
    assert altered.digest != PROFILE.digest
    report = ConformanceHarness(CATALOG).run(altered, StubProbe())
    assert report.profile_digest == altered.digest
    assert all(e.profile_digest == altered.digest for e in report.evidence)


def test_digest_is_stable_and_present_in_serialized_result_and_evidence():
    assert replace(PROFILE).digest == PROFILE.digest
    assert len(PROFILE.digest) == 64
    report = ConformanceHarness(CATALOG).run(PROFILE, StubProbe())
    artifact = json.loads(json.dumps(asdict(report), default=lambda v: v.value))
    assert artifact['profile_digest'] == PROFILE.digest
    assert all(e['profile_digest'] == PROFILE.digest for e in artifact['evidence'])
