import os
from datetime import datetime, timedelta
import pandas as pd
from flask import request, Blueprint, jsonify
from routes.auth import login_required
# Removido: importação direta dos processadores (agora usamos PlatformProcessorRegistry)
from nistiprint_shared.services.bling_client_resolver_service import bling_client_resolver_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from utils import prepare_ml_file
import traceback
import json
import logging
from uuid import uuid4
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

consolidar_bp = Blueprint('consolidar', __name__, url_prefix='/api/v2')

PLATFORM_LABELS = {
    'shopee': 'Shopee',
    'mercadolivre': 'MercadoLivre',
    'amazon': 'Amazon',
    'shein': 'Shein',
}

def _ensure_temp_dir():
    """Garante que o diretório temp existe."""
    basedir = os.path.join(os.getcwd(), 'temp')
    if not os.path.exists(basedir):
        os.makedirs(basedir)
    return basedir

basedir = _ensure_temp_dir()


def _normalize_platform_key(value):
    normalized = str(value or '').strip().lower().replace(' ', '').replace('_', '').replace('-', '')
    aliases = {
        'mercadolivre': 'mercadolivre',
        'mercadolivrebr': 'mercadolivre',
        'mercadolivreclassic': 'mercadolivre',
        'mercadolivreantiga': 'mercadolivre',
        'ml': 'mercadolivre',
        'shopee': 'shopee',
        'shopeebr': 'shopee',
        'shopeeflex': 'shopee',
        'amazon': 'amazon',
        'amazonbr': 'amazon',
        'shein': 'shein',
        'sheinbr': 'shein',
    }
    return aliases.get(normalized, normalized)


def _resolve_channel(channel_param):
    if not channel_param:
        return None

    channel_slug = channel_param.lower().strip().replace(' ', '-').replace('_', '-')
    all_channels = canal_venda_service.get_all()
    channel = next((c for c in all_channels if c.get('slug') == channel_slug and c.get('ativo', True) is not False), None)

    if channel:
        return channel

    return next((c for c in all_channels if c.get('nome') == channel_param and c.get('ativo', True) is not False), None)


def _resolve_marketplace_context(form):
    platform_input = form.get('platform')
    module_input = form.get('module_id')
    channel_param = form.get('channel')
    marketplace_integration_id = form.get('marketplace_integration_id')
    bling_integration_id = form.get('bling_integration_id')

    channel = _resolve_channel(channel_param)
    platform_candidates = [
        platform_input,
        module_input,
        (channel or {}).get('plataforma'),
        (channel or {}).get('slug'),
        channel_param,
    ]

    platform_key = None
    for candidate in platform_candidates:
        normalized = _normalize_platform_key(candidate)
        if normalized in PLATFORM_LABELS:
            platform_key = normalized
            break

    if not platform_key:
        raise ValueError('Selecione uma plataforma valida para a consolidacao.')

    platform_name = PLATFORM_LABELS[platform_key]
    channel_id = (channel or {}).get('id')
    channel_slug = (channel or {}).get('slug')

    marketplace_installation = None
    if marketplace_integration_id:
        from nistiprint_shared.services.installed_integration_service import installed_integration_service

        marketplace_installation = installed_integration_service.get_installed_by_id(str(marketplace_integration_id))
        if not marketplace_installation:
            raise ValueError(f"Integracao de marketplace '{marketplace_integration_id}' nao encontrada.")
        if _normalize_platform_key(marketplace_installation.module_id) != platform_key:
            raise ValueError(
                f"A integracao '{marketplace_installation.instance_name}' nao pertence a plataforma '{platform_name}'."
            )
        marketplace_integration_id = int(marketplace_installation.id)
    else:
        marketplace_integration_id = None

    if bling_integration_id:
        try:
            bling_integration_id = int(bling_integration_id)
        except ValueError as exc:
            raise ValueError('Conta Bling invalida.') from exc
    else:
        bling_integration_id = None

    return {
        'platform_key': platform_key,
        'platform_name': platform_name,
        'channel': channel,
        'channel_id': channel_id,
        'channel_slug': channel_slug,
        'marketplace_integration_id': marketplace_integration_id,
        'marketplace_installation': marketplace_installation,
        'bling_integration_id': bling_integration_id,
    }


def _resolve_bling_client(context):
    return bling_client_resolver_service.resolve_client(
        bling_integration_id=context.get('bling_integration_id'),
        marketplace_integration_id=context.get('marketplace_integration_id'),
        platform_name=context.get('platform_name'),
        channel_id=context.get('channel_id'),
        function_name='ORDER_IMPORT',
    )

@consolidar_bp.route('/consolidar', methods=['GET', 'POST'])
@login_required
def consolidar():
    return jsonify({
        'success': False,
        'error': 'O upload de planilhas agora acontece em /despacho/arquivo.',
        'redirect': '/despacho/arquivo',
    }), 410

    # Mantido abaixo apenas como referência histórica durante a migração.
    if request.method == 'POST':
        try:
            _file = request.files.get('file')
            results = {}

            # Handle date filtering
            start_date = request.form.get('start_date')
            end_datetime = request.form.get('end_datetime')
            context = _resolve_marketplace_context(request.form)
            plataforma = context['platform_name']
            plataforma_normalized = context['platform_key']
            channel_id = context.get('channel_id')
            bling_client, account_id = _resolve_bling_client(context)

            options = {
                'plataforma': plataforma,
                'platform': plataforma,
                'module_id': plataforma_normalized,
                'print_orders': request.form.get('print-orders') == 'true',
                'is_flex': request.form.get('is_flex') == 'true',
                'persist_new_orders': request.form.get('persist_new_orders', 'true') == 'true',
                'channel_slug': context.get('channel_slug'),
                'channel_id': channel_id,
                'marketplace_integration_id': context.get('marketplace_integration_id'),
                'bling_integration_id': account_id,
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

            safe_name = secure_filename(_file.filename or '')
            if not safe_name:
                raise ValueError('Nome de arquivo invalido.')
            filepath = os.path.join(basedir, f'{uuid4().hex}{os.path.splitext(safe_name)[1].lower()}')
            _file.save(filepath)

            # NOVA ARQUITETURA (Fase 7): Usar PlatformProcessorRegistry
            # Substitui if/else hardcoded por registry lookup
            from nistiprint_shared.services.platform_processor_registry import PlatformProcessorRegistry
            
            try:
                processor_func = PlatformProcessorRegistry.get_processor(plataforma_normalized)
                
                # Caso especial: Mercado Livre requer preparo do arquivo
                if plataforma_normalized == 'mercadolivre':
                    new_file_path = prepare_ml_file(filepath)
                    result = processor_func(
                        new_file_path, period_filter, options, bling_client)
                    os.remove(new_file_path)
                else:
                    result = processor_func(filepath, period_filter, options, bling_client)
                    
            except ValueError as e:
                # Erro do registry (processador não encontrado)
                raise ValueError(f"Plataforma '{plataforma}' não suportada. Detalhes: {str(e)}")
            except Exception as e:
                # Erro no processamento
                logger.error(f"Erro ao processar arquivo para plataforma {plataforma}: {e}")
                raise

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

            # --- NOVO: PERSISTÊNCIA DOS PEDIDOS NO BANCO UNIFICADO (ASSÍNCRONO) ---
            # Para evitar timeout, salvamos os dados em um JSON temporário e enviamos para o worker
            if bling_orders_data and options.get('persist_new_orders'):
                try:
                    import json
                    import uuid
                    
                    # Gera nome de arquivo único
                    temp_filename = f"orders_batch_{uuid.uuid4().hex}.json"
                    temp_filepath = os.path.join(basedir, temp_filename)
                    
                    # Salva payload para o worker
                    with open(temp_filepath, 'w', encoding='utf-8') as f:
                        json.dump({'orders': bling_orders_data}, f)
                        
                    print(f"💾 Disparando persistência assíncrona de {len(bling_orders_data)} pedidos via arquivo {temp_filename}...")
                    
                    from nistiprint_shared.services.celery_app import celery_app
                    celery_app.send_task(
                        'tasks.consolidation_tasks.persist_orders_batch',
                        args=[
                            temp_filepath,
                            plataforma,
                            channel_id,
                            account_id,
                            context.get('marketplace_integration_id')
                        ],
                        kwargs={}
                    )
                except Exception as async_persist_err:
                    print(f"⚠️ Erro ao disparar persistência assíncrona: {async_persist_err}")
                    # Em caso de erro no disparo, não fazemos nada síncrono para não travar.
                    # O usuário poderá tentar novamente ou usar a rota async completa.
            # ---------------------------------------------------------
            elif bling_orders_data:
                print(f"[i] Persistencia de novos pedidos desabilitada para esta consolidacao ({len(bling_orders_data)} pedidos ignorados).")

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
                    'print_order_resolution': options.get('print_order_resolution'),
                    'conflicts': conflicts # Adicionado como campo extra, geralmente ignorado por renderizadores de tabela estritos
                }

            os.remove(filepath)

            # --- NOVO: DISPARAR SINCRONIZAÇÃO DE NÚMEROS BLING (BACKGROUND) ---
            if ids_pedidos and options.get('persist_new_orders'):
                try:
                    from nistiprint_shared.services.celery_app import celery_app
                    # ids_pedidos pode vir como uma lista de IDs [id1, id2...] ou chunks [id1;id2, id101;id102...]
                    flat_ids = []
                    if isinstance(ids_pedidos, list):
                        for item in ids_pedidos:
                            if isinstance(item, str) and ';' in item:
                                flat_ids.extend(item.split(';'))
                            elif isinstance(item, (str, int)):
                                flat_ids.append(str(item))
                    
                    # Remover duplicatas e filtrar strings vazias
                    flat_ids = list(set([str(fid) for fid in flat_ids if fid]))
                    
                    sync_ids = options.get('print_order_resolution', {}).get('sync_ids') if options.get('print_orders') else flat_ids
                    if sync_ids:
                        print(f"[*] Consolidar API: Disparando sync de {len(sync_ids)} pedidos individuais com Bling...")
                        celery_app.send_task(
                            'tasks.consolidation_tasks.sync_orders_with_bling',
                            args=[sync_ids, channel_id, plataforma],
                            kwargs={}
                        )
                except Exception as sync_trigger_err:
                    print(f"⚠️ Erro ao disparar sync com Bling na API: {sync_trigger_err}")
            # ------------------------------------------------------------------

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
    return jsonify({
        'success': False,
        'error': 'O processamento assíncrono legado foi aposentado.',
        'redirect': '/despacho/arquivo',
    }), 410

    """
    Inicia processamento assíncrono de consolidação de pedidos.
    Retorna imediatamente com um ID para polling.
    """
    try:
        _file = request.files.get('file')
        
        # Parse form data
        start_date = request.form.get('start_date')
        end_datetime = request.form.get('end_datetime')
        print_orders = request.form.get('print-orders') == 'true'
        is_flex = request.form.get('is_flex') == 'true'
        mode = request.form.get('mode', 'legacy')

        context = _resolve_marketplace_context(request.form)

        if not _file or not (_file.filename.endswith('.xlsx') or _file.filename.endswith('.csv')):
            return jsonify({'error': 'Arquivo invalido. Apenas .xlsx e .csv sao aceitos.'}), 400

        plataforma = context['platform_name']
        channel_id = context.get('channel_id')

        # Salva arquivo temporário
        basedir = _ensure_temp_dir()
        safe_name = secure_filename(_file.filename or '')
        if not safe_name:
            raise ValueError('Nome de arquivo invalido.')
        filepath = os.path.join(basedir, f'{uuid4().hex}{os.path.splitext(safe_name)[1].lower()}')
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
            'platform': plataforma,
            'module_id': context['platform_key'],
            'print_orders': print_orders,
            'is_flex': is_flex,
            'persist_new_orders': request.form.get('persist_new_orders', 'true') == 'true',
            'channel_slug': context.get('channel_slug'),
            'channel_id': channel_id,
            'marketplace_integration_id': context.get('marketplace_integration_id'),
            'bling_integration_id': context.get('bling_integration_id'),
            'mode': mode,
            'file_path': filepath,
            'file_name': _file.filename
        }
        
        consolidacao_record = {
            'status': 'PENDENTE',
            'platform': plataforma,
            'channel_id': channel_id,
            'channel_slug': context.get('channel_slug'),
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




# ============================================================================
# Conferencia do arquivo contra a base
# ============================================================================
#
# A tela Consolidar recebe uma planilha exportada do painel do marketplace.
# Ela NAO cria demanda: a demanda nasce em um lugar so, a Torre de Despacho.
# O que ela faz e casar cada linha do arquivo com um pedido canonico pelo ID de
# origem e dizer, por no da torre, onde aqueles pedidos caem.
#
# A pergunta que o operador traz para esta tela e sempre a mesma: "o que esta
# no painel do marketplace ja chegou aqui?". Antes ela era respondida gerando
# uma demanda a partir do arquivo — o que dava uma resposta parecida e um lote
# que a torre nao reconhecia.


@consolidar_bp.route('/consolidar/casar', methods=['POST'])
@login_required
def casar_refs_com_base():
    """Casa IDs de origem de uma planilha com os pedidos canonicos.

    Body JSON: {"refs": ["2000018149273500", "260828G5DFPHPM", ...]}

    Devolve o casamento linha a linha e um agrupamento por no da torre
    (marketplace + modalidade), que e a chave que a Torre de Despacho usa para
    abrir um escopo.
    """
    try:
        body = request.get_json(silent=True) or {}
        refs = body.get('refs') or []
        if not isinstance(refs, list):
            return jsonify({'success': False, 'error': 'refs deve ser uma lista'}), 400

        # Normaliza aqui tambem: a planilha costuma trazer o ID como numero, e
        # um float do pandas ("2000018149273500.0") nao casa com nada.
        limpos = []
        for ref in refs:
            texto = str(ref if ref is not None else '').strip()
            if texto.endswith('.0'):
                texto = texto[:-2]
            if texto:
                limpos.append(texto)

        if not limpos:
            return jsonify({'success': True, 'data': {
                'total_refs': 0, 'encontrados': 0, 'nao_encontrados': [],
                'fora_da_torre': [], 'nos': [],
            }})

        from nistiprint_shared.database.supabase_db_service import supabase_db
        resultado = supabase_db.rpc('consolidar_casar_refs', {'p_refs': limpos}).execute()
        linhas = resultado.data or []

        nao_encontrados = [l['ref'] for l in linhas if not l.get('pedido_id')]
        # Casado mas fora da torre: ja despachado, cancelado, ou preso a uma
        # demanda publicada. E um resultado distinto de "nao encontrado" e
        # precisa aparecer como tal — os dois somados viram "faltando", e o
        # operador reimporta o que ja produziu.
        fora_da_torre = [
            {
                'ref': l['ref'],
                'pedido_id': l['pedido_id'],
                'numero_pedido': l.get('numero_pedido'),
                'despachado_em': l.get('despachado_em'),
            }
            for l in linhas
            if l.get('pedido_id') and not l.get('na_torre')
        ]

        nos = {}
        for linha in linhas:
            if not linha.get('pedido_id') or not linha.get('na_torre'):
                continue
            chave = (linha.get('marketplace_integration_id'), linha.get('modalidade_logistica_id'))
            no = nos.setdefault(chave, {
                'integration_id': linha.get('marketplace_integration_id'),
                'marketplace_nome': linha.get('marketplace_nome'),
                'modalidade_id': linha.get('modalidade_logistica_id'),
                'modalidade_nome': linha.get('modalidade_nome'),
                'qtd_pedidos': 0,
                'pedido_ids': [],
            })
            no['qtd_pedidos'] += 1
            no['pedido_ids'].append(linha['pedido_id'])

        ordenados = sorted(
            nos.values(),
            key=lambda n: (-n['qtd_pedidos'], n['marketplace_nome'] or '', n['modalidade_nome'] or ''),
        )

        return jsonify({'success': True, 'data': {
            'total_refs': len(limpos),
            'encontrados': len(limpos) - len(nao_encontrados),
            'nao_encontrados': nao_encontrados,
            'fora_da_torre': fora_da_torre,
            'nos': ordenados,
            'linhas': linhas,
        }})
    except Exception as exc:
        logger.error('Erro ao casar refs da planilha com a base: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500

# ============================================================================
# APOSENTADO — geracao automatica de rascunho (26/08/2026)
# ============================================================================
#
# Esta rota chamava consolidation_service.consolidar_pedido() pedido a pedido.
# Entre 27/06 e 16/07 ela produziu 39 rascunhos, 14 deles com zero ou um pedido:
# e a origem do "uma demanda por pedido". A task do Celery ja estava
# desabilitada, mas a rota continuava disparando a mesma logica sob demanda.
#
# O rascunho agora nasce do clique do operador na Torre de Despacho, que agrupa
# por marketplace, modalidade e prazo e consolida por titulo/SKU/variacao/miolo
# (despacho_lancar_escopo -> despacho_publicar_demanda).
#
# A rota permanece respondendo 410 em vez de sumir: um cliente antigo que ainda
# a chame precisa receber a explicacao, nao um 404 que parece indisponibilidade
# temporaria e convida a repetir a chamada.


@consolidar_bp.route('/consolidar/rascunhos/processar', methods=['POST'])
@login_required
def processar_rascunhos():
    """Aposentado. Rascunho e criado na Torre de Despacho."""
    return jsonify({
        'success': False,
        'error': 'endpoint_aposentado',
        'message': (
            'A geracao automatica de rascunhos foi encerrada em 26/08/2026. '
            'Monte o lote na Torre de Despacho: escolha o no (marketplace + '
            'modalidade), confira o total contra o painel do marketplace e '
            'publique.'
        ),
        'substituto': {
            'tela': '/despacho',
            'rpc_montar': 'despacho_lancar_escopo',
            'rpc_publicar': 'despacho_publicar_demanda',
        },
    }), 410
