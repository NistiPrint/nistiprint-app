import os
import importlib

# Exportação dinâmica de todos os módulos na pasta services
# Isso permite que 'from nistiprint_shared.services import any_service' funcione
_current_dir = os.path.dirname(__file__)
for file in os.listdir(_current_dir):
    if file.endswith(".py") and file != "__init__.py":
        module_name = file[:-3]
        try:
            # Importa o módulo e o adiciona ao namespace do pacote
            module = importlib.import_module(f".{module_name}", package=__package__)
            globals()[module_name] = module
        except Exception as e:
            # Silenciosamente ignora falhas de importação durante o carregamento dinâmico
            pass

# Exportações manuais importantes para manter compatibilidade direta
from nistiprint_shared.services.supabase_storage_service import supabase_storage_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.services.bling.bling_client import BlingClient

