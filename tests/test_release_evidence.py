import copy
import runpy

import pytest
from historian.libsql_store.profile import CERTIFIED_RUNTIME, SQLITE
from historian.persistence.catalog import CATALOG

validate = runpy.run_path('scripts/prepare-release.py')['validate']


def report():
    identity = {'profile_name': SQLITE.name, 'profile_version': SQLITE.version,
                'profile_digest': SQLITE.digest, 'run_id': 'run'}
    return {**identity, 'contract_version': '1', 'status': 'CONFORMS',
            'runtime': dict(CERTIFIED_RUNTIME),
            'missing_properties': [],
            'evidence': [{**identity, 'test_id': t.id, 'status': 'CONFORMS'}
                         for i in CATALOG for t in i.conformance_tests]}


def test_release_gate_accepts_complete_matching_report():
    validate(report(), SQLITE, set())


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'digest', 'untested', 'properties',
                                    'runtime', 'no_runtime'])
def test_release_gate_rejects_incomplete_or_misbound_evidence(change):
    data = copy.deepcopy(report())
    if change == 'missing':
        data['evidence'].pop()
    elif change == 'duplicate':
        data['evidence'][0] = data['evidence'][1]
    elif change == 'digest':
        data['evidence'][0]['profile_digest'] = 'wrong'
    elif change == 'runtime':
        data['runtime'] = {**data['runtime'], 'sqlite': '3.53.1'}
    elif change == 'no_runtime':
        del data['runtime']
    elif change == 'untested':
        data['evidence'][0]['status'] = 'NOT_TESTED'
    else:
        data['missing_properties'] = [['PV17', ['authenticated_identity']]]
    with pytest.raises(AssertionError):
        validate(data, SQLITE, set())
