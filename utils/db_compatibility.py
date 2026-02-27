"""
Database Compatibility Utilities
Provides database-agnostic functions to handle differences between MySQL and PostgreSQL
"""
from services.database.supabase_db_service import get_current_database_mode, DatabaseMode
from sqlalchemy import text


def get_concat_function():
    """
    Returns the appropriate concatenation function based on the database type
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        return "STRING_AGG"
    else:
        return "GROUP_CONCAT"


def get_json_build_function():
    """
    Returns the appropriate JSON building function based on the database type
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        return "json_build_object"
    else:
        return "JSON_OBJECT"


def get_json_agg_function():
    """
    Returns the appropriate JSON aggregation function based on the database type
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        return "json_agg"
    else:
        return "JSON_ARRAYAGG"


def get_json_extract_operator():
    """
    Returns the appropriate JSON extraction operator based on the database type
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        return "->>"
    else:
        return "JSON_EXTRACT"


def get_separator_clause():
    """
    Returns the appropriate separator clause based on the database type
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        return ", '|||'"
    else:
        return " SEPARATOR '|||'"


def get_group_concat_max_len_statement():
    """
    Returns the appropriate statement to set max length for group concatenation
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        # PostgreSQL doesn't need this setting as it handles large concatenations differently
        return ""
    else:
        return "SET SESSION group_concat_max_len = 1000000"


def get_json_unquote_function():
    """
    Returns the appropriate function to unquote JSON values
    """
    mode = get_current_database_mode()
    if mode == DatabaseMode.SUPABASE:
        # PostgreSQL doesn't need JSON_UNQUOTE as values are extracted directly
        return ""
    else:
        return "JSON_UNQUOTE"


def build_database_aware_query(base_query_parts, db_type=None):
    """
    Builds a database-aware query by replacing placeholders with database-specific syntax
    """
    if db_type is None:
        db_type = get_current_database_mode()
    
    query = base_query_parts
    
    # Replace placeholders with database-specific functions
    if db_type == DatabaseMode.SUPABASE:
        query = query.replace("{CONCAT_FUNCTION}", "STRING_AGG")
        query = query.replace("{JSON_BUILD_FUNCTION}", "json_build_object")
        query = query.replace("{JSON_AGG_FUNCTION}", "json_agg") 
        query = query.replace("{JSON_EXTRACT_OP}", "->>")
        query = query.replace("{SEPARATOR_CLAUSE}", ", '|||'")
        query = query.replace("{JSON_UNQUOTE_FUNCTION}(JSON_EXTRACT", "")
        query = query.replace("JSON_EXTRACT", "")
        # Remove the closing parenthesis for JSON_UNQUOTE
        query = query.replace("))", ")")
        query = query.replace("))", ")")  # Second pass to handle nested cases
    else:
        query = query.replace("{CONCAT_FUNCTION}", "GROUP_CONCAT")
        query = query.replace("{JSON_BUILD_FUNCTION}", "JSON_OBJECT")
        query = query.replace("{JSON_AGG_FUNCTION}", "JSON_ARRAYAGG")
        query = query.replace("{JSON_EXTRACT_OP}", "JSON_EXTRACT")
        query = query.replace("{SEPARATOR_CLAUSE}", " SEPARATOR '|||'")
        query = query.replace("{JSON_UNQUOTE_FUNCTION}", "JSON_UNQUOTE")
    
    return text(query)