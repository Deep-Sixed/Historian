import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-pg",
        action="store_true",
        default=False,
        help="run PostgreSQL security/invariant tests",
    )
    parser.addoption(
        "--run-corpus",
        action="store_true",
        default=False,
        help="run real-corpus canary tests",
    )


def pytest_collection_modifyitems(config, items):
    skip_pg = pytest.mark.skip(reason="PostgreSQL gate requires --run-pg")
    skip_corpus = pytest.mark.skip(reason="corpus canary requires --run-corpus")

    for item in items:
        if "pg" in item.keywords and not config.getoption("--run-pg"):
            item.add_marker(skip_pg)
        if "canary" in item.keywords and not config.getoption("--run-corpus"):
            item.add_marker(skip_corpus)


def pytest_configure(config):
    if config.getoption("--run-pg"):
        os.environ["HISTORIAN_RUN_PG"] = "1"
    if config.getoption("--run-corpus"):
        os.environ["HISTORIAN_RUN_CORPUS"] = "1"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("--run-pg"):
        terminalreporter.write_line("PostgreSQL gates: NOT RUN (use --run-pg)")
    if not config.getoption("--run-corpus"):
        terminalreporter.write_line("Corpus canary: NOT RUN (use --run-corpus)")
