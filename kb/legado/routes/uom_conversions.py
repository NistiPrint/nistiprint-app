from flask import Blueprint, render_template, request, flash, redirect, url_for
from services.uom_conversion_service import uom_conversion_service
from services.product_service import product_service

uom_conversions_bp = Blueprint('uom_conversions_bp', __name__, url_prefix='/uom-conversions')

@uom_conversions_bp.route('/')
def index():
    """Lists all UoM conversions."""
    # This could be inefficient if there are many products/conversions.
    # For now, we fetch all and process in memory.
    all_products, _ = product_service.get_products(per_page=9999)
    product_map = {p['id']: p for p in all_products}
    
    all_conversions = []
    for product in all_products:
        conversions = uom_conversion_service.get_conversions_for_product(product['id'])
        for conv in conversions:
            conv['productName'] = product.get('name', 'N/A')
            all_conversions.append(conv)
            
    return render_template('uom_conversions/list.html', conversions=all_conversions)

@uom_conversions_bp.route('/new', methods=['GET', 'POST'])
def new_conversion():
    """Handles creation of a new UoM conversion."""
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        unit_name = request.form.get('unit_name')
        conversion_factor = request.form.get('conversion_factor', type=float)
        try:
            uom_conversion_service.create_conversion(product_id, unit_name, conversion_factor)
            flash(f'Proporção "{unit_name}" criada com sucesso!', 'success')
            return redirect(url_for('uom_conversions_bp.index'))
        except Exception as e:
            flash(f'Erro ao criar proporção: {e}', 'danger')

    all_products, _ = product_service.get_products(per_page=9999)
    return render_template('uom_conversions/form.html', conversion=None, products=all_products)

@uom_conversions_bp.route('/<conversion_id>/edit', methods=['GET', 'POST'])
def edit_conversion(conversion_id):
    """Handles editing an existing UoM conversion."""
    conversion = uom_conversion_service.get_by_id(conversion_id)
    if not conversion:
        flash('Proporção não encontrada.', 'danger')
        return redirect(url_for('uom_conversions_bp.index'))

    if request.method == 'POST':
        unit_name = request.form.get('unit_name')
        conversion_factor = request.form.get('conversion_factor', type=float)
        try:
            uom_conversion_service.update_conversion(conversion_id, unit_name, conversion_factor)
            flash(f'Proporção "{unit_name}" atualizada com sucesso!', 'success')
            return redirect(url_for('uom_conversions_bp.index'))
        except Exception as e:
            flash(f'Erro ao atualizar proporção: {e}', 'danger')

    all_products, _ = product_service.get_products(per_page=9999)
    # We pass the full conversion object to the form
    return render_template('uom_conversions/form.html', conversion=conversion, products=all_products)

@uom_conversions_bp.route('/<conversion_id>/delete', methods=['POST'])
def delete_conversion(conversion_id):
    """Handles deletion of a UoM conversion."""
    try:
        uom_conversion_service.delete_conversion(conversion_id)
        flash('Proporção deletada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar proporção: {e}', 'danger')
    return redirect(url_for('uom_conversions_bp.index'))
