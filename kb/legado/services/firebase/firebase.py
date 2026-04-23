import os
import json
import firebase_admin
from firebase_admin import credentials

def get_firebase_credentials():
    """
    Obtém as credenciais do Firebase.
    Suporte para arquivo firebase_credentials.json ou variável de ambiente FIREBASE_CREDENTIALS
    """
    # Primeiro tenta ler do arquivo
    cred_file_path = 'firebase_credentials.json'
    if os.path.exists(cred_file_path):
        print(f"Encontrado arquivo de credenciais: {cred_file_path}")
        with open(cred_file_path, 'r') as f:
            return json.load(f)

    # Se não encontrou arquivo, tenta variável de ambiente
    cred_json_str = os.environ.get('FIREBASE_CREDENTIALS')
    if cred_json_str:
        print("Usando credenciais da variável de ambiente FIREBASE_CREDENTIALS")
        try:
            return json.loads(cred_json_str)
        except json.JSONDecodeError:
            print("ERRO: FIREBASE_CREDENTIALS não é um JSON válido")
            return None
    else:
        print("AVISO: Nenhuma credencial do Firebase encontrada.")
        print("Para configurar:")
        print("1. Baixe o arquivo JSON de credenciais do console Firebase")
        print("2. Ou configure a variável de ambiente FIREBASE_CREDENTIALS")
        return None

def initialize_firebase():
    """Initializes Firebase Admin SDK."""
    # Verificar se o Firebase já foi inicializado
    try:
        firebase_admin.get_app()
        print("Firebase já está inicializado")
        return True
    except ValueError:
        # Firebase ainda não foi inicializado, proceder com a inicialização
        pass

    cred_json = get_firebase_credentials()

    if cred_json:
        try:
            cred = credentials.Certificate(cred_json)
            firebase_admin.initialize_app(cred)
            print("Firebase inicializado com sucesso!")
            return True
        except Exception as e:
            print(f"Erro ao inicializar Firebase: {e}")
            return False
    else:
        print("Erro: Credenciais do Firebase não encontradas")
        return False
