import os
from datetime import datetime, timedelta
import pandas as pd
from flask import request, render_template, Blueprint, jsonify
from routes.auth import login_required
from nistiprint_shared.services.file_processors import process_mercadolivre, process_shopee, process_amazon, process_shein
from constants import PLATFORM_X_CNPJ
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from utils import prepare_ml_file
import traceback # Import traceback

consolidar_bp = Blueprint('consolidar', __name__, url_prefix='/api/v2')

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
        print(request.form)
        try:
            _file = request.files.get('file')
            results = {}

            # Handle date filtering
            start_date = request.form.get('start_date')
            end_datetime = request.form.get('end_datetime')
            
            channel_param = request.form.get('channel') # Exclusive identifier (slug)
            
            if not channel_param:
                raise ValueError("O identificador do canal (slug) é obrigatório.")

            # Normalização defensiva do slug recebido
            channel_slug = channel_param.lower().strip().replace(' ', '-').replace('_', '-')

            # Busca robusta: tenta por slug, depois por nome
            all_channels = canal_venda_service.get_all()
            channel = next((c for c in all_channels if c.get('slug') == channel_slug and c.get('ativo', True) != False), None)
            
            if not channel:
                channel = next((c for c in all_channels if c.get('nome') == channel_param and c.get('ativo', True) != False), None)

            if not channel:
                raise ValueError(f"Canal de venda ativo não encontrado para '{channel_param}'. Verifique o slug no cadastro.")

            # A plataforma é derivada do canal encontrado para o roteamento dos processadores
            plataforma = channel.get('plataforma')
            if not plataforma:
                raise ValueError(f"O canal '{channel['nome']}' não possui uma plataforma configurada.")
            
            # Normalização para comparação de roteamento
            plataforma_normalized = plataforma.replace(' ', '').lower()

            # O Bling Client é selecionado através da plataforma, como no original
            bling_client = BlingClient.create_client_for_platform(plataforma)

            options = {
                'plataforma': plataforma,
                'print_orders': request.form.get('print-orders') == 'true',
                'channel_slug': channel.get('slug'),
                'mode': request.form.get('mode')
            }

            if not start_date:
                start_date = datetime.now() - timedelta(days=120)
            if not end_datetime:
                end_datetime = datetime.now() + timedelta(days=30)

            period_filter = {
                'end': pd.to_datetime(end_datetime),
                'start': pd.to_datetime(start_date)
            }

            if not _file or not (_file.filename.endswith('.xlsx') or _file.filename.endswith('.csv')):
                raise ValueError("Arquivo inválido. Apenas .xlsx e .csv são aceitos.")

            filepath = os.path.join(basedir, _file.filename)
            _file.save(filepath)

            if plataforma_normalized == 'mercadolivre':
                new_file_path = prepare_ml_file(filepath)
                result = process_mercadolivre(
                    new_file_path, period_filter, options, bling_client)
                os.remove(new_file_path)
            elif 'shopee' in plataforma_normalized:
                result = process_shopee(filepath, period_filter, options, bling_client)
            elif plataforma_normalized == 'amazon':
                result = process_amazon(filepath, period_filter, options, bling_client)
            elif plataforma_normalized == 'shein':
                result = process_shein(filepath, period_filter, options, bling_client)
            else:
                raise ValueError(f"Plataforma '{plataforma}' não suportada")

            capas, total_capas, miolos, total_miolos, capas_miolos, ids_pedidos, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, raw_data = result

            # --- NOVO: VERIFICAÇÃO DE CONFLITOS (SEM ALTERAR ESTRUTURA DE EXIBIÇÃO) ---
            from nistiprint_shared.services.order_tracker_service import order_tracker_service
            all_orders_to_check = []
            
            # Mapeamento interno para uso futuro se necessário (sem expor no JSON de dados)
            order_mapping = {} 

            if hasattr(capas_miolos, 'iterrows'):
                for idx, row in capas_miolos.iterrows():
                    refs = row.get('order_refs', [])
                    sku = str(row.get('SKU', ''))
                    for ref in refs:
                        all_orders_to_check.append({
                            'pedido_externo_id': str(ref),
                            'sku_externo': sku
                        })
                
                # Opcional: Remover a coluna de refs do dataframe para não vazar para o frontend/display
                if 'order_refs' in capas_miolos.columns:
                    # Criamos uma cópia para exibição sem a coluna nova
                    display_capas_miolos = capas_miolos.drop(columns=['order_refs'])
                else:
                    display_capas_miolos = capas_miolos
            else:
                display_capas_miolos = capas_miolos
            
            conflicts = order_tracker_service.check_conflicts(all_orders_to_check, plataforma)
            # -------------------------------------------------------------------------

            if plataforma:
                results[plataforma] = {
                    'total_capas': total_capas,
                    'total_miolos': total_miolos,
                    # JSON serializable data - USANDO display_capas_miolos para manter estrutura original
                    'capas_data': capas.where(pd.notnull(capas), None).to_dict('records') if hasattr(capas, 'to_dict') else capas,
                    'miolos_data': miolos.where(pd.notnull(miolos), None).to_dict('records') if hasattr(miolos, 'to_dict') else miolos,
                    'capas_miolos_data': display_capas_miolos.where(pd.notnull(display_capas_miolos), None).to_dict('records') if hasattr(display_capas_miolos, 'to_dict') else display_capas_miolos,
                    'ids_pedidos': ids_pedidos,
                    'total_pedidos_plataforma': total_pedidos_plataforma,
                    'bling_orders_id': bling_orders_id,
                    'bling_orders_data': bling_orders_data,
                    'bling_orders_id_numero': bling_orders_id_numero,
                    'bling_orders_not_found': bling_orders_not_found,
                    'raw_data': raw_data.where(pd.notnull(raw_data), None).to_dict('records') if hasattr(raw_data, 'to_dict') else raw_data,
                    'options': options,
                    'conflicts': conflicts # Adicionado como campo extra, geralmente ignorado por renderizadores de tabela estritos
                }

            os.remove(filepath)

            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify(results)

            return render_template('results.html', results=results, period_filter=period_filter, options=options)

        except Exception as e:
            print(f"Error processing /consolidar: {e}")
            traceback.print_exc() # Print the full traceback
            error_message = str(e)
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({'error': error_message}), 400
            return render_template('error.html', message=error_message)

    return render_template('consolidar.html')





