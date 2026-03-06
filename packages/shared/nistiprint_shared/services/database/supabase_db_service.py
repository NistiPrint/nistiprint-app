"""
Supabase Database Service that focuses exclusively on Supabase
"""
import os
from enum import Enum
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from contextlib import contextmanager

# Import the Supabase service
from nistiprint_shared.database.supabase_db_service import get_db_session as get_supabase_session, get_session as get_supabase_raw_session, SupabaseDBService

# Load environment variables
load_dotenv()

class DatabaseMode(Enum):
    SUPABASE = "supabase"


def get_current_database_mode() -> DatabaseMode:
    """
    Always return Supabase mode since we're using only Supabase
    """
    return DatabaseMode.SUPABASE


def get_db_session():
    """
    Get a Supabase database session
    """
    return get_supabase_session()


def get_session():
    """
    Get a raw Supabase database session
    """
    return get_supabase_raw_session()


def cleanup_session(exception=None):
    """
    Clean up the session (no-op since Supabase handles this differently)
    """
    # Supabase session cleanup is handled internally
    pass


def init_app_with_supabase_db(app):
    """
    Initialize the app with support for Supabase only
    """
    # Use Supabase PostgreSQL database
    supabase_url = os.environ.get('SUPABASE_URL')
    if not supabase_url:
        raise ValueError("SUPABASE_URL must be set when using Supabase mode")

    # Configure for PostgreSQL (Supabase uses PostgreSQL)
    app.config['SQLALCHEMY_DATABASE_URI'] = supabase_url.replace("http://", "postgresql://").replace("https://", "postgresql://")

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 280,
        'pool_pre_ping': True
    }

    # Initialize and test the Supabase client
    try:
        supabase_service = SupabaseDBService()  # Initialize to test connection

        # Perform a connection test
        test_connection(app, supabase_service)

    except Exception as e:
        app.logger.error(f"Failed to initialize Supabase: {e}")
        raise


def test_connection(app, supabase_service):
    """
    Test the Supabase connection by performing a simple operation
    """
    try:
        # Test by attempting to query a common table (e.g., usuarios)
        # This will verify that we can connect and perform basic operations
        result = supabase_service.get_all('usuarios', {'limit': 1})  # Try to get one user record
        app.logger.info("Supabase connection test successful: Able to query 'usuarios' table")

        # Log success message
        app.logger.info("✓ Successfully connected to Supabase database")

        # Also test with another common table if it exists
        try:
            result = supabase_service.get_all('produtos', {'limit': 1})  # Try to get one product record
            app.logger.info("Supabase connection test successful: Able to query 'produtos' table")
        except Exception:
            # If products table doesn't exist yet, that's fine
            app.logger.info("Supabase connection test: 'products' table may not exist yet, which is OK")

    except Exception as e:
        app.logger.error(f"Supabase connection test failed: {e}")
        raise


# Export the main db object for backward compatibility (using mock db for Supabase mode)
from nistiprint_shared.database.supabase_db_service import mock_db as db

