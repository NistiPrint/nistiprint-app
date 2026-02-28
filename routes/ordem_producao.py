from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from nistiprint_shared.services.ordem_producao_service import ordem_producao_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.estoque_service import estoque_service
import traceback

ordem_producao_bp = Blueprint('ordem_producao', __name__, url_prefix='/ordem-producao')

@ordem_producao_bp.route('/')
def index():
    """Lista todas as Ordens de Produção."""
    status_filter = request.args.get('status')
    try:
        ordens_producao = ordem_producao_service.get_all(status=status_filter)
        return render_template('ordem_producao/index.html', ordens_producao=ordens_producao)
    except Exception as e:
        flash(f'Erro ao listar Ordens de Produção: {str(e)}', 'error')
        return render_template('ordem_producao/index.html', ordens_producao=[])

def get_status_label(status):
    labels = {
        'DRAFT': 'Rascunho',
        'PENDING': 'Pendente',
        'IN_PROGRESS': 'Em Andamento',
        'PAUSED': 'Pausada',
        'PARTIALLY_DELIVERED': 'Parcialmente Entregue',
        'COMPLETED': 'Concluída',
        'CANCELED': 'Cancelada'
    }
    return labels.get(status, status)

@ordem_producao_bp.context_processor
def inject_helpers():
    return {
        'getStatusLabel': get_status_label,
        'getStatusBadgeClass': lambda s: {
            'DRAFT': 'secondary',
            'PENDING': 'warning',
            'IN_PROGRESS': 'info',
            'PAUSED': 'warning',
            'PARTIALLY_DELIVERED': 'primary',
            'COMPLETED': 'success',
            'CANCELED': 'danger'
        }.get(s, 'secondary'),
        'getProgressBarClass': lambda s: {
            'DRAFT': 'secondary',
            'PENDING': 'warning',
            'IN_PROGRESS': 'primary',
            'PAUSED': 'warning',
            'PARTIALLY_DELIVERED': 'info',
            'COMPLETED': 'success',
            'CANCELED': 'danger'
        }.get(s, 'secondary')
    }

@ordem_producao_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Cria nova Ordem de Produção."""
    if request.method == 'POST':
        try:
            product_id = request.form.get('product_id')
            quantity_to_produce = float(request.form.get('quantity_to_produce', 0))
            notes = request.form.get('notes', '')

            po = ordem_producao_service.create_draft(product_id, quantity_to_produce, notes)
            flash('Ordem de Produção criada com sucesso!', 'success')
            return redirect(url_for('ordem_producao.detail', po_id=po['id']))
        except Exception as e:
            flash(f'Erro ao criar Ordem de Produção: {str(e)}', 'error')
            return redirect(url_for('ordem_producao.create'))

    # GET: busca produtos para seleção
    query = request.args.get('q', '')
    products = []
    if query:
        products = product_service.search_produtos(query, limit=20, status='ativo')
    return render_template('ordem_producao/form.html', is_create=True, products=products, query=query, po=None, components=[])

@ordem_producao_bp.route('/<po_id>')
def detail(po_id):
    """Detalhes da Ordem de Produção."""
    try:
        po = ordem_producao_service.get_by_id(po_id)
        if not po:
            flash('Ordem de Produção não encontrada.', 'error')
            return redirect(url_for('ordem_producao.index'))

        # Buscar componentes: da subcoleção se já iniciou produção, senão da BOM
        components = ordem_producao_service.get_components(po_id)
        if not components:
            # Se não há subcoleção (ainda DRAFT), buscar da BOM do produto
            bom_components = product_service.get_bom_components(po['productId'])
            quantity_to_produce = po['quantityToProduce']
            components = []
            for comp in bom_components:
                # Para DRAFT, ainda não há consumo
                required = comp['bom_quantity'] * quantity_to_produce
                components.append({
                    'componentName': comp['name'],
                    'quantityRequired': required,
                    'quantityConsumed': 0.0,
                    'componentId': comp['id']
                })

        # Calcular progresso
        progress_percentage = 0
        if po['quantityToProduce'] > 0:
            progress_percentage = (po['quantityProduced'] / po['quantityToProduce']) * 100

        return render_template('ordem_producao/detail.html', po=po, components=components, progress_percentage=progress_percentage)
    except Exception as e:
        flash(f'Erro ao carregar detalhes: {str(e)}', 'error')
        return redirect(url_for('ordem_producao.index'))

@ordem_producao_bp.route('/<po_id>/edit', methods=['GET', 'POST'])
def edit(po_id):
    """Edita Ordem de Produção em DRAFT."""
    if request.method == 'POST':
        try:
            quantity_to_produce = float(request.form.get('quantity_to_produce', 0))
            notes = request.form.get('notes', '')

            po = ordem_producao_service.update_draft(po_id, quantity_to_produce=quantity_to_produce, notes=notes)
            flash('Ordem de Produção atualizada!', 'success')
            return redirect(url_for('ordem_producao.detail', po_id=po_id))
        except Exception as e:
            flash(f'Erro ao atualizar: {str(e)}', 'error')
            return redirect(url_for('ordem_producao.edit', po_id=po_id))

    # GET
    try:
        po = ordem_producao_service.get_by_id(po_id)
        if not po:
            flash('Ordem de Produção não encontrada.', 'error')
            return redirect(url_for('ordem_producao.index'))

        if po['status'] != 'DRAFT':
            flash('Apenas Ordens em Rascunho podem ser editadas.', 'error')
            return redirect(url_for('ordem_producao.detail', po_id=po_id))


        # Buscar componentes da BOM com detalhes de estoque usando a função centralizada
        deposito_para_producao = app_config_service.get_config('default_production_deposit_id') or 'principal'
        components_with_stock = product_service.get_bom_components(po['productId'], deposito_id=deposito_para_producao)
        
        components = []
        for comp in components_with_stock:
            required = comp['bom_quantity'] * po['quantityToProduce']
            available = comp.get('available_stock', 0)
            
            components.append({
                'componentName': comp['name'],
                'componentId': comp['id'],
                'quantityRequired': required,
                'quantityConsumed': 0.0, # Em DRAFT, o consumo é sempre 0
                'current_stock': comp.get('physical_stock', 0),
                'reserved_stock': comp.get('reserved_stock', 0),
                'available_stock': available,
                'after_production_stock': available - required,
                'is_available': available >= required
            })

        return render_template('ordem_producao/form.html', is_create=False, products=[], query='', po=po, components=components)
    except Exception as e:
        flash(f'Erro ao carregar: {str(e)}', 'error')
        return redirect(url_for('ordem_producao.index'))

@ordem_producao_bp.route('/<po_id>/start', methods=['POST'])
def start(po_id):
    """Inicia produção."""
    try:
        po = ordem_producao_service.start_production(po_id)
        flash('Produção iniciada com sucesso! Estoque reservado.', 'success')
    except Exception as e:
        flash(f'Erro ao iniciar produção: {str(e)}', 'error')
    return redirect(url_for('ordem_producao.detail', po_id=po_id))

@ordem_producao_bp.route('/<po_id>/deliver', methods=['POST'])
def deliver(po_id):
    """Entrega produção."""
    try:
        quantity_delivered = float(request.form.get('quantity_delivered', 0))
        po = ordem_producao_service.deliver_production(po_id, quantity_delivered)
        flash('Produção entregue com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao entregar produção: {str(e)}', 'error')
    return redirect(url_for('ordem_producao.detail', po_id=po_id))

@ordem_producao_bp.route('/<po_id>/pause', methods=['POST'])
def pause(po_id):
    """Pausa produção."""
    try:
        po = ordem_producao_service.pause_production(po_id)
        flash('Produção pausada.', 'warning')
    except Exception as e:
        flash(f'Erro ao pausar: {str(e)}', 'error')
    return redirect(url_for('ordem_producao.detail', po_id=po_id))

@ordem_producao_bp.route('/<po_id>/resume', methods=['POST'])
def resume(po_id):
    """Retoma produção."""
    try:
        po = ordem_producao_service.resume_production(po_id)
        flash('Produção retomada.', 'success')
    except Exception as e:
        flash(f'Erro ao retomar: {str(e)}', 'error')
    return redirect(url_for('ordem_producao.detail', po_id=po_id))

@ordem_producao_bp.route('/<po_id>/cancel', methods=['POST'])
def cancel(po_id):
    """Cancela produção."""
    try:
        po = ordem_producao_service.cancel_production(po_id)
        flash('Produção cancelada. Reservas estornadas.', 'warning')
    except Exception as e:
        flash(f'Erro ao cancelar: {str(e)}', 'error')
    return redirect(url_for('ordem_producao.detail', po_id=po_id))

# API endpoints
@ordem_producao_bp.route('/api/products/<product_id>/bom')
def api_get_bom(product_id):
    """API: Busca BOM do produto para preview."""
    try:
        product = product_service.get_by_id(product_id)
        if not product:
            return jsonify({'error': 'Produto não encontrado'}), 404

        deposito_para_producao = app_config_service.get_config('default_production_deposit_id') or 'principal'
        bom_components_with_stock = product_service.get_bom_components(product_id, deposito_id=deposito_para_producao)
        quantity_to_produce = float(request.args.get('quantity', 1))

        components_data = []
        total_available = True

        for comp in bom_components_with_stock:
            required = comp['bom_quantity'] * quantity_to_produce
            available = comp.get('available_stock', 0)
            is_available = available >= required

            components_data.append({
                'name': comp['name'],
                'current_stock': comp.get('physical_stock', 0),
                'reserved_stock': comp.get('reserved_stock', 0),
                'available_stock': available,
                'required': required,
                'after_production_stock': available - required,
                'is_available': is_available
            })

            if not is_available:
                total_available = False

        return jsonify({
            'components': components_data,
            'total_available': total_available
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@ordem_producao_bp.route('/api/search_products')
def api_search_products():
    """API: Busca produtos."""
    query = request.args.get('q', '')
    try:
        products = product_service.search_produtos(query, limit=20, status='ativo')
        return jsonify(products)
    except Exception as e:
        return jsonify({'error': str(e)}), 500





