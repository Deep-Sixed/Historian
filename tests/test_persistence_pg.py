"""Execute the candidate profile and retain truthful evidence, including known gaps."""
import json
import os
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip('psycopg')
from persistence_pg import PostgreSQLProbe
from test_pg_roles import build_packet, conn, seeded  # noqa: F401

from historian.persistence.catalog import CATALOG
from historian.persistence.contract import ConformanceHarness, Status
from historian.persistence.profiles import POSTGRESQL

pytestmark = pytest.mark.pg


def test_postgresql_profile_conformance(request):
    request.getfixturevalue("seeded")
    packet_id = build_packet("pv-packet-" + uuid4().hex, "S1", "what?",
                             [("e1", 0), ("e2", 1)])
    report = ConformanceHarness(CATALOG).run(POSTGRESQL, PostgreSQLProbe(conn, packet_id))
    destination = Path(os.environ.get('HISTORIAN_CONFORMANCE_REPORT',
                                     '/tmp/historian-persistence-conformance.json'))
    destination.write_text(json.dumps(asdict(report), indent=2,
                                     default=lambda v: v.value if isinstance(v, Enum) else str(v)))
    print(f'\n{report.profile_name} version {report.profile_version} '
          f'digest {report.profile_digest}: {report.status.value}')
    assert report.profile_digest == POSTGRESQL.digest
    assert all(e.profile_digest == report.profile_digest for e in report.evidence)
    assert all(e.access is e.expected_access and e.actor and e.capability_class
               for e in report.evidence)
    # Known violations remain failures IN THE REPORT. This regression gate ensures they
    # are observed; it does not award CONFORMS or skip them to make a green CI badge.
    expected_gaps = {'PV05.bypass', 'PV11.normal', 'PV11.integrity',
                     'PV12.normal', 'PV12.integrity'}
    failures = {e.test_id for e in report.evidence if e.status is Status.DOES_NOT_CONFORM}
    untested = {e.test_id for e in report.evidence if e.status is Status.NOT_TESTED}
    assert not untested, f'unavailable probes: {sorted(untested)}'
    assert failures == expected_gaps
    assert report.status is Status.DOES_NOT_CONFORM
