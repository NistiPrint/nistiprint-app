import os
from datetime import datetime, timedelta
import pandas as pd
from flask import request, render_template, Blueprint
from routes.auth import login_required
from services.file_processors import process_mercadolivre, process_shopee, process_amazon, process_shein
from constants import PLATFORM_X_CNPJ
from services.bling.bling_client import BlingClient
from utils import prepare_ml_file

consolidar_bp = Blueprint('consolidar', __name__)

def _ensure_temp_dir():
    """Garante que o diretório temp existe."""
    basedir = os.path.join(os.getcwd(), 'temp')
    if not os.path.exists(basedir):
        os.makedirs(basedir)
    return basedir

basedir = _ensure_temp_dir()

@consolidar_bp.route('/consolidar', methods=['GET', 'POST'])
@login_required
def consolidar():
    if request.method == 'POST':
        _file = request.files.get('file')
        results = {}

        # Handle date filtering
        start_date = request.form.get('start_date')
        end_datetime = request.form.get('end_datetime')

        # Captura os valores dos checkboxes
        options = {
            'platform': request.form.get('platform'),
            'print_orders': request.form.get('print-orders') == 'true'
        }

        if not start_date:
            start_date = datetime.now() - timedelta(days=120)
        if not end_datetime:
            end_datetime = datetime.now() + timedelta(days=30)

        period_filter = {
            'end': pd.to_datetime(end_datetime),
            'start': pd.to_datetime(start_date)
        }

        if _file and (_file.filename.endswith('.xlsx') or _file.filename.endswith('.csv')):
            filepath = os.path.join(basedir, _file.filename)
            _file.save(filepath)

        # Obter o CNPJ da plataforma selecionada
        cnpj = PLATFORM_X_CNPJ.get(options['platform'].lower(), None)
        if not cnpj:
            return render_template('error.html', message=f"Plataforma {options['platform']} não tem CNPJ configurado")

        # Criar cliente Bling com CNPJ
        bling_client = BlingClient.create_client(cnpj=cnpj)

        if options['platform'] == 'MercadoLivre':
            new_file_path = prepare_ml_file(filepath)
            result = process_mercadolivre(
                new_file_path, period_filter, options, bling_client)
            os.remove(new_file_path)
        elif 'Shopee' in options['platform']:
            result = process_shopee(filepath, period_filter, options, bling_client)
        elif options['platform'] == 'Amazon':
            result = process_amazon(filepath, period_filter, options, bling_client)
        elif options['platform'] == 'Shein':
            result = process_shein(filepath, period_filter, options, bling_client)

        capas, total_capas, miolos, total_miolos, capas_miolos, ids_pedidos, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, raw_data = result

        if options['platform']:
            results[options['platform']] = {
                'capas': capas.to_html(classes='data', header="true", index=False),
                'total_capas': total_capas,
                'miolos': miolos.to_html(classes='data', header="true", index=False),
                'total_miolos': total_miolos,
                'capas_miolos': capas_miolos.to_html(classes='data', header="true", index=False),
                'ids_pedidos': ids_pedidos,
                'total_pedidos_plataforma': total_pedidos_plataforma,
                'bling_orders_id': bling_orders_id,
                'bling_orders_data': bling_orders_data,
                'bling_orders_id_numero': bling_orders_id_numero,
                'bling_orders_not_found': bling_orders_not_found,
                'raw_data': raw_data,
                'options': options
            }

        os.remove(filepath)

        return render_template('results.html', results=results, period_filter=period_filter, options=options)

    return render_template('consolidar.html')
