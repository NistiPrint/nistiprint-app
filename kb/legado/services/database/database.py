from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from contextlib import contextmanager
from flask import current_app

db = SQLAlchemy()

def get_db_session_factory():
    """Create and return a new session factory."""
    return sessionmaker(
        bind=db.engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False
    )

# Create a thread-local registry for sessions
_session_factory = None

def get_session():
    """Get a scoped session, creating the session factory if needed."""
    global _session_factory
    if _session_factory is None:
        _session_factory = scoped_session(get_db_session_factory())
    return _session_factory()

@contextmanager
def get_db_session():
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Database error: {str(e)}")
        raise
    finally:
        session.close()

def cleanup_session(exception=None):
    """Clean up the session at the end of the request."""
    global _session_factory
    if _session_factory is not None:
        _session_factory.remove()
