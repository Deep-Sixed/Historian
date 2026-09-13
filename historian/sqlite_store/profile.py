import json
import platform
import sqlite3
from historian.sqlite_store.access import WRITE, READ
from historian.persistence.catalog import CATALOG
from historian.persistence.contract import Boundary, PersistenceProfile, ThreatModel

SQLITE = PersistenceProfile(
    name="sqlite-linux-peercred-service-v1",
    version=1,
    backend_family="SQLite",
    deployment_model=f"Linux local Unix socket service, Python {platform.python_version()}, "
    f"stdlib sqlite3, SQLite {sqlite3.sqlite_version}; "
    "service UID 10000; private 0700 database directory and 0755 socket directory; "
    "WAL with foreign_keys enabled; no remote database endpoint.",
    credential_access_model="SO_PEERCRED kernel UID; fixed UID 10001..10009 capability mapping; "
    "assertion writes persist the kernel-derived principal and capability, and "
    "the database constrains origin compatibility for UIDs 10004 and 10005. "
    "Domain object writes and reads use a fixed per-type capability allowlist; full resolution and gold lineage are stored atomically. Packet snapshot reads use the AdjudicationPacket read capability set. "
    + json.dumps({"write": {k: sorted(v) for k,v in WRITE.items()}, "read": {k: sorted(v) for k,v in READ.items()}},sort_keys=True)
    + " No shared database credential or bearer secret. Callers cannot acquire "
    "service UID, root, container control, ptrace or database files.",
    trusted_boundaries=(Boundary.DATABASE, Boundary.TRUSTED_SERVICE),
    excluded_untrusted_boundaries=(
        "request role/identity fields",
        "arbitrary client processes",
        "raw requests and direct file access from caller UIDs",
    ),
    claimed_invariant_coverage=tuple(i.id for i in CATALOG),
    threat_model=ThreatModel(
        actors=(
            ("authorized_service", "UID 10000 exclusively owns database access."),
            (
                "specialized_writer",
                (
                    "Fixed UID maps to extractor/verifier/designer/typed/reviewer/"
                    "runtime/builder/adjudicator/gold, in that order, UIDs 10001..10009."
                ),
            ),
            (
                "ordinary_caller",
                "Unassigned UID may connect but has no operation capability.",
            ),
            (
                "bypass_caller",
                "Can send arbitrary socket JSON and run arbitrary code as its UID.",
            ),
            (
                "direct_db_actor",
                "Caller may try opening database, WAL, directory or service proc files.",
            ),
            (
                "privileged_operator",
                "Root/host and service UID are trusted provisioning/TCB.",
            ),
        ),
        access_assumptions=(
            "Linux kernel peer credentials and Unix DAC remain trustworthy.",
            "Each capability is a distinct OS UID; processes sharing a UID share its authority.",
            "Ordinary callers have no sudo/setuid/ptrace privilege or Docker socket access.",
            "No host bind mount exposes database or source directory to a caller namespace.",
            "The service has a finite operation allowlist and no SQL or role-switch endpoint.",
            "The database enforces assertion-origin compatibility for the fixed typed/reviewer UID map.",
            (
                "UID 10002 verifier code is trusted to verify external adapter bytes before direct evidence intake; "
                "the verify_source operation independently rereads configured RAG source bytes."
            ),
        ),
        excluded_threats=(
            "host/root compromise",
            "service UID or service code compromise",
            "compromised trusted verifier UID 10002",
            "kernel compromise",
            "physical disk access",
            "power-loss certification",
        ),
    ),
)
