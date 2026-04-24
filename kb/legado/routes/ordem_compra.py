from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
from datetime import datetime

from services.ordem_compra_service import ordem_compra_service
from services.fornecedor_service import fornecedor_service
from services.product_service import product_service
from services.deposito_service import deposito_service

ordem_compra_bp = Blueprint('ordem_compra', __name__, url_prefix='/ordens-compra')


@ordem_compra_bp.route('', methods=['GET'])
def index():
    """Lista ordens de compra"""
    try:
        fornecedor_id = request.args.get('fornecedor_id', type=int)
        status = request.args.get('status')

        ordens_compra = ordem_compra_service.list_ordens_compra(
            fornecedor_id=fornecedor_id, status=status
        )

        fornecedores = fornecedor_service.list_fornecedores()

        return render_template('ordem_compra/index.html',
                             ordens_compra=ordens_compra,
                             fornecedores=fornecedores,
                             filtro_fornecedor=fornecedor_id,
                             filtro_status=status)
    except Exception as e:
        flash(f'Erro ao carregar ordens de compra: {str(e)}', 'error')
        return render_template('ordem_compra/index.html')


@ordem_compra_bp.route('/nova', methods=['GET', 'POST'])
def nova():
    """Cria nova ordem de compra"""
    try:
        if request.method == 'POST':
            # Dados da OC
            oc_data = {
                'numero_oc': request.form.get('numero_oc'),
                'fornecedor_id': request.form.get('fornecedor_id', type=int),
                'data_emissao': datetime.fromisoformat(request.form.get('data_emissao')),
                'data_previsao_entrega': request.form.get('data_previsao_entrega'),
                'observacoes': request.form.get('observacoes', '')
            }

            # Cria OC
            oc_id = ordem_compra_service.create_ordem_compra(oc_data)

            flash(f'Ordem de compra criada com sucesso: {oc_data["numero_oc"]}', 'success')
            return redirect(url_for('ordem_compra.detalhes', oc_id=oc_id))

        # GET - mostra formulário
        fornecedores = fornecedor_service.list_fornecedores()
        return render_template('ordem_compra/nova.html', fornecedores=fornecedores)

    except Exception as e:
        flash(f'Erro ao criar ordem de compra: {str(e)}', 'error')
        return render_template('ordem_compra/nova.html')


@ordem_compra_bp.route('/<oc_id>', methods=['GET'])
def detalhes(oc_id):
    """Detalhes da ordem de compra"""
    try:
        oc = ordem_compra_service.get_ordem_compra(oc_id)
        if not oc:
            flash('Ordem de compra não encontrada', 'error')
            return redirect(url_for('ordem_compra.index'))

        fornecedor = fornecedor_service.get_by_id(oc['fornecedor_id'])

        return render_template('ordem_compra/detalhes.html',
                             oc=oc,
                             fornecedor=fornecedor)
    except Exception as e:
        flash(f'Erro ao carregar detalhes: {str(e)}', 'error')
        return redirect(url_for('ordem_compra.index'))


@ordem_compra_bp.route('/<oc_id>/adicionar-item', methods=['POST'])
def adicionar_item(oc_id):
    """Adiciona item à ordem de compra"""
    try:
        item_data = {
            'produto_id': request.form.get('produto_id'),
            'quantidade': float(request.form.get('quantidade')),
            'custo_unitario': float(request.form.get('custo_unitario'))
        }

        ordem_compra_service.add_item_to_ordem_compra(oc_id, item_data)

        flash('Item adicionado com sucesso', 'success')
        return redirect(url_for('ordem_compra.detalhes', oc_id=oc_id))

    except Exception as e:
        flash(f'Erro ao adicionar item: {str(e)}', 'error')
        return redirect(url_for('ordem_compra.detalhes', oc_id=oc_id))


@ordem_compra_bp.route('/receber/<item_id>', methods=['POST'])
def receber_item(item_id):
    """Registra recebimento de item"""
    try:
        quantidade_recebida = float(request.form.get('quantidade_recebida'))
        deposito_id = int(request.form.get('deposito_id'))

        success = ordem_compra_service.receber_item(
            item_id=item_id,
            quantidade_recebida=quantidade_recebida,
            deposito_id=deposito_id,
            usuario_id=request.form.get('usuario_id', type=int)
        )

        if success:
            flash('Item recebido com sucesso', 'success')
        else:
            flash('Erro ao registrar recebimento', 'error')

    except Exception as e:
        flash(f'Erro no recebimento: {str(e)}', 'error')

    # Redireciona para a OC do item
    # Como não temos fácil acesso ao OC ID, vamos busca via item (simplificado)
    return redirect(url_for('ordem_compra.index'))


@ordem_compra_bp.route('/cancelar/<oc_id>', methods=['POST'])
def cancelar(oc_id):
    """Cancela ordem de compra"""
    try:
        success = ordem_compra_service.cancelar_ordem_compra(oc_id)
        if success:
            flash('Ordem de compra cancelada', 'success')
        else:
            flash('Erro ao cancelar ordem', 'error')
    except Exception as e:
        flash(f'Erro ao cancelar: {str(e)}', 'error')

    return redirect(url_for('ordem_compra.detalhes', oc_id=oc_id))


@ordem_compra_bp.route('/api/produtos', methods=['GET'])
def api_produtos():
    """API para busca de produtos (autocomplete)"""
    try:
        q = request.args.get('q', '')
        produtos = product_service.search_produtos(q, limit=20)

        # Formatar para select2/autocomplete
        results = [{
            'id': p['id'],
            'text': f"{p.get('sku_mestre', '')} - {p.get('nome', '')}"
        } for p in produtos]

        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ordem_compra_bp.route('/api/fornecedores', methods=['GET'])
def api_fornecedores():
    """API para busca de fornecedores (autocomplete)"""
    try:
        fornecedores = fornecedor_service.list_fornecedores()

        results = [{
            'id': f['id'],
            'text': f.get('nome_razao_social', ''),
            'cnpj': f.get('cpf_cnpj', '')
        } for f in fornecedores]

        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
