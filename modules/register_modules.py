"""
Script to register platform modules in the integration marketplace
"""
from services.integration_module_service import integration_module_service
from modules.platform_modules import get_all_platform_modules


def register_platform_modules():
    """Register all platform modules in the marketplace"""
    print("Registering platform modules in the integration marketplace...")
    
    modules = get_all_platform_modules()
    
    for module in modules:
        try:
            # Check if module already exists by name
            existing_modules = integration_module_service.get_all_modules()
            module_exists = any(m.name == module.name for m in existing_modules)
            
            if not module_exists:
                module_id = integration_module_service.create_module(module)
                print(f"Registered module '{module.name}' with ID: {module_id}")
            else:
                print(f"Module '{module.name}' already exists, skipping...")
        except Exception as e:
            print(f"Error registering module '{module.name}': {e}")
    
    print("Platform modules registration completed!")


if __name__ == "__main__":
    register_platform_modules()