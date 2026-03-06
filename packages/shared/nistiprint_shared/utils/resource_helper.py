import os
from pathlib import Path

def get_shared_resource_path(relative_path):
    """
    Retorna o caminho absoluto para um recurso dentro do pacote nistiprint_shared.
    Exemplo: get_shared_resource_path('templates/prompts/prompt_template.txt')
    """
    # Localiza a raiz do pacote nistiprint_shared
    package_root = Path(__file__).parent.parent
    resource_path = package_root / relative_path
    
    if not resource_path.exists():
        # Fallback para busca no diretório de execução caso não esteja no pacote
        fallback_path = Path(os.getcwd()) / relative_path
        if fallback_path.exists():
            return str(fallback_path)
            
    return str(resource_path)

def get_prompt_template_path():
    """Atalho para obter o caminho do template de prompt principal."""
    return get_shared_resource_path('templates/prompts/prompt_template.txt')
