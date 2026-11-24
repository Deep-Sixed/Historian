"""Offline service-owner operations; never exposed through the caller socket."""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from historian.sqlite_store.repository import connect, validate_schema


def private_parent(path):
    parent = Path(path).parent
    st = parent.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("storage directory must be owner-private (0700)")


@contextmanager
def storage_lock(database):
    private_parent(database)
    with open(str(database) + ".lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("storage is in use; stop the service first") from None
        yield


def check(database):
    if not Path(database).is_file():
        raise ValueError("database does not exist")
    c = connect(database)
    try:
        validate_schema(c)
        if c.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("database integrity check failed")
        if c.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("database foreign key check failed")
    finally:
        c.close()


def snapshot(source, destination):
    """Create a consistent, validated, new file; refuse all overwrites."""
    private_parent(source)
    private_parent(destination)
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError("source and destination must differ")
    with storage_lock(source), storage_lock(destination):
        check(source)
        if Path(destination).exists():
            raise ValueError("destination already exists; restore into a new path")
        # Reserve the name before VACUUM; SQLite accepts an empty destination file.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        c = connect(source)
        try:
            c.execute("VACUUM INTO ?", (str(destination),))
            check(destination)
            with open(destination, "rb") as result:
                os.fsync(result.fileno())
            directory = os.open(Path(destination).parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            Path(destination).unlink(missing_ok=True)
            raise
        finally:
            c.close()
