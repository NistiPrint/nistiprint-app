from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session
import json
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.unit_of_work import UnitOfWork
from nistiprint_shared.services.auditoria_service import auditoria_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service
from datetime import datetime, date, timedelta # Needed for data_criacao formatting in template
from routes.auth import login_required, check_permission
import pytz
from constants import APP_TIMEZONE

demanda_producao_bp = Blueprint('demanda_producao', __name__, url_prefix='/producao/demanda')
demanda_producao_api_bp = Blueprint('demanda_producao_api', __name__, url_prefix='/api/v2/demanda_producao')

@demanda_producao_bp.route('/')
@login_required
@check_permission('demanda_producao', 'ler')
def list_demandas():
    try:
        demandas = demanda_producao_service.get_all_demandas()
    except Exception as e:
        flash(f'Erro ao carregar as demandas: {e}', 'danger')
        demandas = []
    return render_template('producao/demanda_list.html', demandas=demandas)

@demanda_producao_bp.route('/nova', methods=['GET', 'POST'])
@login_required
@check_permission('demanda_producao', 'criar')
def create_demanda():
    if request.method == 'POST':
        form_data = request.form

        # Handle pre-filled form from results page
        if 'items_json' in form_data:
            try:
                items = json.loads(form_data['items_json'])
                products, _ = product_service.get_products(per_page=10000) 
                canais_venda = canal_venda_service.get_all()
                return render_template('producao/demanda_form.html', products=products, canais_venda=canais_venda, items=items)
            except (json.JSONDecodeError, Exception) as e:
                flash(f'Erro ao processar itens da demanda: {e}', 'danger')
                return redirect(url_for('demanda_producao.list_demandas'))

        # Handle form submission for creating a new demand
        nome_demanda = form_data.get('nome_demanda')
        canal_venda_id = form_data.get('canal_venda_id')
        data_entrega_str = form_data.get('data_entrega')

        if not nome_demanda or not canal_venda_id or not data_entrega_str:
            flash('O nome da demanda, a plataforma e a data de entrega são obrigatórios.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

        # Server-side date validation considering timezone and collection time
        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            # Parse the delivery date
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()

            # Get collection time if provided, otherwise default to end of day
            horario_coleta_str = form_data.get('horario_coleta_especifico')
            if horario_coleta_str:
                # Combine date and time
                combined_dt = datetime.combine(data_entrega, datetime.strptime(horario_coleta_str, '%H:%M').time())
            else:
                # Default to end of day if no specific collection time
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            # Localize the combined datetime to the application timezone
            combined_dt_localized = tz.localize(combined_dt)

            # Compare with current time in the application timezone
            if combined_dt_localized < now_local:
                flash('A data e horário de entrega não podem ser no passado.', 'danger')
                return redirect(url_for('demanda_producao.create_demanda'))
        except ValueError:
            flash('Formato de data ou horário inválido para a data de entrega.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

        itens = []
        itens_dict = {}
        for key, value in form_data.items():
            if key.startswith('itens['):
                parts = key.replace(']', '').split('[')
                index = int(parts[1])
                field = parts[2]
                if index not in itens_dict:
                    itens_dict[index] = {}
                itens_dict[index][field] = value
        
        itens = list(itens_dict.values())

        if not itens:
            flash('É necessário adicionar pelo menos um item à demanda.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

        try:
            nova_demanda = demanda_producao_service.criar_demanda_direta(nome_demanda, canal_venda_id, data_entrega_str, itens)
            flash(f"Demanda '{nova_demanda['nome']}' criada com sucesso!", 'success')
            return redirect(url_for('demanda_producao.view_dashboard', demanda_id=nova_demanda['id']))
        except Exception as e:
            flash(f'Erro ao criar demanda: {e}', 'danger')
            print(f"ERROR creating demand: {e}")
            return redirect(url_for('demanda_producao.create_demanda'))

    # Handle GET request
    try:
        products, _ = product_service.get_products(per_page=10000) 
        canais_venda = canal_venda_service.get_all()
    except Exception as e:
        flash(f'Erro ao carregar dados para o formulário: {e}', 'danger')
        products = []
        canais_venda = []

    return render_template('producao/demanda_form.html', products=products, canais_venda=canais_venda, items=[])

# --- API Routes ---

@demanda_producao_api_bp.route('/', methods=['GET'])
def api_list_demandas():
    try:
        demandas = demanda_producao_service.get_all_demandas()

        # Re-sort demands to ensure critical deadlines are on top
        def sort_key(d):
            # Prioridade 1: Modalidade Expressa
            modalidade = d.get('modalidade_logistica', 'STANDARD')
            is_express = modalidade == 'EXPRESS'
            
            # Prioridade 2: Score Manual
            priority = d.get('manual_priority_score') or 0
            
            # Prioridade 3: Data de Entrega
            data_entrega = d.get('data_entrega', '9999-12-31')
            
            # Prioridade 4: Deadline Crítico (Final)
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

        # Validate User Permissions
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
        tipo_demanda = data.get('tipo_demanda', 'PLATAFORMA') # Get type, default to PLATAFORMA
        modalidade_logistica = data.get('modalidade_logistica', 'STANDARD')
        classificacao_cliente = data.get('classificacao_cliente', 'B2C')
        is_draft = data.get('is_draft', False)
        status = 'AGUARDANDO' if is_draft else 'EM_PRODUCAO'

        # NEW: Enhanced demand fields
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

        # Validate date considering timezone and collection time
        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            # Parse the delivery date
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()

            # Get collection time if provided, otherwise default to end of day
            if horario_coleta_especifico:
                # Combine date and time - handle HH:mm and HH:mm:ss
                if len(horario_coleta_especifico) > 5:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M:%S').time()
                else:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M').time()
                combined_dt = datetime.combine(data_entrega, h_time)
            else:
                # Default to end of day if no specific collection time
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            # Localize the combined datetime to the application timezone
            combined_dt_localized = tz.localize(combined_dt)

            # Compare with current time in the application timezone
            # Permitir uma margem de 10 minutos para evitar erros de sincronia
            if combined_dt_localized < now_local - timedelta(minutes=10):
                 return jsonify({'success': False, 'message': f'A data e horário de entrega ({combined_dt_localized.strftime("%d/%m %H:%M")}) não podem ser no passado.'}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': f'Formato de data ou horário inválido: {str(e)}'}), 400
        
        # Convert data_finalizacao_prevista if provided
        data_finalizacao_prevista = None
        if data_finalizacao_prevista_str:
            try:
                # Usar dateutil para maior flexibilidade no parsing do ISO do JS
                from dateutil.parser import parse
                data_finalizacao_prevista = parse(data_finalizacao_prevista_str)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Formato de data de finalização prevista inválido: {str(e)}'}), 400

        user_id = session.get('user_email', 'System')

        # Use criar_demanda_direta for standard demands
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
            # Extra fields will go into **kwargs and then into dados_adicionais
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
        print(f"ERROR in create_demanda_api: {e}")
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

        # Validate User Permissions
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'criar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem criar demandas.'}), 403

        # Common demand fields
        nome_demanda = data.get('nome')
        canal_venda_id = data.get('canal_venda_id')
        data_entrega_str = data.get('data_entrega')
        itens = data.get('itens', [])
        horario_coleta_especifico = data.get('horario_coleta_especifico')
        data_finalizacao_prevista_str = data.get('data_finalizacao_prevista')
        observacoes = data.get('observacoes')
        modalidade_logistica = data.get('modalidade_logistica', 'STANDARD')
        classificacao_cliente = data.get('classificacao_cliente', 'B2B')
        
        # Empresas specific fields
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

        # Validate dates considering timezone and collection time
        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            # Parse the delivery date
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()

            # Get collection time if provided, otherwise default to end of day
            if horario_coleta_especifico:
                # Combine date and time - handle HH:mm and HH:mm:ss
                if len(horario_coleta_especifico) > 5:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M:%S').time()
                else:
                    h_time = datetime.strptime(horario_coleta_especifico, '%H:%M').time()
                combined_dt = datetime.combine(data_entrega, h_time)
            else:
                # Default to end of day if no specific collection time
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            # Localize the combined datetime to the application timezone
            combined_dt_localized = tz.localize(combined_dt)

            # Compare with current time in the application timezone
            # Permitir uma margem de 10 minutos para evitar erros de sincronia
            if combined_dt_localized < now_local - timedelta(minutes=10):
                 return jsonify({'success': False, 'message': f'A data e horário de entrega ({combined_dt_localized.strftime("%d/%m %H:%M")}) não podem ser no passado.'}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': f'Formato de data ou horário inválido: {str(e)}'}), 400
        
        data_finalizacao_prevista = None
        if data_finalizacao_prevista_str:
            try:
                # Usar dateutil para maior flexibilidade no parsing do ISO do JS
                from dateutil.parser import parse
                data_finalizacao_prevista = parse(data_finalizacao_prevista_str)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Formato de data de finalização prevista inválido: {str(e)}'}), 400


        user_id = session.get('user_email', 'System')

        # NEW: Enhanced demand fields
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
        print(f"ERROR in create_demanda_empresas_api: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>', methods=['PUT'])
@demanda_producao_api_bp.route('/<string:demanda_id>/atualizar-completo', methods=['PUT'])
@login_required
def atualizar_demanda_completa_api(demanda_id):
    try:
        # Validate User Permissions
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
        
        # Prepare updates for the header
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

            # NEW: Enhanced demand fields
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

        # B2B fields if applicable
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

        # Convert date strings
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
        print(f"ERROR in atualizar_demanda_completa_api: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/publicar', methods=['POST'])
@login_required
def publicar_demanda_api(demanda_id):
    try:
        # Validate User Permissions
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
        print(f"ERROR in publicar_demanda_api: {e}")
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/daily-summary', methods=['GET'])
def api_get_daily_summary():
    try:
        summary_data = demanda_producao_service.get_daily_production_summary()
        return jsonify({'success': True, 'summary': summary_data})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_daily_summary: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/ativas', methods=['GET'])
def get_active_demands():
    try:
        product_id = request.args.get('product_id')
        demandas_ativas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'], product_id=product_id)
        return jsonify({'success': True, 'demandas': demandas_ativas}), 200
    except Exception as e:
        import traceback
        print(f"ERROR in get_active_demands: {e}")
        print(traceback.format_exc())
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

    # Validate user permissions based on setor
    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    # Get user identifier for logging
    user_id = session.get('user_email', 'Unknown User')

    # Define permissions by setor (keys in lowercase)
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
        # Normalize the user's setor name for comparison
        normalized_setor = user_setor.strip().lower() if user_setor else ''

        # Check if the normalized setor exists in our permissions map
        allowed_fields = field_permissions.get(normalized_setor, [])

        # If not found, try to match by case-insensitive comparison
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
        print(f"ERROR updating item progress for item {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao atualizar progresso: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/registrar-producao', methods=['POST'])
@login_required
def registrar_producao_incremental(demanda_id, item_id):
    """
    Registra produção incremental para um item de demanda.
    Em vez de substituir valores, soma as quantidades produzidas aos valores existentes.
    """
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    producao_incremental = data.get('producao_incremental', {})
    origem_tipo = data.get('origem_tipo', 1)

    if not producao_incremental:
        return jsonify({'success': False, 'message': 'Dados de produção incremental não fornecidos.'}), 400

    # Determinar se é estorno ou incremento para escolher a origem correta se não fornecida
    if 'origem_tipo' not in data:
        is_removal = any(val < 0 for val in producao_incremental.values() if isinstance(val, (int, float)))
        origem_tipo = 2 if is_removal else 1

    # Validate user permissions based on setor
    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    # Get user identifier for logging
    user_id = session.get('user_email', 'Unknown User')

    # Use the permission service to check if the user has permission to edit these fields
    if not is_admin:
        # Check each field individually using the permission service
        for field in producao_incremental.keys():
            if not permissao_service.has_permission(session.get('user_id'), 'campo_demanda', 'editar'):
                # For more granular control, we could check specific field permissions
                # but for now we'll use the enhanced check based on setor
                user_setor_lower = user_setor.strip().lower() if user_setor else ''

                # Define permissions by setor (keys in lowercase)
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

                # Normalize the user's setor name for comparison
                normalized_setor = user_setor_lower

                # Check if the normalized setor exists in our permissions map
                allowed_fields = field_permissions.get(normalized_setor, [])

                # If not found, try to match by case-insensitive comparison
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
        updated_item = demanda_producao_service.registrar_producao_incremental(demanda_id, item_id, producao_incremental, user_id, origem_tipo=origem_tipo)
        return jsonify({'success': True, 'message': 'Produção registrada com sucesso!', 'item_id': updated_item['id']}), 200

    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        print(f"ERROR registering incremental production for item {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao registrar produção: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/itens/registrar-producao-lote', methods=['POST'])
@login_required
def registrar_producao_lote(demanda_id):
    """
    Registra produção incremental para múltiplos itens de uma demanda de uma vez.
    """
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    updates = data.get('updates', [])
    origem_tipo = data.get('origem_tipo', 1)

    if not updates:
        return jsonify({'success': False, 'message': 'Dados de produção em lote não fornecidos.'}), 400

    # Validate user permissions based on setor (simplified for batch)
    user_setor = session.get('user_setor')
    is_admin = session.get('user_is_admin', False)

    if not user_setor and not is_admin:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    user_id = session.get('user_email', 'Unknown User')

    # Define permissions (reusing logic from individual update)
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
        # Normalize the user's setor name for comparison
        normalized_setor = user_setor.strip().lower() if user_setor else ''

        # Check if the normalized setor exists in our permissions map
        allowed_fields = field_permissions.get(normalized_setor, [])

        # If not found, try to match by case-insensitive comparison
        if not allowed_fields:
            for key, value in field_permissions.items():
                if key.lower() == normalized_setor:
                    allowed_fields = value
                    break

        # Check all items in the batch
        for update in updates:
            producao_incremental = update.get('producao_incremental', {})
            unauthorized_fields = [field for field in producao_incremental.keys() if field not in allowed_fields]
            if unauthorized_fields:
                return jsonify({
                    'success': False,
                    'message': f'Acesso negado. O setor "{user_setor}" não tem permissão para alterar: {", ".join(unauthorized_fields)}'
                }), 403

    try:
        batch_results = demanda_producao_service.registrar_producao_lote(demanda_id, updates, user_id, origem_tipo=origem_tipo)
        return jsonify({
            'success': True, 
            'message': f'{len(batch_results.get("results", []))} itens processados com sucesso!', 
            'results': batch_results.get('results', []),
            'results_count': len(batch_results.get('results', []))
        }), 200
    except Exception as e:
        print(f"ERROR registering batch production for demand {demanda_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno ao registrar produção em lote: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/finalizar-parcial', methods=['POST'])
def finalizar_item_parcial_api(demanda_id, item_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    quantidade_parcial = data.get('quantidade_parcial')

    if not quantidade_parcial or quantidade_parcial <= 0:
        return jsonify({'success': False, 'message': 'Quantidade parcial inválida.'}), 400

    # Validate user permissions based on setor
    user_setor = session.get('user_setor')
    if not user_setor:
        return jsonify({'success': False, 'message': 'Setor do usuário não identificado.'}), 403

    # Only allow finalization for specific sectors
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
        print(f"ERROR finalizing item partially {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao finalizar item: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/finalizar', methods=['POST'])
def finalizar_item_api(demanda_id, item_id):
    try:
        updated_item = demanda_producao_service.finalizar_item(demanda_id, item_id)
        return jsonify({'success': True, 'message': 'Item finalizado com sucesso!', 'item_id': updated_item['id'], 'status_item': updated_item['status_item']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        print(f"ERROR finalizing item {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao finalizar item: {e}'}), 500

@demanda_producao_api_bp.route('/<string:demanda_id>/item/<string:item_id>/reverter-finalizacao', methods=['POST'])
def reverter_finalizacao_item_api(demanda_id, item_id):
    try:
        # Validar permissões do usuário
        user_setor = session.get('user_setor')
        user_is_admin = session.get('user_is_admin', False)

        # Permitir apenas para administradores ou setores específicos
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
        print(f"ERROR reverting finalization for item {item_id} in demand {demanda_id}: {e}")
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
        # Calls the refactored consolidated service method
        demanda = demanda_producao_service.registrar_coleta_parcial(demanda_id, int(quantidade_coletar), user_id)
        
        return jsonify({'success': True, 'message': 'Coleta registrada com sucesso!', 'demanda': demanda})
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        print(f"ERROR finalizing complete demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500


# Production Planning API Routes

@demanda_producao_api_bp.route('/production-plan', methods=['GET'])
def get_production_plan():
    """
    Get comprehensive production plan with timeline visualization.
    """
    try:
        from datetime import datetime, timedelta
        from nistiprint_shared.services.production_planning_service import production_planning_service

        start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))

        plan_data = production_planning_service.get_production_plan(start_date, end_date)
        return jsonify({'success': True, 'plan': plan_data})
    except Exception as e:
        print(f"ERROR in get_production_plan: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/gantt-data', methods=['GET'])
def get_gantt_data():
    """
    Get data formatted for Gantt chart visualization.
    """
    try:
        from datetime import datetime, timedelta
        from nistiprint_shared.services.production_planning_service import production_planning_service

        demanda_ids_param = request.args.get('demanda_ids')
        demanda_ids = demanda_ids_param.split(',') if demanda_ids_param else None

        gantt_data = production_planning_service.get_gantt_data(demanda_ids)
        return jsonify({'success': True, 'gantt_data': gantt_data})
    except Exception as e:
        print(f"ERROR in get_gantt_data: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/resource-allocation-dashboard', methods=['GET'])
def get_resource_allocation_dashboard():
    """
    Get dashboard data for resource allocation.
    """
    try:
        from nistiprint_shared.services.production_planning_service import production_planning_service

        dashboard_data = production_planning_service.get_resource_allocation_dashboard()
        return jsonify({'success': True, 'dashboard': dashboard_data})
    except Exception as e:
        print(f"ERROR in get_resource_allocation_dashboard: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/production-forecast', methods=['GET'])
def get_production_forecast():
    """
    Forecast production needs based on historical data and demand patterns.
    """
    try:
        from nistiprint_shared.services.production_planning_service import production_planning_service

        period_days = request.args.get('period_days', 30, type=int)

        forecast_data = production_planning_service.forecast_production_needs(period_days)
        return jsonify({'success': True, 'forecast': forecast_data})
    except Exception as e:
        print(f"ERROR in get_production_forecast: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/calendar-data', methods=['GET'])
def get_calendar_data():
    """
    Get calendar data for demands in the specified date range.
    """
    try:
        from datetime import datetime, timedelta
        from nistiprint_shared.services.calendar_service import calendar_service

        start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))

        calendar_data = calendar_service.get_calendar_data(start_date, end_date)
        return jsonify({'success': True, 'events': calendar_data})
    except Exception as e:
        print(f"ERROR in get_calendar_data: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/validate-schedule-conflict', methods=['POST'])
def validate_schedule_conflict():
    """
    Validate if the new schedule dates would create conflicts with existing demands.
    """
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
        print(f"ERROR in validate_schedule_conflict: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@demanda_producao_api_bp.route('/update-demand-schedule/<string:demanda_id>', methods=['PUT'])
def update_demand_schedule(demanda_id):
    """
    Update the schedule dates for a demand.
    """
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
        print(f"ERROR in update_demand_schedule: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/fila-estoque', methods=['GET'])
def api_get_fila_estoque():
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        # Usando a sintaxe padrão de join do PostgREST/Supabase
        # itens_demanda(sku, descricao) - o Supabase resolve o FK automaticamente
        res = supabase_db.table('fila_processamento_estoque')\
            .select("*, itens_demanda(sku, descricao)")\
            .order('created_at', desc=True)\
            .limit(100)\
            .execute()
        
        # Mapeia 'itens_demanda' para 'item' para manter compatibilidade com o frontend
        queue_data = []
        if res.data:
            for row in res.data:
                item_info = row.pop('itens_demanda', None)
                row['item'] = item_info
                queue_data.append(row)

        return jsonify({'success': True, 'queue': queue_data})
    except Exception as e:
        print(f"ERRO ao buscar fila de estoque: {e}")
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

        # 1. Buscar logs de produção de hoje para calcular os totais dos setores
        # Isso garante que apenas o que foi produzido HOJE seja contabilizado
        logs_res = supabase_db.table('logs_producao_diaria')\
            .select("*")\
            .eq('data', today.isoformat())\
            .neq('deleted', True)\
            .execute()
        
        sector_totals = {
            'CPD': 0,
            'Capas': 0,
            'Miolos': 0,
            'Expedição': 0
        }

        if logs_res.data:
            for log in logs_res.data:
                qty = float(log.get('quantidade_produzida', 0))
                # Tenta pegar metadados de detalhes_producao (campo do log_service)
                metadata = log.get('detalhes_producao') or {}
                campo = metadata.get('campo')
                
                if campo:
                    # Mapeamento de campo para setor seguindo a lógica original
                    if campo in ['capas_impressas_qtd', 'capas_prontas_retirada_qtd']:
                        sector_totals['CPD'] += qty
                    elif campo == 'capas_produzidas_qtd':
                        sector_totals['Capas'] += qty
                    elif campo == 'miolos_prontos_retirada_qtd':
                        sector_totals['Miolos'] += qty
                    elif campo in ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']:
                        sector_totals['Expedição'] += qty

        # 2. Buscar contagem de demandas (Hoje e Futuro)
        demand_totals = {
            'today': 0,
            'future': 0
        }
        
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

        return jsonify({
            'success': True,
            'sector_totals': sector_totals,
            'demand_totals': demand_totals
        })
    except Exception as e:
        print(f"ERROR in get_dashboard_totals: {e}")
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/dashboard-summary', methods=['GET'])
def api_get_dashboard_summary():
    try:
        summary_data = demanda_producao_service.get_dashboard_summary()
        return jsonify({'success': True, **summary_data})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_dashboard_summary: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/consolidado', methods=['GET'])
def api_get_consolidado():
    try:
        trilha = request.args.get('trilha') # Opcional: PRINCIPAL ou LATERAL
        agrupado = request.args.get('agrupado', 'true').lower() == 'true'
        
        if agrupado:
            dados = demanda_producao_service.get_consolidado_agrupado_por_sku(trilha=trilha)
        else:
            dados = demanda_producao_service.get_consolidado_producao(trilha=trilha)
            
        return jsonify({'success': True, 'data': dados})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_consolidado: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/ativas-por-item/<string:produto_id>', methods=['GET'])
def api_get_ativas_por_item(produto_id):
    try:
        demandas = demanda_producao_service.get_demandas_ativas_por_item(produto_id)
        return jsonify({'success': True, 'demandas': demandas})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_ativas_por_item: {e}")
        print(traceback.format_exc())
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
        import traceback
        print(f"ERROR in api_registrar_retirada_expedicao: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/prioritized', methods=['GET'])
def api_get_prioritized_demandas():
    try:
        limit = request.args.get('limit', type=int, default=50)
        prioritized_items = demanda_producao_service.get_prioritized_demandas(limit=limit)
        return jsonify({'success': True, 'prioritized_items': prioritized_items})
    except Exception as e:
        import traceback
        print(f"ERROR in api_get_prioritized_demandas: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_api_bp.route('/demanda/<demanda_id>/detalhes', methods=['PUT'])
@login_required
def api_update_demanda_details(demanda_id):
    try:
        # Validate User Permissions
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'editar'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem atualizar detalhes da demanda.'}), 403

        data = request.get_json()
        user_id = session.get('user_email', 'System')
        updated_demanda = demanda_producao_service.update_demanda_details(demanda_id, data, user_id)
        
        # Add canal_venda_color
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
        import traceback
        print(f"ERROR in api_update_demanda_details: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

from nistiprint_shared.services.daily_production_log_service import daily_production_log_service # Assuming this service exists

@demanda_producao_api_bp.route('/registrar-saida', methods=['POST'])
def registrar_saida_distribuida():
    data = request.get_json()
    distributions = data.get('distributions')
    product_id = data.get('product_id')
    total_quantity = data.get('quantity')
    production_date_str = data.get('date')
    demanda_id = data.get('demanda_id') # Captura o ID da demanda selecionada
    update_demand = data.get('update_demand', True) # Flag para controle de acoplamento

    if not all([distributions, product_id, total_quantity, production_date_str]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400

    try:
        # Use session-based user authentication
        user_id = session.get('user_id')
        production_date = datetime.strptime(production_date_str, '%Y-%m-%d').date()

        # Pre-validação de Estoque
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        saldo = estoque_service.get_saldo_atual(product_id, deposito_id)
        # Assumindo que total_quantity é positivo
        if saldo['quantidade_disponivel'] < float(total_quantity):
             return jsonify({'success': False, 'error': f"Saldo insuficiente. Disponível: {saldo['quantidade_disponivel']}, Solicitado: {total_quantity}"}), 400

        # Obter o contexto do usuário para validação de setor
        from routes.auth import get_current_user
        usuario = get_current_user()
        user_context = {
            'id': usuario['id'],
            'setor_id': usuario['setor_id'],
            'setor_nome': usuario['setor_nome'],
            'is_admin': usuario['is_admin']
        }

        # Use UnitOfWork para garantir atomicidade de todas as operações
        with UnitOfWork(user_id=user_id) as uow:
            # 1. Registrar a saída de estoque (atualiza saldo)
            uow.execute_in_transaction(
                estoque_service.registrar_saida,
                product_id,
                deposito_id,
                total_quantity,
                f"Saída distribuída de miolos para demandas - {production_date_str}",
                user_id,
                user_context=user_context,
                documento_referencia=demanda_id # Passa o ID da demanda como referência
            )

            # 2. Registrar a distribuição nos itens das demandas (apenas se solicitado)
            if update_demand:
                uow.execute_in_transaction(
                    demanda_producao_service.registrar_saida_item_distribuida,
                    distributions,
                    product_id,
                    user_id
                )
                
                # --- NOVO: AGENDAR PROCESSAMENTO DE FILA DE ESTOQUE PARA CADA DISTRIBUIÇÃO ---
                for dist in distributions:
                    item_id = dist.get('item_id')
                    qty = dist.get('quantidade')
                    if item_id and qty:
                         # No contexto de Miolos (Saída Distribuída), o campo é miolos_prontos_retirada_qtd
                         # Mas o registrar_saida_item_distribuida identifica o role automaticamente.
                         # Para simplificar e garantir a BOM, agendamos o processamento do item.
                         uow.execute_in_transaction(
                             demanda_producao_service.agendar_processamento_estoque,
                             demanda_id,
                             item_id,
                             'miolos_prontos_retirada_qtd', # Assume miolo por ser a tela de miolos
                             float(qty),
                             user_id
                         )
                # ---------------------------------------------------------------------------

            # 3. Registrar no log de produção diário
            uow.execute_in_transaction(
                daily_production_log_service.create_log,
                production_date,
                product_id,
                f"Produto {product_id}",  # Simplificado, poderia buscar nome real
                -abs(total_quantity),  # Negativo para saída
                None,  # production_order_id
                [],  # component_stock_snapshot
                user_id,
                metadata={'demanda_id': demanda_id} # CORREÇÃO: Salvar ID da demanda no log diário
            )

            # 4. Registrar evento de auditoria
            uow.log_audit_event('SAIDA_DISTRIBUIDA_DEMANDA', {
                'product_id': product_id,
                'total_quantity': total_quantity,
                'production_date': production_date_str,
                'distributions': distributions
            })

        # Após transação bem-sucedida, obter totais atualizados para UI
        new_daily_removed = daily_production_log_service.get_total_removed_for_product_on_date(product_id, production_date)

        return jsonify({
            'success': True,
            'message': 'Saída distribuída registrada com sucesso!',
            'new_daily_removed': new_daily_removed
        }), 200

    except Exception as e:
        import traceback
        print(f"ERROR in registrar_saida_distribuida: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': f'Erro interno: {e}'}), 500

# Legacy HTML routes that might still be needed or can be removed if strictly converting to React
@demanda_producao_bp.route('/<string:demanda_id>/dashboard')
def view_dashboard(demanda_id):
    try:
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            flash(f'Demanda com ID {demanda_id} não encontrada.', 'danger')
            return redirect(url_for('demanda_producao.list_demandas'))

        # Pass a list containing the single demand to the template
        return render_template('producao/demanda_dashboard.html', demandas=[demanda])
    except Exception as e:
        flash(f'Erro ao carregar o dashboard da demanda: {e}', 'danger')
        return redirect(url_for('demanda_producao.list_demandas'))

@demanda_producao_bp.route('/in-progress-dashboard')
def list_in_progress_dashboard():
    try:
        # Fetch demands with status 'Em Produção' or 'Pendente'
        demandas_raw = demanda_producao_service.get_demandas_by_status(['Em Produção', 'Pendente'])
        
        demandas_for_template = []
        for demanda_data in demandas_raw:
            # For each demand, get its items and calculate progress
            demanda_with_itens = demanda_producao_service.get_demanda_with_itens(demanda_data['id'])
            if demanda_with_itens:
                total_quantidade = 0
                completed_quantidade = 0
                for item in demanda_with_itens['itens']:
                    quantidade_total_item = item.get('quantidade_total', 0)
                    total_quantidade += quantidade_total_item
                    if item.get('status_item') == 'Finalizado':
                        completed_quantidade += quantidade_total_item
                
                progresso_percentual = 0
                if total_quantidade > 0:
                    progresso_percentual = (completed_quantidade / total_quantidade) * 100
                
                demanda_with_itens['progresso_percentual'] = round(progresso_percentual, 2)
                demanda_with_itens['total_quantidade'] = total_quantidade
                demanda_with_itens['completed_quantidade'] = completed_quantidade
                demandas_for_template.append(demanda_with_itens)

    except Exception as e:
        flash(f'Erro ao carregar as demandas em andamento: {e}', 'danger')
        demandas_for_template = []
    return render_template('producao/demanda_dashboard.html', demandas=demandas_for_template)
    
@demanda_producao_bp.route('/api/miolo/<string:miolo_id>/itens-pendentes', methods=['GET'])
def get_pending_items_for_miolo(miolo_id):
    try:
        demands_with_items = demanda_producao_service.get_pending_items_by_miolo(miolo_id)
        return render_template('producao/_distribution_list.html', demands_dict=demands_with_items)
    except Exception as e:
        import traceback
        print(f"ERROR in get_pending_items_for_miolo: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Ocorreu um erro ao buscar os itens pendentes.'}), 500

@demanda_producao_api_bp.route('/miolo/<string:miolo_id>/itens-pendentes', methods=['GET'])
def get_pending_items_for_miolo_api(miolo_id):
    try:
        demands_with_items = demanda_producao_service.get_pending_items_by_miolo(miolo_id)
        # Transform/Serialize if necessary, but get_pending_items_by_miolo returns a dict/list structure
        return jsonify({'success': True, 'demands': demands_with_items})
    except Exception as e:
        import traceback
        print(f"ERROR in get_pending_items_for_miolo_api: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@demanda_producao_bp.route('/<string:demanda_id>/marcar_coletado', methods=['POST'])
def marcar_coletado_route(demanda_id):
    try:
        demanda_producao_service.marcar_como_coletado(demanda_id)
        flash('Demanda marcada como coletada com sucesso!', 'success')
    except ValueError as ve:
        flash(str(ve), 'danger')
    except Exception as e:
        flash(f'Erro ao marcar a demanda como coletada: {e}', 'danger')
    return redirect(url_for('demanda_producao.view_dashboard', demanda_id=demanda_id))

@demanda_producao_api_bp.route('/miolo-demand-summary', methods=['GET'])
def get_miolo_demand_summary():
    try:
        # Get all active demands with items
        all_demandas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'])

        miolo_summary = {} # key: id_produto_miolo or name if id missing

        for demanda in all_demandas:
            # d_with_itens = demanda_producao_service.get_demanda_with_itens(demanda['id'])
            # Optimization: we already have some info, but we need items to know miolos
            # Better use a method that gets items for all these demands at once
            pass
        
        # Otimização: buscar itens de todas as demandas ativas de uma vez
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
                    
                    # Calcular saldo faltante (miolo)
                    pronto = item.get('miolos_prontos_retirada_qtd', 0) or 0
                    faltante = max(0, quantity - pronto)
                    
                    if faltante <= 0: continue

                    if key not in miolo_summary:
                        miolo_summary[key] = {
                            'name': miolo_name,
                            'id': miolo_id,
                            'quantity': 0,
                            'quantity_pending': 0,
                            'demandas_map': {} # Usar mapa para agrupar por demanda
                        }
                    
                    miolo_summary[key]['quantity'] += quantity
                    miolo_summary[key]['quantity_pending'] += faltante

                    # Agrupar itens da mesma demanda para este miolo
                    if did_str not in miolo_summary[key]['demandas_map']:
                        miolo_summary[key]['demandas_map'][did_str] = {
                            'demanda_id': demanda['id'],
                            'demanda_nome': demanda.get('nome') or demanda.get('descricao'),
                            'quantidade_total': 0,
                            'quantidade_faltante': 0,
                            'data_entrega': demanda['data_entrega']
                        }
                    
                    miolo_summary[key]['demandas_map'][did_str]['quantidade_total'] += quantity
                    miolo_summary[key]['demandas_map'][did_str]['quantidade_faltante'] += faltante

        # Converter mapas de demandas para listas e ordenar
        summary_list = list(miolo_summary.values())
        for miolo in summary_list:
            miolo['demandas'] = list(miolo['demandas_map'].values())
            miolo['demandas'].sort(key=lambda x: x['data_entrega'] or '9999-12-31')
            del miolo['demandas_map']
            # O frontend espera o campo 'quantity' como o total pendente para o Badge lateral
            miolo['quantity'] = miolo['quantity_pending']

        # Ordenar lista principal por nome
        summary_list.sort(key=lambda x: x['name'])

        return jsonify({'success': True, 'summary': summary_list})
    except Exception as e:
        print(f"ERROR in get_miolo_demand_summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/capa-demand-info', methods=['GET'])
def get_capa_demand_info():
    try:
        # Get all active demands with items
        all_demandas = demanda_producao_service.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'])

        capa_summary = {} # key: sku or product_id

        demanda_ids = [d['id'] for d in all_demandas]
        itens_mapping = demanda_producao_service.get_items_for_multiple_demandas([str(id) for id in demanda_ids])

        for demanda in all_demandas:
            did_str = str(demanda['id'])
            itens = itens_mapping.get(did_str, [])
            
            for item in itens:
                # Se não tem produto_id, ignorar (não é uma capa rastreável)
                if not item.get('produto_id'): continue
                
                key = str(item['produto_id'])
                quantity = item.get('quantidade_total', 0)
                
                # Saldo faltante (capa finalizada)
                pronto = item.get('capas_produzidas_qtd', 0) or item.get('capas_prontas_retirada_qtd', 0) or 0
                faltante = max(0, quantity - pronto)
                
                if faltante <= 0: continue

                if key not in capa_summary:
                    capa_summary[key] = {
                        'name': item.get('item_descricao') or item.get('descricao'),
                        'sku': item.get('sku'),
                        'id': item.get('produto_id'),
                        'variacao': item.get('variacao'),
                        'miolo_name': item.get('miolo_name'),
                        'quantity': 0,
                        'quantity_pending': 0,
                        'demandas_map': {} # Sub-agrupamento por demanda
                    }
                
                capa_summary[key]['quantity'] += quantity
                capa_summary[key]['quantity_pending'] += faltante

                # Agrupar itens da mesma demanda para esta capa
                if did_str not in capa_summary[key]['demandas_map']:
                    capa_summary[key]['demandas_map'][did_str] = {
                        'demanda_id': demanda['id'],
                        'demanda_nome': demanda.get('nome') or demanda.get('descricao'),
                        'quantidade_total': 0,
                        'quantidade_faltante': 0,
                        'data_entrega': demanda['data_entrega']
                    }
                
                capa_summary[key]['demandas_map'][did_str]['quantidade_total'] += quantity
                capa_summary[key]['demandas_map'][did_str]['quantidade_faltante'] += faltante

        # Converter para o formato de lista esperado pelo frontend
        summary_list = []
        for c_key, c_data in capa_summary.items():
            c_data['demandas'] = list(c_data['demandas_map'].values())
            # Ordenar demandas por data de entrega
            c_data['demandas'].sort(key=lambda x: x.get('data_entrega', ''))
            del c_data['demandas_map']
            # O frontend espera 'quantity' como o total pendente
            c_data['quantity'] = c_data['quantity_pending']
            summary_list.append(c_data)

        # Ordenar lista principal por SKU/Nome
        summary_list.sort(key=lambda x: x.get('sku') or x['name'])

        return jsonify({'success': True, 'summary': summary_list})
    except Exception as e:
        print(f"ERROR in get_capa_demand_info: {e}")
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/products/<int:product_id>/default-miolo', methods=['GET'])
def get_default_miolo_for_product(product_id):
    try:
        # Import necessário para acessar a função
        from nistiprint_shared.services.file_processors import get_miolo_from_bom

        print(f"[DEBUG MIOLO BACKEND] Buscando miolo para produto ID: {product_id}")

        # Obtém o miolo padrão do produto a partir da BOM
        miolo_nome, id_produto_miolo = get_miolo_from_bom(product_id)

        print(f"[DEBUG MIOLO BACKEND] Resultado para produto {product_id}: miolo_nome={miolo_nome}, id_produto_miolo={id_produto_miolo}")

        if miolo_nome and id_produto_miolo:
            print(f"[DEBUG MIOLO BACKEND] Retornando miolo: {miolo_nome} (ID: {id_produto_miolo})")
            return jsonify({
                'success': True,
                'miolo': {
                    'id': id_produto_miolo,
                    'nome': miolo_nome
                }
            })
        else:
            print(f"[DEBUG MIOLO BACKEND] Nenhum miolo encontrado para o produto {product_id}")
            return jsonify({
                'success': True,
                'miolo': None,
                'message': 'Nenhum miolo padrão encontrado para este produto'
            })

    except Exception as e:
        print(f"ERROR in get_default_miolo_for_product: {e}")
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500

@demanda_producao_api_bp.route('/<demanda_id>', methods=['DELETE'])
@login_required
def delete_demanda_api(demanda_id):
    try:
        # Validate User Permissions
        user_id = session.get('user_id')
        if not permissao_service.has_permission(user_id, 'demanda_producao', 'excluir'):
             return jsonify({'success': False, 'message': 'Acesso negado. Apenas usuários com permissão podem deletar demandas.'}), 403

        # Get user identifier for logging
        user_id = session.get('user_email', 'Unknown User')

        # Check if demand exists
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            return jsonify({'success': False, 'message': 'Demanda não encontrada.'}), 404

        # Delete the demand
        demanda_producao_service.deletar_demanda(demanda_id, user_id)

        return jsonify({
            'success': True,
            'message': f'Demanda "{demanda.get("nome", "")}" deletada com sucesso!'
        }), 200

    except Exception as e:
        print(f"ERROR in delete_demanda_api: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {e}'}), 500





