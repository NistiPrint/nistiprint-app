from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
from services.composition_template_service import composition_template_service
from services.product_service import product_service
from services.category_service import category_service
from services.tag_service import tag_service
import json

composition_templates_bp = Blueprint('composition_templates', __name__, url_prefix='/templates/composition')

@composition_templates_bp.route('', methods=['GET'])
def list_templates():
    """Lists all composition templates."""
    try:
        templates = composition_template_service.get_all_templates()
        return render_template('composition_template/list.html', templates=templates)
    except Exception as e:
        flash(f'Erro ao carregar templates de composição: {str(e)}', 'error')
        return render_template('composition_template/list.html', templates=[])

@composition_templates_bp.route('/novo', methods=['GET', 'POST'])
def create_template():
    """Creates a new composition template."""
    try:
        if request.method == 'POST':
            name = request.form.get('name')
            description = request.form.get('description')
            
            new_template = composition_template_service.create_template(name, description)
            flash(f'Template "{new_template["name"]}" criado com sucesso!', 'success')
            return redirect(url_for('composition_templates.edit_template', template_id=new_template['id']))

        return render_template('composition_template/form.html', template=None)
    except ValueError as e:
        flash(f'Erro de validação: {str(e)}', 'error')
        return render_template('composition_template/form.html', template=None)
    except Exception as e:
        flash(f'Erro ao criar template: {str(e)}', 'error')
        return render_template('composition_template/form.html', template=None)

@composition_templates_bp.route('/<template_id>/editar', methods=['GET', 'POST'])
def edit_template(template_id):
    """Edits an existing composition template."""
    try:
        template = composition_template_service.get_template_by_id(template_id)
        if not template:
            flash('Template não encontrado', 'error')
            return redirect(url_for('composition_templates.list_templates'))

        if request.method == 'POST':
            name = request.form.get('name')
            description = request.form.get('description')
            
            updated_template = composition_template_service.update_template(template_id, name, description)
            flash(f'Template "{updated_template["name"]}" atualizado com sucesso!', 'success')
            return redirect(url_for('composition_templates.edit_template', template_id=template_id))

        template_items = []
        if template.get('items'):
            component_ids = [item['component_product_id'] for item in template['items']]
            components_map = product_service.get_by_ids(component_ids)

            for item in template['items']:
                component_data = components_map.get(item['component_product_id'])
                if component_data:
                    item['component_name'] = component_data.get('name', 'Produto Desconhecido')
                    item['component_sku'] = component_data.get('sku', 'N/A')
                    template_items.append(item)
        
        return render_template('composition_template/form.html', template=template, template_items=template_items)
    except ValueError as e:
        flash(f'Erro de validação: {str(e)}', 'error')
        return render_template('composition_template/form.html', template=template)
    except Exception as e:
        flash(f'Erro ao editar template: {str(e)}', 'error')
        return redirect(url_for('composition_templates.list_templates'))

@composition_templates_bp.route('/<template_id>/deletar', methods=['POST'])
def delete_template(template_id):
    """Deletes a composition template."""
    try:
        composition_template_service.delete_template(template_id)
        flash('Template de composição deletado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar template: {str(e)}', 'error')
    return redirect(url_for('composition_templates.list_templates'))

@composition_templates_bp.route('/<template_id>/items', methods=['POST'])
def add_template_item(template_id):
    """Adds an item to a composition template (API)."""
    try:
        data = request.get_json()
        component_product_id = data.get('component_product_id')
        quantity = data.get('quantity')

        if not component_product_id or not quantity:
            return jsonify({'error': 'ID do produto componente e quantidade são obrigatórios'}), 400
        
        composition_template_service.add_item_to_template(template_id, component_product_id, float(quantity))
        return jsonify({'success': True, 'message': 'Item adicionado ao template com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Erro ao adicionar item ao template: {str(e)}'}), 500

@composition_templates_bp.route('/<template_id>/items/<item_id>', methods=['PUT', 'DELETE'])
def manage_template_item(template_id, item_id):
    """Updates or deletes an item from a composition template (API)."""
    try:
        if request.method == 'PUT':
            data = request.get_json()
            quantity = data.get('quantity')
            if not quantity:
                return jsonify({'error': 'Quantidade é obrigatória'}), 400
            
            composition_template_service.update_template_item(template_id, item_id, float(quantity))
            return jsonify({'success': True, 'message': 'Item do template atualizado com sucesso!'})
        
        elif request.method == 'DELETE':
            composition_template_service.delete_template_item(template_id, item_id)
            return jsonify({'success': True, 'message': 'Item do template deletado com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Erro ao gerenciar item do template: {str(e)}'}), 500

@composition_templates_bp.route('/apply/<template_id>/to_product/<product_id>', methods=['POST'])
def apply_template_to_product_route(template_id, product_id):
    """Applies a composition template to a product's BOM."""
    try:
        data = request.get_json(silent=True) or {}
        overwrite_existing = data.get('overwrite_existing', False)

        composition_template_service.apply_template_to_product(template_id, product_id, overwrite_existing)
        flash('Template aplicado ao produto com sucesso!', 'success')
        return jsonify({'success': True, 'message': 'Template aplicado ao produto com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Erro ao aplicar template ao produto: {str(e)}'}), 500
