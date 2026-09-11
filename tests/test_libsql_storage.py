"""Local driver checks that do not substitute for deployed capability-boundary proof."""
import pytest

pytest.importorskip('libsql')
from historian.libsql_store.repository import connect, initialize


@pytest.mark.parametrize('identity', [None, ''])
def test_durable_identity_cannot_be_null_or_empty(tmp_path, identity):
    path = tmp_path / 'identity.db'
    initialize(path)
    c = connect(path)
    try:
        with pytest.raises(ValueError):
            c.execute('INSERT INTO question VALUES (?,?)', (identity, 'question'))
        assert c.execute('SELECT count(*) FROM question').fetchone() == (0,)
    finally:
        c.close()
