import os
from datetime import datetime, timedelta
import pandas as pd
from flask import request, Blueprint, jsonify
from routes.auth import login_required
from nistiprint_shared.services.file_processors import process_mercadolivre, process_shopee, process_amazon, process_shein
from constants import PLATFORM_X_CNPJ
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from utils import prepare_ml_file
import traceback # Import traceback
import json

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
            channel_id = channel.get('id')
            if not plataforma:
                raise ValueError(f"O canal '{channel['nome']}' não possui uma plataforma configurada.")
            
            # Normalização para comparação de roteamento
            plataforma_normalized = plataforma.replace(' ', '').lower()

            # 1. Resolver qual conta Bling usar para esta operação de consolidação/importação
            from nistiprint_shared.services.integration_routing_service import integration_routing_service
            account_id = integration_routing_service.get_account_id(
                function_name='ORDER_IMPORT',
                module='bling',
                channel_id=channel_id,
                platform_name=plataforma
            )

            # 2. Criar o cliente Bling apontando para a conta correta
            bling_client = BlingClient.create_client_for_platform(
                plataforma, 
                channel_id=channel_id, 
                function_name='ORDER_IMPORT'
            )

            options = {
                'plataforma': plataforma,
                'print_orders': request.form.get('print-orders') == 'true',
                'is_flex': request.form.get('is_flex') == 'true',
                'channel_slug': channel.get('slug'),
                'channel_id': channel_id,
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

            # --- NOVO: PERSISTÊNCIA DOS PEDIDOS NO BANCO UNIFICADO ---
            from nistiprint_shared.services.order_service import order_service
            import logging

            if bling_orders_data:
                print(f"💾 Iniciando persistência de {len(bling_orders_data)} pedidos no banco unificado...")
                for order in bling_orders_data:
                    try:
                        # Normalização básica para o OrderService
                        order_to_upsert = {
                            'codigo_pedido_externo': str(order.get('numeroLoja')),
                            'numero_pedido': str(order.get('numero')),
                            'cliente_nome': order.get('contato', {}).get('nome'),
                            'cliente_documento': order.get('contato', {}).get('numeroDocumento'),
                            'status_original': str(order.get('situacao', {}).get('id', 'IMPORTADO')),
                            'total_pedido': float(order.get('totalProdutos', 0)),
                            'origem': plataforma
                        }
                        
                        # Mapeia itens para o formato do serviço
                        order_items = []
                        for item in order.get('itens', []):
                            order_items.append({
                                'sku_externo': item.get('codigo'),
                                'descricao': item.get('descricao'),
                                'quantidade': item.get('quantidade'),
                                'preco_unitario': item.get('valor')
                            })

                        order_service.upsert_order(
                            order_data=order_to_upsert,
                            platform=plataforma,
                            platform_order_id=str(order.get('numeroLoja')),
                            raw_payload=order,
                            items=order_items,
                            channel_id=channel_id,
                            integration_id=account_id
                        )
                    except Exception as upsert_error:
                        logging.error(f"Erro ao persistir pedido {order.get('numeroLoja')} na consolidação: {upsert_error}")
            # ---------------------------------------------------------

            if plataforma:
                # Adiciona order_refs como campo separado para exibição no frontend
                if hasattr(display_capas_miolos, 'copy'):
                    display_capas_miolos_with_refs = display_capas_miolos.copy()
                else:
                    display_capas_miolos_with_refs = display_capas_miolos
                    
                # Re-adiciona order_refs se existir no capas_miolos original
                if hasattr(capas_miolos, 'iterrows') and 'order_refs' in capas_miolos.columns:
                    # Recria o order_refs a partir do original
                    order_refs_list = []
                    for idx, row in capas_miolos.iterrows():
                        refs = row.get('order_refs', [])
                        order_refs_list.append(refs if refs else None)
                    
                    # Adiciona como nova coluna
                    display_capas_miolos_with_refs = display_capas_miolos_with_refs.copy()
                    display_capas_miolos_with_refs['order_refs'] = order_refs_list

                results[plataforma] = {
                    'total_capas': total_capas,
                    'total_miolos': total_miolos,
                    # JSON serializable data - USANDO display_capas_miolos_with_refs para manter order_refs
                    'capas_data': capas.where(pd.notnull(capas), None).to_dict('records') if hasattr(capas, 'to_dict') else capas,
                    'miolos_data': miolos.where(pd.notnull(miolos), None).to_dict('records') if hasattr(miolos, 'to_dict') else miolos,
                    'capas_miolos_data': display_capas_miolos_with_refs.where(pd.notnull(display_capas_miolos_with_refs), None).to_dict('records') if hasattr(display_capas_miolos_with_refs, 'to_dict') else display_capas_miolos_with_refs,
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

            # Sempre retorna JSON para API React frontend
            return jsonify(results)

        except Exception as e:
            print(f"Error processing /consolidar: {e}")
            traceback.print_exc() # Print the full traceback
            error_message = str(e)
            # Sempre retorna JSON para API React frontend
            return jsonify({'error': error_message}), 400

    # GET endpoint - retorna informações básicas da API
    return jsonify({'message': 'Endpoint de consolidação. Use POST para processar arquivos.'})


# ============================================================================
# ENDPOINTS ASSÍNCRONOS PARA PROCESSAMENTO DE ARQUIVOS GRANDES
# ============================================================================

@consolidar_bp.route('/consolidar-async', methods=['POST'])
@login_required
def consolidar_async():
    """
    Inicia processamento assíncrono de consolidação de pedidos.
    Retorna imediatamente com um ID para polling.
    """
    try:
        _file = request.files.get('file')
        
        # Parse form data
        start_date = request.form.get('start_date')
        end_datetime = request.form.get('end_datetime')
        channel_param = request.form.get('channel')
        print_orders = request.form.get('print-orders') == 'true'
        is_flex = request.form.get('is_flex') == 'true'
        mode = request.form.get('mode', 'legacy')
        
        if not channel_param:
            return jsonify({'error': 'O identificador do canal (slug) é obrigatório.'}), 400
        
        if not _file or not (_file.filename.endswith('.xlsx') or _file.filename.endswith('.csv')):
            return jsonify({'error': 'Arquivo inválido. Apenas .xlsx e .csv são aceitos.'}), 400
        
        # Busca canal
        channel_slug = channel_param.lower().strip().replace(' ', '-').replace('_', '-')
        all_channels = canal_venda_service.get_all()
        channel = next((c for c in all_channels if c.get('slug') == channel_slug and c.get('ativo', True) != False), None)
        
        if not channel:
            channel = next((c for c in all_channels if c.get('nome') == channel_param and c.get('ativo', True) != False), None)
        
        if not channel:
            return jsonify({'error': f'Canal de venda ativo não encontrado para {channel_param}'}), 404
        
        plataforma = channel.get('plataforma')
        channel_id = channel.get('id')
        
        # Salva arquivo temporário
        basedir = _ensure_temp_dir()
        filepath = os.path.join(basedir, _file.filename)
        _file.save(filepath)
        
        # Prepara period filter
        if not start_date:
            start_date = datetime.now() - timedelta(days=120)
        if not end_datetime:
            end_datetime = datetime.now() + timedelta(days=30)
        
        # Cria registro na tabela consolidacoes_pedido
        from nistiprint_shared.database.supabase_db_service import supabase_db
        
        options = {
            'plataforma': plataforma,
            'print_orders': print_orders,
            'is_flex': is_flex,
            'channel_slug': channel.get('slug'),
            'channel_id': channel_id,
            'mode': mode,
            'file_path': filepath,
            'file_name': _file.filename
        }
        
        consolidacao_record = {
            'status': 'PENDENTE',
            'platform': plataforma,
            'channel_id': channel_id,
            'channel_slug': channel.get('slug'),
            'file_path': filepath,
            'file_name': _file.filename,
            'period_filter_start': pd.to_datetime(start_date).isoformat() if start_date else None,
            'period_filter_end': pd.to_datetime(end_datetime).isoformat() if end_datetime else None,
            'options': options
        }
        
        result = supabase_db.table('consolidacoes_pedido').insert(consolidacao_record).execute()
        
        if not result.data:
            return jsonify({'error': 'Falha ao criar registro de consolidação'}), 500
        
        consolidacao_id = result.data[0]['id']
        
        # Dispara task Celery para processamento
        try:
            from nistiprint_shared.services.celery_app import celery_app
            celery_app.send_task(
                'tasks.consolidation_tasks.process_consolidacao',
                args=[consolidacao_id],
                kwargs={}
            )
            print(f"DEBUG: Task Celery disparada para consolidação {consolidacao_id}")
        except Exception as celery_err:
            print(f"AVISO: Falha ao disparar task Celery: {celery_err}")
            # Atualiza status para ERRO
            supabase_db.table('consolidacoes_pedido').update({
                'status': 'ERRO',
                'error_message': f'Falha ao disparar worker: {str(celery_err)}'
            }).eq('id', consolidacao_id).execute()
            return jsonify({'error': 'Falha ao iniciar processamento assíncrono'}), 500
        
        return jsonify({
            'consolidacao_id': consolidacao_id,
            'status': 'PENDENTE',
            'message': 'Processamento iniciado. Use GET /consolidar-async/:id para acompanhar.'
        }), 202
        
    except Exception as e:
        print(f"Error in consolidar_async: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@consolidar_bp.route('/consolidar-async/<int:consolidacao_id>', methods=['GET'])
@login_required
def get_consolidacao_status(consolidacao_id):
    """
    Retorna o status e resultado de uma consolidação assíncrona.
    """
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        
        response = supabase_db.table('consolidacoes_pedido').select('*').eq('id', consolidacao_id).execute()
        
        if not response.data:
            return jsonify({'error': 'Consolidação não encontrada'}), 404
        
        consolidacao = response.data[0]
        
        return_response = {
            'id': consolidacao['id'],
            'status': consolidacao['status'],
            'platform': consolidacao['platform'],
            'channel_id': consolidacao['channel_id'],
            'created_at': consolidacao['created_at'],
            'updated_at': consolidacao['updated_at'],
            'processing_started_at': consolidacao.get('processing_started_at'),
            'processing_completed_at': consolidacao.get('processing_completed_at'),
            'error_message': consolidacao.get('error_message')
        }
        
        # Se status for PRONTO, inclui o resultado
        if consolidacao['status'] == 'PRONTO' and consolidacao.get('result_data'):
            return_response['result'] = consolidacao['result_data']
        
        return jsonify(return_response)
        
    except Exception as e:
        print(f"Error getting consolidacao status: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@consolidar_bp.route('/consolidar-async/<int:consolidacao_id>/result', methods=['GET'])
@login_required
def get_consolidacao_result(consolidacao_id):
    """
    Retorna apenas o resultado de uma consolidação (se pronta).
    """
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        
        response = supabase_db.table('consolidacoes_pedido').select('status, result_data, error_message').eq('id', consolidacao_id).execute()
        
        if not response.data:
            return jsonify({'error': 'Consolidação não encontrada'}), 404
        
        consolidacao = response.data[0]
        
        if consolidacao['status'] != 'PRONTO':
            return jsonify({
                'error': 'Consolidação ainda não está pronta',
                'status': consolidacao['status']
            }), 400
        
        if not consolidacao.get('result_data'):
            return jsonify({'error': 'Resultado não encontrado'}), 404
        
        return jsonify(consolidacao['result_data'])
        
    except Exception as e:
        print(f"Error getting consolidacao result: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500





