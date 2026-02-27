from flask_sqlalchemy import SQLAlchemy

# Keep the original SQLAlchemy instance for backward compatibility
db = SQLAlchemy()

def cleanup_session(exception=None):
    """Clean up the session at the end of the request."""
    pass