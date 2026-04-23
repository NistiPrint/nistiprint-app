from flask import Blueprint, render_template, request
import requests
from services.report_service import report_service

relatorios_bp = Blueprint('relatorios_bp', __name__, template_folder='../templates')

@relatorios_bp.route('/relatorios')
def index():
    """
    Renders the main reports page.
    """
    # Fetch the report data from the service
    sulfite_report_data = report_service.get_sulfite_consumption_report()
    
    return render_template('relatorios/index.html', sulfite_report=sulfite_report_data)

@relatorios_bp.route('/relatorios/historico-producao')
def historico_producao():
    """Renders the production log history page."""
    page = request.args.get('page', 1, type=int)
    per_page = 50 # Or get from a config

    logs, has_next = report_service.get_production_log_history(page=page, per_page=per_page)

    return render_template(
        'relatorios/historico_producao.html',
        logs=logs,
        page=page,
        has_next=has_next
    )
