import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

_DSN = os.environ.get("SHOWER_DB", str(Path(__file__).resolve().parent.parent / "shower_data" / "shower.db"))


def _sa_url():
    if _DSN.startswith("mysql://"):
        return _DSN.replace("mysql://", "mysql+pymysql://", 1)
    return f"sqlite:///{_DSN}"


url = _sa_url()
if url.startswith("sqlite"):
    engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 30})
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_engine(url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine)


def _set_engine(new_engine):
    global engine, SessionLocal
    engine = new_engine
    SessionLocal.configure(bind=engine)

_local_tx = threading.local()
_local_sessions = threading.local()


def get_session():
    if hasattr(_local_tx, "session") and _local_tx.session is not None:
        return _local_tx.session
    # Track and close previous standalone session for this thread
    if hasattr(_local_sessions, "last") and _local_sessions.last is not None:
        try:
            _local_sessions.last.close()
        except Exception:
            pass
    s = SessionLocal()
    _local_sessions.last = s
    return s


def close_session(session):
    """Close a session unless it belongs to an active transaction."""
    if not hasattr(_local_tx, "session") or _local_tx.session is not session:
        session.close()


def write_db(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        session = SessionLocal()
        _local_tx.session = session
        try:
            result = func(*args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            _local_tx.session = None
            session.close()
    return wrapper
