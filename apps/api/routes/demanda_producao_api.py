from flask import request, jsonify, session
import json
import pytz
from datetime import datetime, timedelta
from constants import APP_TIMEZONE
from routes.auth import login_required, check_permission, get_current_user
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.unit_of_work import UnitOfWork
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from .demanda_producao_base import demanda_producao_api_bp

from nistiprint_shared.services.previsao_consumo_service import previsao_consumo_service

@demanda_producao_api_bp.route('/<string:demanda_id>/auditoria-consumo', methods=['GET'])
@login_required
def api_auditoria_consumo_demanda(demanda_id):
    try:
        demanda_res = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda_res:
            return jsonify({'success': False, 'message': 'Demanda não encontrada'}), 404
        
        internal_id = demanda_res['id']
        result = previsao_consumo_service.audit_consumption_for_demand(internal_id)
        return jsonify(result)
    except Exception as e:
        print(f"ERROR in api_auditoria_consumo_demanda: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/item/<int:item_id>/stock-history', methods=['GET'])
@check_permission('demanda_producao', 'ler')
def get_stock_history_for_item(item_id):
    try:
        history = demanda_producao_service.get_stock_history_for_item(item_id)
        return jsonify({'success': True, 'history': history}), 200
    except Exception as e:
        print(f"ERROR fetching stock history for item {item_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/retry-fila-estoque/<string:task_id>', methods=['POST'])
@login_required
def api_retry_fila_estoque(task_id):
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        from nistiprint_shared.utils.date_utils import get_now_iso
        
        res = supabase_db.table('fila_processamento_estoque').update({
            'status': 'PENDENTE',
            'tentativas': 0,
            'proxima_execucao_at': get_now_iso(),
            'mensagem_erro': None
        }).eq('id', task_id).execute()
        
        if not res.data:
            return jsonify({'success': False, 'message': 'Tarefa não encontrada'}), 404
            
        return jsonify({'success': True})
    except Exception as e:
        print(f"ERROR in api_retry_fila_estoque: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/', methods=['GET'])
def api_list_demandas():
    try:
        demandas = demanda_producao_service.get_all_demandas()

        def sort_key(d):
            modalidade = d.get('modalidade_logistica', 'STANDARD')
            is_express = modalidade == 'EXPRESS'
            priority = d.get('manual_priority_score') or 0
            data_entrega = d.get('data_entrega') or '9999-12-31'
            horario = d.get('deadline_final') or d.get('horario_coleta') or "23:59"
            
            return (not is_express, -int(priority), data_entrega, horario)
            
        demandas.sort(key=sort_key)

        return jsonify({'success': True, 'demandas': demandas})
    except Exception as e:
        import traceback
        print(f"ERROR in api_list_demandas: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<demanda_id>', methods=['GET'])
def api_get_demanda(demanda_id):
    try:
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            return jsonify({'success': False, 'message': 'Demanda não encontrada'}), 404

        return jsonify({'success': True, 'demanda': demanda})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_demanda: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/coletas', methods=['GET'])
def api_get_coletas_demanda(demanda_id):
    try:
        coletas = demanda_producao_service.get_coletas_da_demanda(demanda_id)
        return jsonify({'success': True, 'coletas': coletas})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_coletas_demanda: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/coletas/historico', methods=['GET'])
def api_get_historico_coletas_global():
    try:
        limit = request.args.get('limit', default=200, type=int)
        coletas = demanda_producao_service.get_historico_coletas_global(limit=limit)
        return jsonify({'success': True, 'coletas': coletas})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_historico_coletas_global: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/', methods=['POST'])
@login_required
def create_demanda_api():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400

        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'criar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem criar demandas.'}), 403

        nome_demanda = data.get('nome')
        canal_venda_id = data.get('canal_venda_id')
        data_entrega_str = data.get('data_entrega')
        itens = data.get('itens', [])
        horario_coleta_especifico = data.get('horario_coleta_especifico') or None
        data_finalizacao_prevista_str = data.get('data_finalizacao_prevista')
        observacoes = data.get('observacoes') or None
        tipo_demanda = data.get('tipo_demanda', 'PLATAFORMA')
        modalidade_logistica = data.get('modalidade_logistica', 'STANDARD')
        classificacao_cliente = data.get('classificacao_cliente', 'B2C')
        is_draft = data.get('is_draft', False)
        status = 'AGUARDANDO' if is_draft else 'EM_PRODUCAO'

        categoria_demanda = data.get('categoria_demanda')
        capacidade_requerida = data.get('capacidade_requerida')
        data_inicio_planejada = data.get('data_inicio_planejada')
        data_fim_planejada = data.get('data_fim_planejada')
        setores_envolvidos = data.get('setores_envolvidos')
        categoria_temporal = data.get('categoria_temporal')
        data_promessa_cliente = data.get('data_promessa_cliente')
        data_maxima_entrega = data.get('data_maxima_entrega')

        if not nome_demanda or not canal_venda_id or not data_entrega_str:
            return jsonify({'success': False, 'message': 'Nome, canal de venda e data de entrega são obrigatórios.'}), 400

        if not itens:
            return jsonify({'success': False, 'message': 'Pelo menos um item é necessário.'}), 400

        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
            if horario_coleta_especifico:
                if len(horario_coleta_especifico) > 5:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M:%S').time()
                else:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M').time()
                combined_dt = datetime.combine(data_entrega, h_time)
            else:
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            combined_dt_localized = tz.localize(combined_dt)

            if combined_dt_localized < now_local - timedelta(minutes=10):
                 return jsonify({'success': False, 'message': f'A data e horário de entrega ({combined_dt_localized.strftime("%d/%m %H:%M")}) não podem ser no passado.'}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': f'Formato de data ou horário inválido: {str(e)}'}), 400
        
        data_finalizacao_prevista = None
        if data_finalizacao_prevista_str:
            try:
                from dateutil.parser import parse
                data_finalizacao_prevista = parse(data_finalizacao_prevista_str)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Formato de data de finalização prevista inválido: {str(e)}'}), 400

        user_id = session.get('user_email', 'System')

        nova_demanda = demanda_producao_service.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data_entrega_str,
            lista_de_itens=itens,
            horario_coleta_especifico=horario_coleta_especifico,
            data_finalizacao_prevista=data_finalizacao_prevista,
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda=tipo_demanda,
            modalidade_logistica=modalidade_logistica,
            classificacao_cliente=classificacao_cliente,
            status=status,
            categoria_demanda=categoria_demanda,
            capacidade_requerida=capacidade_requerida,
            data_inicio_planejada=data_inicio_planejada,
            data_fim_planejada=data_fim_planejada,
            setores_envolvidos=setores_envolvidos,
            categoria_temporal=categoria_temporal,
            data_promessa_cliente=data_promessa_cliente,
            data_maxima_entrega=data_maxima_entrega
        )
        
        return jsonify({
            'success': True, 
            'message': 'Rascunho salvo com sucesso!' if is_draft else 'Demanda criada com sucesso!', 
            'demanda_id': nova_demanda.get('id')
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/empresas', methods=['POST'])
@login_required
def create_demanda_empresas_api():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400

        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'criar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem criar demandas.'}), 403

        nome_demanda = data.get('nome')
        canal_venda_id = data.get('canal_venda_id')
        data_entrega_str = data.get('data_entrega')
        itens = data.get('itens', [])
        horario_coleta_especifico = data.get('horario_coleta_especifico')
        data_finalizacao_prevista_str = data.get('data_finalizacao_prevista')
        observacoes = data.get('observacoes')
        modalidade_logistica = data.get('modalidade_logistica', 'STANDARD')
        classificacao_cliente = data.get('classificacao_cliente', 'B2B')
        
        empresa_cliente_nome = data.get('empresa_cliente_nome')
        empresa_wire_o_cor = data.get('empresa_wire_o_cor')
        empresa_elastico_cor = data.get('empresa_elastico_cor')
        empresa_interacao_status = data.get('empresa_interacao_status', 'Aguardando arte')
        empresa_pedido_plataforma_numero = data.get('empresa_pedido_plataforma_numero')
        empresa_responsavel_id = data.get('empresa_responsavel_id')
        empresa_responsavel_nome = data.get('empresa_responsavel_nome')

        is_draft = data.get('is_draft', False)
        status = 'AGUARDANDO' if is_draft else 'EM_PRODUCAO'

        if not nome_demanda or not canal_venda_id or not data_entrega_str or not empresa_cliente_nome:
            return jsonify({'success': False, 'message': 'Nome da demanda, canal de venda, data de entrega e nome da empresa são obrigatórios.'}), 400

        if not itens:
            return jsonify({'success': False, 'message': 'Pelo menos um item é necessário.'}), 400

        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
            if horario_coleta_especifico:
                if len(horario_coleta_especifico) > 5:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M:%S').time()
                else:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M').time()
                combined_dt = datetime.combine(data_entrega, h_time)
            else:
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            combined_dt_localized = tz.localize(combined_dt)

            if combined_dt_localized < now_local - timedelta(minutes=10):
                 return jsonify({'success': False, 'message': f'A data e horário de entrega ({combined_dt_localized.strftime("%d/%m %H:%M")}) não podem ser no passado.'}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': f'Formato de data ou horário inválido: {str(e)}'}), 400
        
        data_finalizacao_prevista = None
        if data_finalizacao_prevista_str:
            try:
                from dateutil.parser import parse
                data_finalizacao_prevista = parse(data_finalizacao_prevista_str)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Formato de data de finalização prevista inválido: {str(e)}'}), 400

        user_id = session.get('user_email', 'System')

        categoria_demanda = data.get('categoria_demanda')
        capacidade_requerida = data.get('capacidade_requerida')
        data_inicio_planejada = data.get('data_inicio_planejada')
        data_fim_planejada = data.get('data_fim_planejada')
        setores_envolvidos = data.get('setores_envolvidos')
        categoria_temporal = data.get('categoria_temporal')
        data_promessa_cliente = data.get('data_promessa_cliente')
        data_maxima_entrega = data.get('data_maxima_entrega')

        nova_demanda = demanda_producao_service.criar_demanda_empresas(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data_entrega_str,
            lista_de_itens=itens,
            horario_coleta_especifico=horario_coleta_especifico,
            data_finalizacao_prevista=data_finalizacao_prevista,
            observacoes=observacoes,
            user_id=user_id,
            modalidade_logistica=modalidade_logistica,
            classificacao_cliente=classificacao_cliente,
            empresa_cliente_nome=empresa_cliente_nome,
            empresa_wire_o_cor=empresa_wire_o_cor,
            empresa_elastico_cor=empresa_elastico_cor,
            empresa_interacao_status=empresa_interacao_status,
            empresa_pedido_plataforma_numero=empresa_pedido_plataforma_numero,
            empresa_responsavel_id=empresa_responsavel_id,
            empresa_responsavel_nome=empresa_responsavel_nome,
            status=status,
            categoria_demanda=categoria_demanda,
            capacidade_requerida=capacidade_requerida,
            data_inicio_planejada=data_inicio_planejada,
            data_fim_planejada=data_fim_planejada,
            setores_envolvidos=setores_envolvidos,
            categoria_temporal=categoria_temporal,
            data_promessa_cliente=data_promessa_cliente,
            data_maxima_entrega=data_maxima_entrega
        )
        
        return jsonify({
            'success': True, 
            'message': 'Rascunho salvo com sucesso!' if is_draft else 'Demanda de empresas criada com sucesso!', 
            'demanda_id': nova_demanda.get('id')
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>', methods=['PUT'])
@demanda_producao_api_bp.route('/<string:demanda_id>/atualizar-completo', methods=['PUT'])
@login_required
def atualizar_demanda_completa_api(demanda_id):
    try:
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'editar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem atualizar demandas.'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400

        itens = data.get('itens', [])
        if not itens:
            return jsonify({'success': False, 'message': 'Pelo menos um item é necessário.'}), 400

        is_draft = data.get('is_draft', False)
        
        updates = {
            'nome': data.get('nome'),
            'canal_venda_id': data.get('canal_venda_id'),
            'data_entrega': data.get('data_entrega'),
            'horario_coleta': data.get('horario_coleta_especifico'),
            'data_finalizacao_prevista': data.get('data_finalizacao_prevista'),
            'observacoes': data.get('observacoes'),
            'status': 'AGUARDANDO' if is_draft else 'EM_PRODUCAO',
            'tipo_demanda': data.get('tipo_demanda', 'PLATAFORMA'),
            'modalidade_logistica': data.get('modalidade_logistica', 'STANDARD'),
            'classificacao_cliente': data.get('classificacao_cliente', 'B2C'),

            'categoria_demanda': data.get('categoria_demanda'),
            'prioridade_tipo': data.get('prioridade_tipo'),
            'data_limite_execucao': data.get('data_limite_execucao'),
            'capacidade_requerida': data.get('capacidade_requerida'),
            'data_inicio_planejada': data.get('data_inicio_planejada'),
            'data_fim_planejada': data.get('data_fim_planejada'),
            'setores_envolvidos': data.get('setores_envolvidos'),
            'categoria_temporal': data.get('categoria_temporal'),
            'data_promessa_cliente': data.get('data_promessa_cliente'),
            'data_maxima_entrega': data.get('data_maxima_entrega')
        }

        if updates['tipo_demanda'] == 'B2B':
            updates.update({
                'empresa_cliente_nome': data.get('empresa_cliente_nome'),
                'empresa_wire_o_cor': data.get('empresa_wire_o_cor'),
                'empresa_elastico_cor': data.get('empresa_elastico_cor'),
                'empresa_interacao_status': data.get('empresa_interacao_status'),
                'empresa_pedido_plataforma_numero': data.get('empresa_pedido_plataforma_numero'),
                'empresa_responsavel_id': data.get('empresa_responsavel_id'),
                'empresa_responsavel_nome': data.get('empresa_responsavel_nome')
            })

        if updates['data_finalizacao_prevista']:
            try:
                from dateutil.parser import parse
                updates['data_finalizacao_prevista'] = parse(updates['data_finalizacao_prevista'])
            except:
                pass

        user_id = session.get('user_email', 'System')
        updated_demanda = demanda_producao_service.atualizar_demanda_completa(demanda_id, updates, itens, user_id)

        return jsonify({
            'success': True,
            'message': 'Demanda atualizada com sucesso!',
            'demanda': updated_demanda
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/publicar', methods=['POST'])
@login_required
def publicar_demanda_api(demanda_id):
    try:
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'editar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem publicar demandas.'}), 403

        user_id = session.get('user_email', 'System')
        updated_demanda = demanda_producao_service.publicar_demanda(demanda_id, user_id)
        
        return jsonify({
            'success': True,
            'message': 'Demanda publicada com sucesso!',
            'demanda': updated_demanda
        })
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/daily-summary', methods=['GET'])
def api_get_daily_summary():
    try:
        summary_data = demanda_producao_service.get_daily_production_summary()
        return jsonify({'success': True, 'summary': summary_data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/ativas', methods=['GET'])
def get_active_demandas():
    try:
        product_id = request.args.get('product_id')
        demandas_ativas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'], product_id=product_id)
        return jsonify({'success': True, 'demandas': demandas_ativas}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/atualizar', methods=['POST'])
@login_required
def update_item_progress(demanda_id, item_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    quantities_to_update = data.get('quantities', {})

    if not quantities_to_update:
        return jsonify({'success': False, 'message': 'Nenhuma quantidade para atualizar fornecida.'}), 400

    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    user_id = session.get('user_email', 'Unknown User')

    field_permissions = {
        'cpd': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'controle de produção': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'capas': ['capas_produzidas_qtd'],
        'miolos': ['miolos_prontos_retirada_qtd'],
        'expedição': ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrador': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrativo': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']
    }

    if not is_admin:
        normalized_setor = user_setor.strip().lower() if user_setor else ''
        allowed_fields = field_permissions.get(normalized_setor, [])

        if not allowed_fields:
            for key, value in field_permissions.items():
                if key.lower() == normalized_setor:
                    allowed_fields = value
                    break

        unauthorized_fields = [field for field in quantities_to_update.keys() if field not in allowed_fields]

        if unauthorized_fields:
            return jsonify({
                'success': False,
                'message': f'Acesso negado. O setor "{user_setor}" não tem permissão para alterar: {", ".join(unauthorized_fields)}'
            }), 403

    try:
        updated_item = demanda_producao_service.atualizar_progresso_item(demanda_id, item_id, quantities_to_update, user_id)
        return jsonify({'success': True, 'message': 'Progresso atualizado com sucesso!', 'item_id': updated_item['id']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao atualizar progresso: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/registrar-producao', methods=['POST'])
@login_required
def registrar_producao_incremental(demanda_id, item_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    producao_incremental = data.get('producao_incremental', {})
    origem_tipo = data.get('origem_tipo', 1)

    if not producao_incremental:
        return jsonify({'success': False, 'message': 'Dados de produção incremental não fornecidos.'}), 400

    if 'origem_tipo' not in data:
        is_removal = any(val < 0 for val in producao_incremental.values() if isinstance(val, (int, float)))
        origem_tipo = 2 if is_removal else 1

    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    user_id = session.get('user_email', 'Unknown User')

    if not is_admin:
        for field in producao_incremental.keys():
            if not permissao_service.has_permission(session.get('user_id'), 'campo_demanda', 'editar'):
                user_setor_lower = user_setor.strip().lower() if user_setor else ''
                field_permissions = {
                    'cpd': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
                    'controle de produção': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
                    'capas': ['capas_produzidas_qtd'],
                    'miolos': ['miolos_prontos_retirada_qtd'],
                    'expedição': ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
                    'administrador': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                                     'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
                    'administrativo': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                                     'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']
                }

                normalized_setor = user_setor_lower
                allowed_fields = field_permissions.get(normalized_setor, [])

                if not allowed_fields:
                    for key, value in field_permissions.items():
                        if key.lower() == normalized_setor:
                            allowed_fields = value
                            break

                unauthorized_fields = [field for field in producao_incremental.keys() if field not in allowed_fields]

                if unauthorized_fields:
                    return jsonify({
                        'success': False,
                        'message': f'Acesso negado. O setor "{user_setor}" não tem permissão para registrar produção para: {", ".join(unauthorized_fields)}'
                    }), 403

    try:
        retroactive_date = data.get('retroactive_date')
        correlation_id = data.get('correlation_id')
        
        updated_item = demanda_producao_service.registrar_producao_incremental(
            demanda_id, item_id, producao_incremental, user_id, 
            origem_tipo=origem_tipo,
            retroactive_date=retroactive_date,
            correlation_id=correlation_id
        )
        return jsonify({'success': True, 'message': 'Produção registrada com sucesso!', 'item_id': updated_item['id']}), 200

    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao registrar produção: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/itens/registrar-producao-lote', methods=['POST'])
@login_required
def registrar_producao_lote(demanda_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    updates = data.get('updates', [])
    origem_tipo = data.get('origem_tipo', 1)

    if not updates:
        return jsonify({'success': False, 'message': 'Dados de produção em lote não fornecidos.'}), 400

    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    user_id = session.get('user_email', 'Unknown User')

    field_permissions = {
        'cpd': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'controle de produção': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'capas': ['capas_produzidas_qtd'],
        'miolos': ['miolos_prontos_retirada_qtd'],
        'expedição': ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrador': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrativo': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']
    }

    if not is_admin:
        normalized_setor = user_setor.strip().lower() if user_setor else ''
        allowed_fields = field_permissions.get(normalized_setor, [])

        if not allowed_fields:
            for key, value in field_permissions.items():
                if key.lower() == normalized_setor:
                    allowed_fields = value
                    break

        for update in updates:
            producao_incremental = update.get('producao_incremental', {})
            unauthorized_fields = [field for field in producao_incremental.keys() if field not in allowed_fields]
            if unauthorized_fields:
                return jsonify({
                    'success': False,
                    'message': f'Acesso negado. O setor "{user_setor}" não tem permissão para alterar: {", ".join(unauthorized_fields)}'
                }), 403

    try:
        batch_results = demanda_producao_service.registrar_producao_lote(
            demanda_id, updates, user_id, 
            origem_tipo=origem_tipo,
            retroactive_date=data.get('retroactive_date'),
            correlation_id=data.get('correlation_id')
        )
        return jsonify({
            'success': True, 
            'message': f'{len(batch_results.get("results", []))} itens processados com sucesso!', 
            'results': batch_results.get('results', []),
            'results_count': len(batch_results.get('results', []))
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao registrar produção em lote: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/finalizar-parcial', methods=['POST'])
def finalizar_item_parcial_api(demanda_id, item_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    quantidade_parcial = data.get('quantidade_parcial')

    if not quantidade_parcial or quantidade_parcial <= 0:
        return jsonify({'success': False, 'message': 'Quantidade parcial inválida.'}), 400

    user_setor = session.get('user_setor')
    if not user_setor:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    allowed_sectors = ['Expedição', 'Administrador', 'Administrativo']
    if user_setor not in allowed_sectors:
        return jsonify({
            'success': False,
            'message': 'Acesso negado. Apenas Expedição e Administrativo podem finalizar itens.'
        }), 403

    try:
        user_id = session.get('user_email', 'System')
        updated_item = demanda_producao_service.finalizar_item_parcial(demanda_id, item_id, int(quantidade_parcial), user_id)
        return jsonify({'success': True, 'message': 'Item finalizado parcialmente com sucesso!', 'item_id': updated_item['id']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao finalizar item: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/finalizar', methods=['POST'])
def finalizar_item_api(demanda_id, item_id):
    try:
        updated_item = demanda_producao_service.finalizar_item(demanda_id, item_id)
        return jsonify({'success': True, 'message': 'Item finalizado com sucesso!', 'item_id': updated_item['id'], 'status_item': updated_item['status_item']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao finalizar item: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/reverter-finalizacao', methods=['POST'])
def reverter_finalizacao_item_api(demanda_id, item_id):
    try:
        user_setor = session.get('user_setor')
        user_is_admin = session.get('user_is_admin', False)

        allowed_sectors = ['Administrador', 'Administrativo', 'Controle de Produção']
        if not user_is_admin and user_setor not in allowed_sectors:
            return jsonify({
                'success': False,
                'message': f'Acesso negado. Apenas {", ".join(allowed_sectors)} podem reverter finalizações.'
            }), 403

        user_id = session.get('user_email', 'System')
        updated_item = demanda_producao_service.reverter_finalizacao_item(demanda_id, item_id, user_id)
        return jsonify({
            'success': True,
            'message': 'Finalização do item revertida com sucesso!',
            'item_id': updated_item['id'],
            'status_item': updated_item['status_item']
        }), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno ao reverter finalização: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/coletar', methods=['POST'])
def marcar_coletado_api(demanda_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400

        quantidade_coletar = data.get('quantidade_coletar')
        if quantidade_coletar is None:
            return jsonify({'success': False, 'message': 'Quantidade para coletar não fornecida.'}), 400

        user_id = session.get('user_email', 'System')
        demanda = demanda_producao_service.registrar_coleta_parcial(demanda_id, int(quantidade_coletar), user_id)
        
        return jsonify({'success': True, 'message': 'Coleta registrada com sucesso!', 'demanda': demanda})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/batch/coletar', methods=['POST'])
def marcar_lote_coletado_api():
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'success': False, 'message': 'Nenhum ID fornecido.'}), 400
        
        user_id = session.get('user_email', 'System')
        results = demanda_producao_service.marcar_lote_como_coletado(ids, user_id)
        return jsonify({'success': True, 'message': f'{len(results)} demandas marcadas como coletadas.', 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/finalizar_demanda', methods=['POST'])
def finalizar_demanda_api(demanda_id):
    try:
        user_id = session.get('user_email', 'System')
        demanda = demanda_producao_service.finalizar_demanda_completa(demanda_id, user_id)
        return jsonify({'success': True, 'message': 'Demanda finalizada com sucesso!', 'demanda': demanda})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/production-plan', methods=['GET'])
def get_production_plan():
    try:
        from datetime import datetime, timedelta
        from nistiprint_shared.services.production_planning_service import production_planning_service
        start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))
        plan_data = production_planning_service.get_production_plan(start_date, end_date)
        return jsonify({'success': True, 'plan': plan_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/gantt-data', methods=['GET'])
def get_gantt_data():
    try:
        from nistiprint_shared.services.production_planning_service import production_planning_service
        demanda_ids_param = request.args.get('demanda_ids')
        demanda_ids = demanda_ids_param.split(',') if demanda_ids_param else None
        gantt_data = production_planning_service.get_gantt_data(demanda_ids)
        return jsonify({'success': True, 'gantt_data': gantt_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/resource-allocation-dashboard', methods=['GET'])
def get_resource_allocation_dashboard():
    try:
        from nistiprint_shared.services.production_planning_service import production_planning_service
        dashboard_data = production_planning_service.get_resource_allocation_dashboard()
        return jsonify({'success': True, 'dashboard': dashboard_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/production-forecast', methods=['GET'])
def get_production_forecast():
    try:
        from nistiprint_shared.services.production_planning_service import production_planning_service
        period_days = request.args.get('period_days', 30, type=int)
        forecast_data = production_planning_service.forecast_production_needs(period_days)
        return jsonify({'success': True, 'forecast': forecast_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/calendar-data', methods=['GET'])
def get_calendar_data():
    try:
        from datetime import datetime, timedelta
        from nistiprint_shared.services.calendar_service import calendar_service
        start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))
        calendar_data = calendar_service.get_calendar_data(start_date, end_date)
        return jsonify({'success': True, 'events': calendar_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/validate-schedule-conflict', methods=['POST'])
def validate_schedule_conflict():
    try:
        from nistiprint_shared.services.calendar_service import calendar_service
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        demanda_id = data.get('demanda_id')
        new_schedule_dates = data.get('schedule_dates', {})
        if not demanda_id:
            return jsonify({'success': False, 'message': 'Demanda ID is required'}), 400
        conflict_validation = calendar_service.validate_scheduling_conflict(demanda_id, new_schedule_dates)
        return jsonify({'success': True, 'validation': conflict_validation})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/update-demand-schedule/<string:demanda_id>', methods=['PUT'])
def update_demand_schedule(demanda_id):
    try:
        from nistiprint_shared.services.calendar_service import calendar_service
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        user_id = session.get('user_email', 'System')
        updated_demanda = calendar_service.update_demand_schedule(demanda_id, data, user_id)
        return jsonify({'success': True, 'demanda': updated_demanda})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/fila-estoque', methods=['GET'])
def api_get_fila_estoque():
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        res = supabase_db.table('fila_processamento_estoque')\
            .select("*, itens_demanda(sku, descricao)")\
            .order('created_at', desc=True)\
            .limit(100)\
            .execute()
        queue_data = []
        if res.data:
            for row in res.data:
                item_info = row.pop('itens_demanda', None)
                row['item'] = item_info
                queue_data.append(row)
        return jsonify({'success': True, 'queue': queue_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/processar-fila-estoque', methods=['POST'])
def api_processar_fila_estoque():
    try:
        limit = request.args.get('limit', default=20, type=int)
        count = demanda_producao_service.processar_fila_estoque(limit=limit)
        return jsonify({'success': True, 'processed_count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/dashboard-totals', methods=['GET'])
def get_dashboard_totals():
    try:
        from datetime import date
        from nistiprint_shared.database.supabase_db_service import supabase_db
        today = date.today()
        logs_res = supabase_db.table('logs_producao_diaria')\
            .select("*")\
            .eq('data', today.isoformat())\
            .neq('deleted', True)\
            .execute()
        sector_totals = {'CPD': 0, 'Capas': 0, 'Miolos': 0, 'Expedição': 0}
        if logs_res.data:
            for log in logs_res.data:
                qty = float(log.get('quantidade_produzida', 0))
                metadata = log.get('detalhes_producao') or {}
                campo = metadata.get('campo')
                if campo:
                    if campo in ['capas_impressas_qtd', 'capas_prontas_retirada_qtd']:
                        sector_totals['CPD'] += qty
                    elif campo == 'capas_produzidas_qtd':
                        sector_totals['Capas'] += qty
                    elif campo == 'miolos_prontos_retirada_qtd':
                        sector_totals['Miolos'] += qty
                    elif campo in ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']:
                        sector_totals['Expedição'] += qty
        demand_totals = {'today': 0, 'future': 0}
        all_demandas = demanda_producao_service.get_all_demandas()
        for demanda in all_demandas:
            data_entrega_str = demanda.get('data_entrega')
            if data_entrega_str:
                try:
                    from datetime import datetime
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                    if data_entrega == today:
                        demand_totals['today'] += 1
                    elif data_entrega > today:
                        demand_totals['future'] += 1
                except ValueError:
                    pass
        return jsonify({'success': True, 'sector_totals': sector_totals, 'demand_totals': demand_totals})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/dashboard-summary', methods=['GET'])
def api_get_dashboard_summary():
    try:
        summary_data = demanda_producao_service.get_dashboard_summary()
        return jsonify({'success': True, **summary_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/consolidado', methods=['GET'])
def api_get_consolidado():
    try:
        trilha = request.args.get('trilha')
        agrupado = request.args.get('agrupado', 'true').lower() == 'true'
        if agrupado:
            dados = demanda_producao_service.get_consolidado_agrupado_por_sku(trilha=trilha)
        else:
            dados = demanda_producao_service.get_consolidado_producao(trilha=trilha)
        return jsonify({'success': True, 'data': dados})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/ativas-por-item/<string:produto_id>', methods=['GET'])
def api_get_ativas_por_item(produto_id):
    try:
        demandas = demanda_producao_service.get_demandas_ativas_por_item(produto_id)
        return jsonify({'success': True, 'demandas': demandas})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/retirar-expedicao', methods=['POST'])
@login_required
def api_registrar_retirada_expedicao(demanda_id, item_id):
    try:
        data = request.get_json()
        quantidade = int(data.get('quantidade', 1))
        user_id = session.get('user_email', 'System')
        updated_item = demanda_producao_service.registrar_retirada_expedicao(demanda_id, item_id, quantidade, user_id)
        return jsonify({'success': True, 'message': 'Retirada registrada com sucesso!', 'data': updated_item})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/prioritized', methods=['GET'])
def api_get_prioritized_demandas():
    try:
        limit = request.args.get('limit', type=int, default=50)
        prioritized_items = demanda_producao_service.get_prioritized_demandas(limit=limit)
        return jsonify({'success': True, 'prioritized_items': prioritized_items})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/demanda/<demanda_id>/detalhes', methods=['PUT'])
@login_required
def api_update_demanda_details(demanda_id):
    try:
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'editar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem atualizar detalhes da demanda.'}), 403
        data = request.get_json()
        user_id = session.get('user_email', 'System')
        updated_demanda = demanda_producao_service.update_demanda_details(demanda_id, data, user_id)
        canal_id = updated_demanda.get('canal_venda_id')
        if canal_id:
            try:
                canal = canal_venda_service.get_by_id(canal_id)
                if canal:
                    updated_demanda['canal_venda_color'] = canal.get('color', '#007bff')
            except Exception:
                pass
        return jsonify({'success': True, 'demanda': updated_demanda})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/registrar-saida', methods=['POST'])
def registrar_saida_distribuida():
    data = request.get_json()
    distributions = data.get('distributions')
    product_id = data.get('product_id')
    total_quantity = data.get('quantity')
    production_date_str = data.get('date')
    demanda_id = data.get('demanda_id')
    update_demand = data.get('update_demand', True)
    sincrono = data.get('sincrono', False)
    if not all([distributions, product_id, total_quantity, production_date_str]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400
    try:
        user_id = session.get('user_id')
        production_date = datetime.strptime(production_date_str, '%Y-%m-%d').date()
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        saldo = estoque_service.get_saldo_atual(product_id, deposito_id)
        if saldo['quantidade_disponivel'] < float(total_quantity):
             return jsonify({'success': False, 'error': f"Saldo insuficiente. Disponível: {saldo['quantidade_disponivel']}, Solicitado: {total_quantity}"}), 400
        usuario = get_current_user()
        user_context = {'id': usuario['id'], 'setor_id': usuario['setor_id'], 'setor_nome': usuario['setor_nome'], 'is_admin': usuario['is_admin']}
        with UnitOfWork(user_id=user_id) as uow:
            origem_tipo_saida = None if sincrono else 1
            uow.execute_in_transaction(estoque_service.registrar_saida, product_id, deposito_id, total_quantity, f"Saída distribuída de miolos para demandas - {production_date_str}", user_id, user_context=user_context, documento_referencia=demanda_id, origem_tipo=origem_tipo_saida)
            if update_demand:
                uow.execute_in_transaction(demanda_producao_service.registrar_saida_item_distribuida, distributions, product_id, user_id)
                if not sincrono:
                    for dist in distributions:
                        item_id = dist.get('item_id')
                        qty = dist.get('quantidade')
                        if item_id and qty:
                             uow.execute_in_transaction(demanda_producao_service.agendar_processamento_estoque, demanda_id, item_id, 'miolos_prontos_retirada_qtd', float(qty), user_id)
            uow.execute_in_transaction(daily_production_log_service.create_log, production_date, product_id, f"Produto {product_id}", -abs(total_quantity), None, [], user_id, metadata={'demanda_id': demanda_id, 'sincrono': sincrono})
            uow.log_audit_event('SAIDA_DISTRIBUIDA_DEMANDA', {'product_id': product_id, 'total_quantity': total_quantity, 'production_date': production_date_str, 'distributions': distributions})
        new_daily_removed = daily_production_log_service.get_total_removed_for_product_on_date(product_id, production_date)
        return jsonify({'success': True, 'message': 'Saída distribuída registrada com sucesso!' if not sincrono else 'Saída distribuída processada em tempo real!', 'new_daily_removed': new_daily_removed}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/monitoring/overview', methods=['GET'])
def get_monitoring_overview():
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        stock_queue_res = supabase_db.table('fila_processamento_estoque').select('status').execute()
        stock_stats = {'PENDENTE': 0, 'PROCESSANDO': 0, 'ERRO': 0, 'CONCLUIDO': 0}
        for item in stock_queue_res.data:
            status = item.get('status')
            if status in stock_stats: stock_stats[status] += 1
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        consolidations_res = supabase_db.table('consolidacoes_pedido').select('status').gte('created_at', yesterday).execute()
        consolidation_stats = {'PRONTO': 0, 'PROCESSANDO': 0, 'ERRO': 0, 'PENDENTE': 0}
        for item in consolidations_res.data:
            status = item.get('status')
            if status in consolidation_stats: consolidation_stats[status] += 1
        system_tasks_res = supabase_db.table('task_execution_logs').select('status').gte('created_at', yesterday).execute()
        system_task_stats = {'COMPLETED': 0, 'PROCESSING': 0, 'FAILED': 0, 'PENDING': 0}
        for item in system_tasks_res.data:
            status = item.get('status')
            if status in system_task_stats: system_task_stats[status] += 1
        return jsonify({'success': True, 'stats': {'stock': stock_stats, 'consolidations': consolidation_stats, 'system_tasks': system_task_stats}})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/monitoring/system-tasks', methods=['GET'])
def get_system_tasks():
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        limit = request.args.get('limit', 50, type=int)
        res = supabase_db.table('task_execution_logs').select('*').order('created_at', desc=True).limit(limit).execute()
        return jsonify({'success': True, 'tasks': res.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/miolo-demand-summary', methods=['GET'])
def get_miolo_demand_summary():
    try:
        all_demandas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'])
        miolo_summary = {}
        demanda_ids = [d['id'] for d in all_demandas]
        itens_mapping = demanda_producao_service.get_items_for_multiple_demandas([str(id) for id in demanda_ids])
        for demanda in all_demandas:
            did_str = str(demanda['id'])
            itens = itens_mapping.get(did_str, [])
            for item in itens:
                miolo_name = item.get('miolo_name')
                miolo_id = item.get('id_produto_miolo')
                if miolo_name:
                    key = str(miolo_id) if miolo_id else miolo_name
                    quantity = item.get('quantidade_total', 0)
                    pronto = item.get('miolos_prontos_retirada_qtd', 0) or 0
                    faltante = max(0, quantity - pronto)
                    if faltante <= 0: continue
                    if key not in miolo_summary:
                        miolo_summary[key] = {'name': miolo_name, 'id': miolo_id, 'quantity': 0, 'quantity_pending': 0, 'demandas_map': {}}
                    miolo_summary[key]['quantity'] += quantity
                    miolo_summary[key]['quantity_pending'] += faltante
                    if did_str not in miolo_summary[key]['demandas_map']:
                        miolo_summary[key]['demandas_map'][did_str] = {'demanda_id': demanda['id'], 'demanda_nome': demanda.get('nome') or demanda.get('descricao'), 'quantidade_total': 0, 'quantidade_faltante': 0, 'data_entrega': demanda['data_entrega']}
                    miolo_summary[key]['demandas_map'][did_str]['quantidade_total'] += quantity
                    miolo_summary[key]['demandas_map'][did_str]['quantidade_faltante'] += faltante
        summary_list = list(miolo_summary.values())
        for miolo in summary_list:
            miolo['demandas'] = list(miolo['demandas_map'].values())
            miolo['demandas'].sort(key=lambda x: x['data_entrega'] or '9999-12-31')
            del miolo['demandas_map']
            miolo['quantity'] = miolo['quantity_pending']
        summary_list.sort(key=lambda x: x['name'])
        return jsonify({'success': True, 'summary': summary_list})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/capa-demand-info', methods=['GET'])
def get_capa_demand_info():
    try:
        all_demandas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'])
        capa_summary = {}
        demanda_ids = [d['id'] for d in all_demandas]
        itens_mapping = demanda_producao_service.get_items_for_multiple_demandas([str(id) for id in demanda_ids])
        for demanda in all_demandas:
            did_str = str(demanda['id'])
            itens = itens_mapping.get(did_str, [])
            for item in itens:
                if not item.get('produto_id'): continue
                key = str(item['produto_id'])
                quantity = item.get('quantidade_total', 0)
                pronto = item.get('capas_produzidas_qtd', 0) or item.get('capas_prontas_retirada_qtd', 0) or 0
                faltante = max(0, quantity - pronto)
                if faltante <= 0: continue
                if key not in capa_summary:
                    capa_summary[key] = {'name': item.get('item_descricao') or item.get('descricao'), 'sku': item.get('sku'), 'id': item.get('produto_id'), 'variacao': item.get('variacao'), 'miolo_name': item.get('miolo_name'), 'quantity': 0, 'quantity_pending': 0, 'demandas_map': {}}
                capa_summary[key]['quantity'] += quantity
                capa_summary[key]['quantity_pending'] += faltante
                if did_str not in capa_summary[key]['demandas_map']:
                    capa_summary[key]['demandas_map'][did_str] = {'demanda_id': demanda['id'], 'demanda_nome': demanda.get('nome') or demanda.get('descricao'), 'quantidade_total': 0, 'quantidade_faltante': 0, 'data_entrega': demanda['data_entrega']}
                capa_summary[key]['demandas_map'][did_str]['quantidade_total'] += quantity
                capa_summary[key]['demandas_map'][did_str]['quantidade_faltante'] += faltante
        summary_list = []
        for c_key, c_data in capa_summary.items():
            c_data['demandas'] = list(c_data['demandas_map'].values())
            c_data['demandas'].sort(key=lambda x: x.get('data_entrega', ''))
            del c_data['demandas_map']
            c_data['quantity'] = c_data['quantity_pending']
            summary_list.append(c_data)
        summary_list.sort(key=lambda x: x.get('sku') or x['name'])
        return jsonify({'success': True, 'summary': summary_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/products/<int:product_id>/default-miolo', methods=['GET'])
def get_default_miolo_for_product(product_id):
    try:
        from nistiprint_shared.services.file_processors import get_miolo_from_bom
        miolo_nome, id_produto_miolo = get_miolo_from_bom(product_id)
        if miolo_nome and id_produto_miolo:
            return jsonify({'success': True, 'miolo': {'id': id_produto_miolo, 'nome': miolo_nome}})
        else:
            return jsonify({'success': True, 'miolo': None, 'message': 'Nenhum miolo padrão encontrado'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/<demanda_id>', methods=['DELETE'])
@login_required
def delete_demanda_api(demanda_id):
    try:
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'excluir'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem deletar demandas.'}), 403
        user_id = session.get('user_email', 'System')
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            return jsonify({'success': False, 'message': 'Demanda não encontrada.'}), 404
        demanda_producao_service.deletar_demanda(demanda_id, user_id)
        return jsonify({'success': True, 'message': f'Demanda "{demanda.get("nome", "")}" deletada com sucesso!'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500


# ============================================================================
# ENDPOINT SÍNCRONO SIMPLIFICADO (BYPASS EVENT SOURCING)
# ============================================================================
# Para operações críticas que precisam de resposta imediata
# Não usa fila de processamento de estoque
# ============================================================================

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/producao-sincrona', methods=['POST'])
@login_required
def registrar_producao_sincrona(demanda_id, item_id):
    """
    Registra produção de forma SÍNCRONA e SIMPLIFICADA.
    
    Diferenças do endpoint normal:
    - NÃO usa fila de processamento de estoque (fila_processamento_estoque)
    - NÃO cria eventos imutáveis (eventos_producao_v2)
    - Atualiza diretamente os campos de progresso
    - Registra apenas movimentação básica de estoque
    - Resposta imediata (<500ms)
    
    Use este endpoint para:
    - Operações críticas que não podem falhar
    - Testes e debug
    - Ambiente de desenvolvimento
    
    Para produção em massa, use o endpoint normal (registrar-producao-lote)
    que processa assincronamente via fila.
    
    Payload:
    {
        "producao_incremental": {
            "capas_impressas_qtd": 10,
            "miolos_prontos_retirada_qtd": 5
        }
    }
    """
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    producao_incremental = data.get('producao_incremental', {})

    if not producao_incremental:
        return jsonify({'success': False, 'message': 'Dados de produção incremental não fornecidos.'}), 400

    user_id = session.get('user_email', 'System')
    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    # Validação simplificada de permissões
    field_permissions = {
        'cpd': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'controle de produção': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd'],
        'capas': ['capas_produzidas_qtd'],
        'miolos': ['miolos_prontos_retirada_qtd'],
        'expedição': ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrador': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'administrativo': ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                         'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']
    }

    if not is_admin:
        normalized_setor = user_setor.strip().lower() if user_setor else ''
        allowed_fields = field_permissions.get(normalized_setor, [])

        if not allowed_fields:
            for key, value in field_permissions.items():
                if key.lower() == normalized_setor:
                    allowed_fields = value
                    break

        unauthorized_fields = [field for field in producao_incremental.keys() if field not in allowed_fields]
        if unauthorized_fields:
            return jsonify({
                'success': False,
                'message': f'Acesso negado. O setor "{user_setor}" não pode alterar: {", ".join(unauthorized_fields)}'
            }), 403

    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        from nistiprint_shared.utils.date_utils import get_now_iso
        from datetime import datetime

        # 1. Buscar item atual
        item_res = supabase_db.table('itens_demanda').select('*').eq('id', item_id).single().execute()
        if not item_res.data:
            return jsonify({'success': False, 'message': 'Item não encontrado'}), 404

        item = item_res.data

        # 2. Atualizar campos de progresso diretamente (síncrono)
        updates = {'updated_at': get_now_iso()}
        for campo, valor in producao_incremental.items():
            if campo in ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                        'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd',
                        'finalizados_qtd']:
                current = float(item.get(campo, 0) or 0)
                updates[campo] = max(0, current + valor)

        # 3. Executar atualização direta
        supabase_db.table('itens_demanda').update(updates).eq('id', item_id).execute()

        # 4. Registrar log simplificado (apenas para auditoria básica)
        try:
            supabase_db.table('daily_production_log').insert({
                'demanda_id': int(demanda_id) if demanda_id.isdigit() else None,
                'item_id': int(item_id) if item_id.isdigit() else None,
                'produto_id': item.get('produto_id'),
                'quantidade': sum(producao_incremental.values()),
                'tipo_operacao': 'PRODUCAO_SINCRONA',
                'usuario': user_id,
                'setor': user_setor,
                'metadata': {'campos': producao_incremental, 'sincrono': True},
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as log_err:
            # Log de auditoria é opcional, não falha a operação
            print(f"Aviso: Não foi possível registrar log de auditoria: {log_err}")

        # 5. Buscar item atualizado para retornar
        updated_item_res = supabase_db.table('itens_demanda').select('*').eq('id', item_id).single().execute()
        updated_item = updated_item_res.data if updated_item_res.data else item

        return jsonify({
            'success': True,
            'message': 'Produção registrada com sucesso (modo síncrono)!',
            'item': updated_item,
            'modo': 'sincrono'
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro ao registrar produção síncrona: {str(e)}'}), 500


@demanda_producao_api_bp.route('/<string:demanda_id>/producao-sincrona-lote', methods=['POST'])
@login_required
def registrar_producao_sincrona_lote(demanda_id):
    """
    Registra produção em lote de forma SÍNCRONA e SIMPLIFICADA.
    
    Payload:
    {
        "updates": [
            {
                "item_id": "123",
                "producao_incremental": {
                    "capas_impressas_qtd": 10
                }
            },
            {
                "item_id": "124",
                "producao_incremental": {
                    "miolos_prontos_retirada_qtd": 5
                }
            }
        ]
    }
    
    Retorna resultado de cada item processado.
    """
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    updates = data.get('updates', [])

    if not updates:
        return jsonify({'success': False, 'message': 'Nenhuma atualização fornecida.'}), 400

    user_id = session.get('user_email', 'System')
    results = []
    errors = []

    for update in updates:
        item_id = update.get('item_id')
        producao_incremental = update.get('producao_incremental', {})

        if not item_id or not producao_incremental:
            continue

        # Chamar endpoint síncrono individual internamente
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db
            from nistiprint_shared.utils.date_utils import get_now_iso
            from datetime import datetime

            # Atualização direta
            item_res = supabase_db.table('itens_demanda').select('*').eq('id', item_id).single().execute()
            if not item_res.data:
                errors.append({'item_id': item_id, 'error': 'Item não encontrado'})
                continue

            item = item_res.data
            updates_dict = {'updated_at': get_now_iso()}
            
            for campo, valor in producao_incremental.items():
                if campo in ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
                            'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd',
                            'finalizados_qtd']:
                    current = float(item.get(campo, 0) or 0)
                    updates_dict[campo] = max(0, current + valor)

            supabase_db.table('itens_demanda').update(updates_dict).eq('id', item_id).execute()

            # Log simplificado
            try:
                supabase_db.table('daily_production_log').insert({
                    'demanda_id': int(demanda_id) if demanda_id.isdigit() else None,
                    'item_id': int(item_id) if item_id.isdigit() else None,
                    'produto_id': item.get('produto_id'),
                    'quantidade': sum(producao_incremental.values()),
                    'tipo_operacao': 'PRODUCAO_SINCRONA_LOTE',
                    'usuario': user_id,
                    'metadata': {'campos': producao_incremental, 'sincrono': True, 'lote': True},
                    'created_at': datetime.utcnow().isoformat()
                }).execute()
            except:
                pass  # Log opcional

            results.append({'item_id': item_id, 'success': True})

        except Exception as e:
            errors.append({'item_id': item_id, 'error': str(e)})

    return jsonify({
        'success': True,
        'message': f'{len(results)} itens processados, {len(errors)} erros',
        'results': results,
        'errors': errors,
        'modo': 'sincrono_lote'
    }), 200


# ============================================================================
# ROTAS DE SUGESTÕES E OVERRIDES (Nova Arquitetura)
# ============================================================================

from nistiprint_shared.services.demandas_sugestoes_service import DemandasSugestoesService
from nistiprint_shared.services.demandas_override_service import DemandasOverrideService


@demanda_producao_api_bp.route('/sugestoes', methods=['POST'])
@login_required
def get_sugestoes_demanda():
    """
    Calcula sugestões de valores para criação de demanda.
    
    Payload:
    {
        "canal_venda_id": 1,
        "tipo_demanda": "PLATAFORMA",
        "data_entrega": "2026-04-15"  # Opcional
    }
    
    Response:
    {
        "success": true,
        "sugestoes": {
            "horario_coleta": "14:00",
            "modalidade_logistica": "STANDARD",
            "data_limite_execucao": "2026-04-13",
            "is_flex": false,
            "fulfillment": false,
            "prazo_dias": 2,
            "horario_limite": "15:00",
            "regra_origem": "regras_logisticas_canal",
            "alertas": []
        }
    }
    """
    try:
        data = request.get_json() or {}
        
        canal_venda_id = data.get('canal_venda_id')
        if not canal_venda_id:
            return jsonify({
                'success': False,
                'message': 'canal_venda_id é obrigatório'
            }), 400
        
        tipo_demanda = data.get('tipo_demanda', 'PLATAFORMA')
        data_entrega_str = data.get('data_entrega')
        
        # Converter data_entrega se fornecido
        from datetime import datetime
        data_entrega = None
        if data_entrega_str:
            try:
                data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        # Calcular sugestões
        sugestoes = DemandasSugestoesService.calcular_sugestoes(
            canal_venda_id=canal_venda_id,
            tipo_demanda=tipo_demanda,
            data_entrega=data_entrega
        )
        
        return jsonify({
            'success': True,
            'sugestoes': sugestoes
        }), 200
        
    except Exception as e:
        print(f"ERROR in get_sugestoes_demanda: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@demanda_producao_api_bp.route('/validar-override', methods=['POST'])
@login_required
def validar_override():
    """
    Valida se um override é compatível com as regras do canal.
    
    Payload:
    {
        "campo": "horario_coleta",
        "valor_alterado": "16:00",
        "canal_venda_id": 1
    }
    
    Response:
    {
        "success": true,
        "validacao": {
            "valid": true,
            "alertas": ["Horário após limite de coleta (15:00)"],
            "bloqueios": []
        }
    }
    """
    try:
        data = request.get_json() or {}
        
        campo = data.get('campo')
        valor_alterado = data.get('valor_alterado')
        canal_venda_id = data.get('canal_venda_id')
        
        if not all([campo, valor_alterado, canal_venda_id]):
            return jsonify({
                'success': False,
                'message': 'campo, valor_alterado e canal_venda_id são obrigatórios'
            }), 400
        
        # Validar override
        validacao = DemandasSugestoesService.validar_override(
            campo=campo,
            valor_alterado=valor_alterado,
            canal_venda_id=canal_venda_id
        )
        
        return jsonify({
            'success': True,
            'validacao': validacao
        }), 200
        
    except Exception as e:
        print(f"ERROR in validar_override: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@demanda_producao_api_bp.route('/<string:demanda_id>/overrides', methods=['GET'])
@login_required
def get_overrides_demanda(demanda_id):
    """
    Busca todos os overrides de uma demanda.
    
    Response:
    {
        "success": true,
        "overrides": [
            {
                "id": 1,
                "campo": "horario_coleta",
                "valor_original": "14:00",
                "valor_alterado": "16:00",
                "justificativa": "Coleta extra solicitada",
                "justificativa_tipo": "COLETA_ALTERNATIVA",
                "usuario_nome": "João Silva",
                "contexto_origem": "PLANILHA",
                "created_at": "2026-04-01T10:30:00Z"
            }
        ]
    }
    """
    try:
        # Converter demanda_id para int se for numérico
        try:
            demanda_id_int = int(demanda_id)
        except ValueError:
            # Se for UUID, buscar ID numérico primeiro
            from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
            demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
            if not demanda:
                return jsonify({
                    'success': False,
                    'message': 'Demanda não encontrada'
                }), 404
            demanda_id_int = demanda['id']
        
        # Buscar overrides
        overrides = DemandasOverrideService.get_overrides(demanda_id_int)
        
        return jsonify({
            'success': True,
            'overrides': overrides
        }), 200
        
    except Exception as e:
        print(f"ERROR in get_overrides_demanda: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@demanda_producao_api_bp.route('/<string:demanda_id>/overrides', methods=['POST'])
@login_required
def create_override_demanda(demanda_id):
    """
    Cria um novo override para uma demanda.
    
    Payload:
    {
        "campo": "horario_coleta",
        "valor_original": "14:00",
        "valor_alterado": "16:00",
        "justificativa": "Coleta extra solicitada pela plataforma",
        "justificativa_tipo": "COLETA_ALTERNATIVA",
        "contexto_origem": "PLANILHA"  # Opcional, default: DIRETA
    }
    """
    try:
        # Converter demanda_id para int
        try:
            demanda_id_int = int(demanda_id)
        except ValueError:
            from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
            demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
            if not demanda:
                return jsonify({
                    'success': False,
                    'message': 'Demanda não encontrada'
                }), 404
            demanda_id_int = demanda['id']
        
        data = request.get_json() or {}
        
        # Obter usuário atual
        usuario_id = None
        try:
            usuario_atual = get_current_user()
            if usuario_atual:
                usuario_id = usuario_atual.get('id')
        except:
            pass
        
        # Registrar override
        override = DemandasOverrideService.registrar(
            demanda_id=demanda_id_int,
            campo=data.get('campo'),
            valor_original=data.get('valor_original'),
            valor_alterado=data.get('valor_alterado'),
            justificativa=data.get('justificativa'),
            justificativa_tipo=data.get('justificativa_tipo'),
            usuario_id=usuario_id,
            contexto_origem=data.get('contexto_origem', 'DIRETA')
        )
        
        if override:
            return jsonify({
                'success': True,
                'override': override
            }), 201
        else:
            return jsonify({
                'success': False,
                'message': 'Falha ao criar override. Verifique os dados.'
            }), 400
        
    except Exception as e:
        print(f"ERROR in create_override_demanda: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@demanda_producao_api_bp.route('/justificativas-tipo', methods=['GET'])
@login_required
def get_justificativas_tipo():
    """
    Retorna lista de justificativas pré-definidas para overrides.
    
    Response:
    {
        "success": true,
        "justificativas": [
            {
                "value": "COLETA_ALTERNATIVA",
                "label": "Coleta Alternativa",
                "description": "Plataforma definiu horário alternativo no dia"
            }
        ]
    }
    """
    try:
        justificativas = DemandasSugestoesService.get_justificativas_tipo()
        
        return jsonify({
            'success': True,
            'justificativas': justificativas
        }), 200
        
    except Exception as e:
        print(f"ERROR in get_justificativas_tipo: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
