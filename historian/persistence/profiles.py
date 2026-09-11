"""Declarations are candidates, never evidence of conformance."""
from .catalog import CATALOG
from .contract import Boundary, PersistenceProfile, ThreatModel

POSTGRESQL = PersistenceProfile(
    name='postgresql-role-isolated-v1', version=1, backend_family='PostgreSQL',
    deployment_model='PostgreSQL 18 CI service; frozen baseline plus migration 001; '
                     'isolated disposable database, TCP SCRAM authentication.',
    credential_access_model='Separate login credentials for each capability; individual '
                            'adjudicator principals. Owner credentials are provisioning-only.',
    trusted_boundaries=(Boundary.DATABASE, Boundary.TRUSTED_SERVICE),
    excluded_untrusted_boundaries=('model/extractor payloads', 'ordinary caller identity claims',
                                  'raw SQL from any non-owner capability'),
    claimed_invariant_coverage=tuple(i.id for i in CATALOG),
    threat_model=ThreatModel(
        actors=(
            ('authorized_service', 'Verifier code and source registry are trusted for byte checks.'),
            ('specialized_writer', 'Own credential only; may issue arbitrary SQL.'),
            ('ordinary_caller', 'No owner or other capability credentials; network is not trusted.'),
            ('bypass_caller', 'May bypass Python methods and issue raw SQL as its own role.'),
            ('direct_db_actor', 'TCP connectivity allowed; authentication and grants must hold.'),
            ('privileged_operator', 'Owns schema and provisioning; trusted, outside mutation threat.'),
        ),
        access_assumptions=(
            'Credentials are isolated by deployment; CI supplies independent synthetic credentials.',
            'No application principal has superuser, role administration or owner membership.',
            'Raw access with a specialized credential is IN scope, not a bypass exemption.',
            'Verifier implementation and source access must be tested separately from SQL grants.',
        ),
        excluded_threats=('compromised database owner/host', 'stolen other-capability credentials',
                          'malicious trusted verifier implementation'),
    ),
)
