from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from nistiprint_shared.services.uom_conversion_service import uom_conversion_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service

uom_conversions_bp = Blueprint('uom_conversions_bp', __name__, url_prefix='/cadastros/uom-conversions')
uom_conversions_api_bp = Blueprint('uom_conversions_api_bp', __name__, url_prefix='/api/v2/cadastros/uom-conversions')

# API UoM Conversions routes
@uom_conversions_api_bp.route('/', methods=['GET'])
def api_index():
    """Lists all UoM conversions (API)."""
    # Get all conversions directly from the service with product names already joined
    all_conversions = uom_conversion_service.get_all_conversions()

    return jsonify({'conversions': all_conversions})

@uom_conversions_api_bp.route('/', methods=['POST'])
def api_new_conversion():
    """Handles creation of a new UoM conversion (API)."""
    data = request.get_json()
    product_id = data.get('product_id')
    from_unit_id = data.get('from_unit_id')
    to_unit_id = data.get('to_unit_id')
    conversion_factor = data.get('conversion_factor')
    
    if not all([product_id, from_unit_id, to_unit_id, conversion_factor]):
        return jsonify({'error': 'Dados incompletos.'}), 400

    try:
        uom_conversion_service.create_conversion(product_id, from_unit_id, to_unit_id, float(conversion_factor))
        return jsonify({'success': True, 'message': 'Proporção criada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@uom_conversions_api_bp.route('/<conversion_id>', methods=['GET'])
def api_get_conversion(conversion_id):
    """Retrieves a single UoM conversion (API)."""
    conversion = uom_conversion_service.get_by_id(conversion_id)
    if not conversion:
        return jsonify({'error': 'Proporção não encontrada.'}), 404
    
    all_products, _ = product_service.get_products(per_page=9999)
    units = unit_of_measure_service.get_all()
    return jsonify({'conversion': conversion, 'products': all_products, 'units': units})

@uom_conversions_api_bp.route('/<conversion_id>', methods=['PUT'])
def api_edit_conversion(conversion_id):
    """Handles editing an existing UoM conversion (API)."""
    data = request.get_json()
    from_unit_id = data.get('from_unit_id')
    to_unit_id = data.get('to_unit_id')
    conversion_factor = data.get('conversion_factor')

    if not all([from_unit_id, to_unit_id, conversion_factor]):
        return jsonify({'error': 'Dados incompletos.'}), 400

    try:
        uom_conversion_service.update_conversion(conversion_id, from_unit_id, to_unit_id, float(conversion_factor))
        return jsonify({'success': True, 'message': 'Proporção atualizada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@uom_conversions_api_bp.route('/<conversion_id>', methods=['DELETE'])
def api_delete_conversion(conversion_id):
    """Handles deletion of a UoM conversion (API)."""
    try:
        uom_conversion_service.delete_conversion(conversion_id)
        return jsonify({'success': True, 'message': 'Proporção deletada com sucesso!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

# Regular UoM Conversions routes
@uom_conversions_bp.route('/')
def index():
    """Lists all UoM conversions."""
    # Get all conversions directly from the service with product names already joined
    all_conversions = uom_conversion_service.get_all_conversions()

    return render_template('uom_conversions/list.html', conversions=all_conversions)

@uom_conversions_bp.route('/new', methods=['GET', 'POST'])
def new_conversion():
    """Handles creation of a new UoM conversion."""
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        from_unit_id = request.form.get('from_unit_id')
        to_unit_id = request.form.get('to_unit_id')
        conversion_factor = request.form.get('conversion_factor', type=float)
        
        if not all([product_id, from_unit_id, to_unit_id, conversion_factor]):
            flash('Dados incompletos.', 'danger')
            return redirect(url_for('uom_conversions_bp.new_conversion'))

        try:
            uom_conversion_service.create_conversion(product_id, from_unit_id, to_unit_id, float(conversion_factor))
            flash('Proporção criada com sucesso!', 'success')
            return redirect(url_for('uom_conversions_bp.index'))
        except Exception as e:
            flash(f'Erro ao criar proporção: {e}', 'danger')
            
    all_products, _ = product_service.get_products(per_page=9999)
    units = unit_of_measure_service.get_all()
    return render_template('uom_conversions/form.html', conversion=None, products=all_products, units=units)

@uom_conversions_bp.route('/<conversion_id>/edit', methods=['GET', 'POST', 'PUT'])
def edit_conversion(conversion_id):
    """Handles editing an existing UoM conversion."""
    conversion = uom_conversion_service.get_by_id(conversion_id)
    if not conversion:
        flash('Proporção não encontrada.', 'danger')
        return redirect(url_for('uom_conversions_bp.index'))

    if request.method in ['POST', 'PUT']:
        from_unit_id = request.form.get('from_unit_id')
        to_unit_id = request.form.get('to_unit_id')
        conversion_factor = request.form.get('conversion_factor', type=float)

        if not all([from_unit_id, to_unit_id, conversion_factor]):
            flash('Dados incompletos.', 'danger')
            return redirect(url_for('uom_conversions_bp.edit_conversion', conversion_id=conversion_id)) # Fallback

        try:
            uom_conversion_service.update_conversion(conversion_id, from_unit_id, to_unit_id, float(conversion_factor))
            flash('Proporção atualizada com sucesso!', 'success')
            return redirect(url_for('uom_conversions_bp.index'))
        except Exception as e:
            flash(f'Erro ao atualizar proporção: {e}', 'danger')
            
    all_products, _ = product_service.get_products(per_page=9999)
    units = unit_of_measure_service.get_all()
    # We pass the full conversion object to the form
    return render_template('uom_conversions/form.html', conversion=conversion, products=all_products, units=units)

@uom_conversions_bp.route('/<conversion_id>/delete', methods=['POST', 'DELETE'])
def delete_conversion(conversion_id):
    """Handles deletion of a UoM conversion."""
    try:
        uom_conversion_service.delete_conversion(conversion_id)
        flash('Proporção deletada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar proporção: {e}', 'danger')
    return redirect(url_for('uom_conversions_bp.index'))





