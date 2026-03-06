from flask import Blueprint, jsonify, request, current_app
from nistiprint_shared.services.installed_integration_service import installed_integration_service
from nistiprint_shared.services.app_config_service import app_config_service
import os
import logging

jobs_bp = Blueprint('jobs', __name__, url_prefix='/api/jobs')

@jobs_bp.route('/refresh-tokens', methods=['POST'])
def refresh_tokens_job():
    """
    Job to refresh integration tokens.
    Protected by X-Job-Key header.
    """
    # 1. Security Check
    job_key = request.headers.get('X-Job-Key')
    env_job_key = os.environ.get('JOB_SECRET')
    
    # If JOB_SECRET is not set, we might want to fail or allow only localhost (optional)
    # For now, if not set, we deny access to be safe, unless in dev
    if not env_job_key:
        if os.environ.get('FLASK_ENV') == 'development':
            pass # Allow in dev if secret not set
        else:
            logging.error("JOB_SECRET not set in environment")
            return jsonify({'error': 'Server misconfiguration'}), 500
    elif job_key != env_job_key:
        return jsonify({'error': 'Unauthorized'}), 401

    # 2. Feature Flag Check
    is_enabled = app_config_service.get_config('ENABLE_AUTOMATIC_TOKEN_REFRESH')
    
    # Default to False if not set
    if not is_enabled:
        logging.info("Job ENABLE_AUTOMATIC_TOKEN_REFRESH is disabled or not set.")
        return jsonify({
            'status': 'skipped', 
            'message': 'Job is disabled by configuration (ENABLE_AUTOMATIC_TOKEN_REFRESH)'
        }), 200

    # 3. Execution
    try:
        logging.info("Starting automatic token refresh job...")
        results = installed_integration_service.check_and_refresh_tokens()
        logging.info(f"Token refresh job finished. Results: {results}")
        return jsonify({
            'status': 'success',
            'results': results
        }), 200
    except Exception as e:
        logging.error(f"Error in token refresh job: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500





