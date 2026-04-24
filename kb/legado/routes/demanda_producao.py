from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from services.demanda_producao_service import demanda_producao_service
from services.product_service import product_service
from services.canal_venda_service import canal_venda_service
from datetime import datetime # Needed for data_criacao formatting in template

demanda_producao_bp = Blueprint('demanda_producao', __name__, url_prefix='/producao/demanda')

@demanda_producao_bp.route('/')
def list_demandas():
    try:
        demandas = demanda_producao_service.get_all_demandas()
    except Exception as e:
        flash(f'Erro ao carregar as demandas: {e}', 'danger')
        demandas = []
    return render_template('producao/demanda_list.html', demandas=demandas)

@demanda_producao_bp.route('/nova', methods=['GET', 'POST'])
def create_demanda():
    if request.method == 'POST':
        form_data = request.form
        nome_demanda = form_data.get('nome_demanda')
        canal_venda_id = form_data.get('canal_venda_id')
        data_entrega_str = form_data.get('data_entrega')

        if not nome_demanda or not canal_venda_id or not data_entrega_str:
            flash('O nome da demanda, a plataforma e a data de entrega são obrigatórios.', 'danger')
            return redirect(url_for('demanda_producao.create_demanda'))

        # Server-side date validation for the demand-level data_entrega
        today = datetime.utcnow().date()
        try:
            data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
            if data_entrega < today:
                flash('A data de entrega não pode ser no passado.', 'danger')
                return redirect(url_for('demanda_producao.create_demanda'))
        except ValueError:
            flash('Formato de data inválido para a data de entrega.', 'danger')
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

    try:
        products, _ = product_service.get_products(per_page=10000) 
        canais_venda = canal_venda_service.get_all()
    except Exception as e:
        flash(f'Erro ao carregar dados para o formulário: {e}', 'danger')
        products = []
        canais_venda = []

    return render_template('producao/demanda_form.html', products=products, canais_venda=canais_venda)


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
        # Fetch demands with status 'Em Produção' or 'Em Andamento'
        demandas_raw = demanda_producao_service.get_demandas_by_status(['Em Produção', 'Em Andamento'])
        
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
    
@demanda_producao_bp.route('/api/demandas/ativas', methods=['GET'])
def get_active_demands():
    try:
        product_id = request.args.get('product_id')
        demandas_ativas = demanda_producao_service.get_demandas_by_status(['Criada', 'Em Andamento', 'Em Produção'], product_id=product_id)
        return jsonify({'success': True, 'demandas': demandas_ativas}), 200
    except Exception as e:
        import traceback
        print(f"ERROR in get_active_demands: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@demanda_producao_bp.route('/api/demanda/<string:demanda_id>/item/<string:item_id>/atualizar', methods=['POST'])
def update_item_progress(demanda_id, item_id):
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Requisição deve ser JSON.'}), 400

    data = request.get_json()
    quantities_to_update = data.get('quantities', {})

    if not quantities_to_update:
        return jsonify({'success': False, 'message': 'Nenhuma quantidade para atualizar fornecida.'}), 400

    try:
        updated_item = demanda_producao_service.atualizar_progresso_item(demanda_id, item_id, quantities_to_update)
        return jsonify({'success': True, 'message': 'Progresso atualizado com sucesso!', 'item_id': updated_item['id']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        print(f"ERROR updating item progress for item {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao atualizar progresso: {e}'}), 500

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


@demanda_producao_bp.route('/api/demanda/<string:demanda_id>/item/<string:item_id>/finalizar', methods=['POST'])
def finalizar_item_api(demanda_id, item_id):
    try:
        updated_item = demanda_producao_service.finalizar_item(demanda_id, item_id)
        return jsonify({'success': True, 'message': 'Item finalizado com sucesso!', 'item_id': updated_item['id'], 'status_item': updated_item['status_item']}), 200
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        print(f"ERROR finalizing item {item_id} in demand {demanda_id}: {e}")
        return jsonify({'success': False, 'message': f'Erro interno ao finalizar item: {e}'}), 500
