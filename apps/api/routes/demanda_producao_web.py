from flask import render_template, request, flash, redirect, url_for
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
import json
import pytz
from datetime import datetime
from constants import APP_TIMEZONE
from routes.auth import login_required, check_permission
from .demanda_producao_base import demanda_producao_bp

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

        nome_demanda = form_data.get('nome_demanda')
        canal_venda_id = form_data.get('canal_venda_id')
        data_entrega_str = form_data.get('data_entrega')

        if not nome_demanda or not canal_venda_id or not data_entrega_str:
            flash('O nome da demanda, a plataforma e a data de entrega são obrigatórios.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

        tz = pytz.timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        try:
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
            horario_coleta_str = form_data.get('horario_coleta_especifico')
            if horario_coleta_str:
                combined_dt = datetime.combine(data_entrega, datetime.strptime(horario_coleta_str, '%H:%M').time())
            else:
                combined_dt = datetime.combine(data_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

            combined_dt_localized = tz.localize(combined_dt)

            if combined_dt_localized < now_local:
                flash('A data e horário de entrega não podem ser no passado.', 'danger')
                return redirect(url_for('demanda_producao.create_demanda'))
        except ValueError:
            flash('Formato de data ou horário inválido para a data de entrega.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

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

    try:
        products, _ = product_service.get_products(per_page=10000) 
        canais_venda = canal_venda_service.get_all()
    except Exception as e:
        flash(f'Erro ao carregar dados para o formulário: {e}', 'danger')
        products = []
        canais_venda = []

    return render_template('producao/demanda_form.html', products=products, canais_venda=canais_venda, items=[])

@demanda_producao_bp.route('/<string:demanda_id>/dashboard')
def view_dashboard(demanda_id):
    try:
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            flash(f'Demanda com ID {demanda_id} não encontrada.', 'danger')
            return redirect(url_for('demanda_producao.list_demandas'))
        return render_template('producao/demanda_dashboard.html', demandas=[demanda])
    except Exception as e:
        flash(f'Erro ao carregar o dashboard da demanda: {e}', 'danger')
        return redirect(url_for('demanda_producao.list_demandas'))

@demanda_producao_bp.route('/in-progress-dashboard')
def list_in_progress_dashboard():
    try:
        demandas_raw = demanda_producao_service.get_demandas_by_status(['Em Produção', 'Pendente'])
        demandas_for_template = []
        for demanda_data in demandas_raw:
            demanda_with_itens = demanda_producao_service.get_demanda_with_itens(demanda_data['id'])
            if demanda_with_itens:
                total_quantidade = 0
                completed_quantidade = 0
                for item in demanda_with_itens['itens']:
                    quantidade_total_item = max(0, float(item.get('quantidade_total', 0) or 0))
                    total_quantidade += quantidade_total_item
                    if item.get('status_item') == 'Concluído':
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
