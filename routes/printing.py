from flask import Blueprint, request, jsonify
from services.print_service import print_service
from services.database.v2.supabase_db_service import get_db_session
from models.print_job import PrintJob

printing_bp = Blueprint('printing', __name__, url_prefix='/printing')
printing_api_bp = Blueprint('printing_api', __name__, url_prefix='/api/v2/printing')

# --- Existing / Compatible Routes ---

@printing_api_bp.route('/jobs', methods=['GET'])
def api_list_print_jobs():
    """List all print jobs."""
    try:
        # Check for filters in query params
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        
        with get_db_session() as session:
            query = session.query_model(PrintJob)
            if status:
                query = query.filter_by(status=status)
            
            jobs = query.order_by('created_at desc').limit(limit).all()
            return jsonify([job.to_dict() for job in jobs]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@printing_api_bp.route('/job/<job_id>', methods=['GET'])
def api_get_print_job_status(job_id):
    """Get the status of a print job."""
    try:
        job_info = print_service.get_job_status(job_id)
        return jsonify(job_info), 200
    except ValueError as e:
        return jsonify({'error': str(e)}, 400)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@printing_api_bp.route('/job/<job_id>', methods=['DELETE'])
def api_cancel_print_job(job_id):
    """Cancel a print job."""
    try:
        result = print_service.cancel_job(job_id)
        return jsonify({
            'success': True,
            'message': f'Trabalho de impressão {job_id} cancelado com sucesso!',
            'result': result
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}, 400)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@printing_api_bp.route('/product/<produto_id>/jobs', methods=['GET'])
def api_get_product_print_jobs(produto_id):
    """Get all print jobs for a product."""
    try:
        print_jobs = print_service.get_product_jobs(produto_id)
        return jsonify({
            'product_id': produto_id,
            'print_jobs': print_jobs
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}, 400)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- New Routes per Implementation Plan ---

@printing_api_bp.route('/demanda/<demanda_id>/print', methods=['POST'])
def api_print_demanda(demanda_id):
    """Gera jobs para todos os itens da demanda."""
    try:
        mode = request.args.get('mode', 'full') # 'full' or 'balance'
        jobs = print_service.create_jobs_for_demanda(demanda_id, mode=mode)
        return jsonify({
            'message': f'Jobs de impressão criados para demanda {demanda_id}',
            'jobs': jobs,
            'count': len(jobs),
            'mode': mode
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f"Erro interno: {str(e)}"}), 500


@printing_api_bp.route('/item/<item_id>/print', methods=['POST'])
def api_print_item(item_id):
    """Gera jobs para um item específico."""
    try:
        mode = request.args.get('mode', 'full') # 'full' or 'balance'
        jobs = print_service.create_job_from_item(item_id, mode=mode)
        return jsonify({
            'message': f'Jobs de impressão criados para item {item_id}',
            'jobs': jobs,
            'count': len(jobs),
            'mode': mode
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f"Erro interno: {str(e)}"}), 500


@printing_api_bp.route('/job/<job_id>/retry', methods=['POST'])
def api_retry_job(job_id):
    """Reinicia um job com erro."""
    try:
        job = print_service.retry_job(job_id)
        return jsonify({
            'message': f'Job {job_id} reiniciado',
            'job': job
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f"Erro interno: {str(e)}"}), 500
