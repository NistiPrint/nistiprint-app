import os
from pathlib import Path
from dotenv import load_dotenv
import logging

def load_nistiprint_env():
    """
    Localiza e carrega o arquivo .env buscando do diretório atual para cima.
    Garante que variáveis de ambiente estejam disponíveis para nistiprint-shared.
    """
    current_dir = Path(os.getcwd())
    
    # Busca o .env no diretório atual e nos pais (até 4 níveis acima para cobrir subpastas da API/Worker)
    env_path = None
    for path in [current_dir] + list(current_dir.parents)[:4]:
        candidate = path / '.env'
        if candidate.exists():
            env_path = candidate
            break
            
    if env_path:
        load_dotenv(dotenv_path=env_path)
        # Opcional: print para debug durante a transição
        # print(f"✓ Ambiente carregado de: {env_path}")
        return True
    
    logging.warning("Arquivo .env não localizado. Certifique-se de que as variáveis de ambiente estão configuradas no sistema.")
    return False
