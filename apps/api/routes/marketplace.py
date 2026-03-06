"""
Routes for integration marketplace frontend pages
"""
from flask import Blueprint, render_template, request, jsonify
from nistiprint_shared.services.integration_module_service import integration_module_service
from nistiprint_shared.services.installed_integration_service import installed_integration_service


marketplace_bp = Blueprint('marketplace', __name__, url_prefix='/marketplace')


@marketplace_bp.route('/')
def marketplace_home():
    """Main marketplace page showing available integrations"""
    try:
        # Get all available modules
        modules = integration_module_service.get_all_modules()
        
        # Convert modules to dictionaries for template
        modules_data = []
        for module in modules:
            module_dict = module.to_dict()
            module_dict['id'] = module.id
            modules_data.append(module_dict)
        
        return render_template('marketplace/index.html', modules=modules_data)
    except Exception as e:
        print(f"Error loading marketplace: {e}")
        return render_template('error.html', error=str(e)), 500


@marketplace_bp.route('/install/<module_id>')
def install_wizard(module_id):
    """Installation wizard for a specific module"""
    try:
        # Get module details
        module = integration_module_service.get_module_by_id(module_id)
        if not module:
            return render_template('error.html', error="Module not found"), 404
        
        module_data = module.to_dict()
        module_data['id'] = module.id
        
        return render_template('marketplace/install_wizard.html', module=module_data)
    except Exception as e:
        print(f"Error loading install wizard: {e}")
        return render_template('error.html', error=str(e)), 500


@marketplace_bp.route('/my-integrations')
def my_integrations():
    """Page showing user's installed integrations"""
    try:
        # In a real app, user_id would come from authentication
        user_id = request.args.get('user_id', 'default_user')  # Placeholder
        
        # Get user's installed integrations
        installations = installed_integration_service.get_all_installed(user_id=user_id)
        
        installations_data = []
        for installation in installations:
            installation_dict = installation.to_dict()
            installation_dict['id'] = installation.id
            
            # Get module info for display
            module = integration_module_service.get_module_by_id(installation.module_id)
            if module:
                installation_dict['module_name'] = module.name
                installation_dict['module_icon'] = module.icon_url
                installation_dict['module_description'] = module.description
            
            installations_data.append(installation_dict)
        
        return render_template('marketplace/my_integrations.html', installations=installations_data)
    except Exception as e:
        print(f"Error loading user integrations: {e}")
        return render_template('error.html', error=str(e)), 500





