"""Validate downloaded current-commit CI evidence before release publication."""
import argparse
import hashlib
import json
from pathlib import Path

from historian.sqlite_store.profile import SQLITE
from historian.persistence.catalog import CATALOG


def validate(report, profile, failures):
    expected = {t.id for invariant in CATALOG for t in invariant.conformance_tests}
    assert report['profile_name'] == profile.name
    assert report['profile_version'] == profile.version
    assert report['profile_digest'] == profile.digest
    assert report['contract_version'] == '1'
    rows = report['evidence']
    assert len(rows) == len(expected) == 43
    assert {row['test_id'] for row in rows} == expected
    for row in rows:
        assert row['profile_name'] == profile.name
        assert row['profile_version'] == profile.version
        assert row['profile_digest'] == profile.digest
        assert row['run_id'] == report['run_id']
        assert row['status'] == ('DOES_NOT_CONFORM' if row['test_id'] in failures else 'CONFORMS')
    assert report['status'] == ('DOES_NOT_CONFORM' if failures else 'CONFORMS')
    if not failures:
        assert not report['missing_properties']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--workflow-run', required=True)
    args = parser.parse_args()
    root = args.directory
    validate(json.loads((root/'historian-sqlite-conformance.json').read_text()), SQLITE, set())
    boundary = json.loads((root/'historian-sqlite-boundaries.json').read_text())
    assert boundary['profile_name'] == SQLITE.name and boundary['profile_version'] == SQLITE.version
    assert boundary['profile_digest'] == SQLITE.digest
    assert len(boundary['evidence']) == 124
    assert all(row['expected'] == row['observed'] for row in boundary['evidence'])
    from historian.sqlite_store.access import READ, WRITE
    roles = {"extractor","verifier","designer","typed","reviewer","runtime","builder","adjudicator","gold"}
    app = json.loads((root/'historian-sqlite-application.json').read_text())
    assert (app['profile_name'],app['profile_version'],app['profile_digest']) == (SQLITE.name,SQLITE.version,SQLITE.digest)
    expected = {(op,kind,role) for op,mapping in [('get_object',READ),('put_object',WRITE),('get_packet_snapshot',{'AdjudicationPacket':READ['AdjudicationPacket']})]
                for kind,allowed in mapping.items() for role in [*roles,'unassigned'] if role not in allowed}
    assert len(app['evidence']) == len(expected)
    assert {(e['operation'],e['kind'],e['capability']) for e in app['evidence']} == expected
    assert all(e['observed'] == e['expected'] == 'forbidden' for e in app['evidence'])
    manifest = {'commit': args.commit, 'workflow_run': args.workflow_run,
                'sqlite_profile': SQLITE.name, 'profile_version': SQLITE.version,
                'profile_digest': SQLITE.digest, 'status': 'CONFORMS'}
    (root/'release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    paths = sorted(p for p in root.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    assert any(p.suffix == '.whl' for p in paths)
    assert any(p.name.endswith('.tar.gz') for p in paths)
    (root/'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in paths))


if __name__ == '__main__':
    main()
