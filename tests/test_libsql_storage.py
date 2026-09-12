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


def test_backup_restore_preserves_data_and_constraints(tmp_path):
    from historian.libsql_store.operations import snapshot, check
    tmp_path.chmod(0o700)
    source, backup, restored = [tmp_path / name for name in ('source.db', 'backup.db', 'restored.db')]
    initialize(source)
    c = connect(source)
    c.execute("INSERT INTO question VALUES ('q','question')")
    c.close()
    snapshot(source, backup)
    snapshot(backup, restored)
    check(restored)
    c = connect(restored)
    assert c.execute('SELECT * FROM question').fetchall() == [('q', 'question')]
    with pytest.raises(ValueError, match='immutable'):
        c.execute("UPDATE question SET text='changed'")
    c.close()
    with pytest.raises(ValueError, match='already exists'):
        snapshot(source, backup)


def test_unknown_schema_is_never_silently_upgraded(tmp_path):
    path = tmp_path / 'old.db'
    initialize(path)
    c = connect(path)
    c.execute('DROP TRIGGER immutable_question_UPDATE')
    c.close()
    with pytest.raises(ValueError, match='unsupported schema'):
        initialize(path)
    c = connect(path)
    assert c.execute("SELECT name FROM sqlite_master WHERE name='immutable_question_UPDATE'").fetchall() == []
    c.close()


def test_backup_refuses_live_service_lock(tmp_path):
    from historian.libsql_store.operations import snapshot, storage_lock
    tmp_path.chmod(0o700)
    source = tmp_path / 'source.db'
    initialize(source)
    with storage_lock(source):
        with pytest.raises(RuntimeError, match='in use'):
            snapshot(source, tmp_path / 'backup.db')
    assert not (tmp_path / 'backup.db').exists()
