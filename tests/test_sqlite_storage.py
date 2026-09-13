"""Local driver checks that do not substitute for deployed capability-boundary proof."""
import pytest

import sqlite3
from historian.sqlite_store.repository import connect, initialize


def test_origin_binding_and_foreign_key_have_distinct_sqlite_error_codes(tmp_path):
    path = tmp_path / 'origins.db'
    initialize(path)
    c = connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError) as origin:
            c.execute("INSERT INTO assertion VALUES (?,?,?,?,?,?)",
                      ('a', 'missing', 'also-missing', 'HUMAN_REVIEWED_PROPOSAL',
                       'uid:10004', 'typed'))
        assert origin.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK
        assert str(origin.value) == 'CHECK constraint failed: assertion_origin_binding'
        with pytest.raises(sqlite3.IntegrityError) as foreign_key:
            c.execute("INSERT INTO assertion VALUES (?,?,?,?,?,?)",
                      ('a', 'missing', 'also-missing', 'TYPED_SOURCE',
                       'uid:10004', 'typed'))
        assert foreign_key.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY
        assert c.execute('SELECT count(*) FROM assertion').fetchone() == (0,)
    finally:
        c.close()


@pytest.mark.parametrize('identity', [None, ''])
def test_durable_identity_cannot_be_null_or_empty(tmp_path, identity):
    path = tmp_path / 'identity.db'
    initialize(path)
    c = connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('INSERT INTO question VALUES (?,?)', (identity, 'question'))
        assert c.execute('SELECT count(*) FROM question').fetchone() == (0,)
    finally:
        c.close()


def test_backup_restore_preserves_data_and_constraints(tmp_path):
    from historian.sqlite_store.operations import snapshot, check
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
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
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
    from historian.sqlite_store.operations import snapshot, storage_lock
    tmp_path.chmod(0o700)
    source = tmp_path / 'source.db'
    initialize(source)
    with storage_lock(source):
        with pytest.raises(RuntimeError, match='in use'):
            snapshot(source, tmp_path / 'backup.db')
    assert not (tmp_path / 'backup.db').exists()


def test_upgrade_alpha_schema_is_additive_and_preserves_immutability(tmp_path):
    from historian.sqlite_store.repository import _create_schema, upgrade_schema, validate_schema
    path = tmp_path / 'previous.db'
    c = connect(path)
    _create_schema(c, application=False)
    c.execute("INSERT INTO question VALUES ('old','retained')")
    c.close()
    with pytest.raises(ValueError, match='unsupported schema'):
        initialize(path)
    upgrade_schema(path)
    upgrade_schema(path)  # Repeat is harmless, no duplicate data or triggers.
    c = connect(path)
    validate_schema(c)
    assert c.execute('SELECT * FROM question').fetchall() == [('old','retained')]
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        c.execute("DELETE FROM question")
    c.close()
