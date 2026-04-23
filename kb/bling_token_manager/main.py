import os
import requests
from datetime import datetime, timezone

from flask import Flask, request
from google.cloud import firestore
from google.cloud import secretmanager

# --- Configuração de Projetos ---
# Projeto onde os recursos (Firestore, Secrets) estão.
resource_project_id = "neolabs-nistiprint"

# --- Configuração Inicial ---
app = Flask(__name__)
# Apontar os clientes para o projeto de recursos
db = firestore.Client(project=resource_project_id)
secret_client = secretmanager.SecretManagerServiceClient() # Cliente do Secret Manager

def get_secret(secret_id, version_id="latest"):
    """
    Busca um segredo do Google Cloud Secret Manager no projeto de recursos.
    Lança uma exceção clara se o segredo não for encontrado.
    """
    # O nome do segredo DEVE incluir o ID do projeto onde ele está
    name = f"projects/{resource_project_id}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        # Relança a exceção com uma mensagem mais útil
        raise Exception(f"Falha ao buscar o segredo '{secret_id}' no projeto '{resource_project_id}'. Verifique se ele existe e se a conta de serviço tem permissão. Erro original: {e}")

# --- Endpoint de Verificação de Saúde ---
@app.route("/health", methods=["GET"])
def health_check():
    """
    Endpoint para verificação do status do serviço.
    Retorna uma confirmação de que o serviço está ativo.
    """
    return {"status": "healthy"}, 200

# --- Endpoint para Obter Token de Conta Específica ---
@app.route("/token/<cnpj>", methods=["GET"])
def get_token(cnpj):
    """
    Endpoint para obter o access_token de uma conta específica.
    Requer autenticação via header 'Authorization' com um token válido.
    """
    # Verificar autenticação
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return {"error": "Header 'Authorization' é obrigatório"}, 401

    # Extrair token (formato: Bearer <token>)
    if not auth_header.startswith('Bearer '):
        return {"error": "Formato do header 'Authorization' inválido. Use: Bearer <token>"}, 401

    provided_token = auth_header[7:]  # Remove 'Bearer '

    # Valida o token fornecido
    try:
        valid_token = get_secret("BLING_API_TOKEN")  # Secret para validação de API
        if provided_token != valid_token:
            return {"error": "Token de autenticação inválido"}, 403
    except Exception:
        return {"error": "Erro na validação do token"}, 500

    # Buscar a conta no Firestore pelo campo 'cnpj'
    try:
        # Assumindo que 'cnpj' é único na coleção
        docs = db.collection("bling_accounts").where("cnpj", "==", cnpj).stream()
        doc_list = [doc for doc in docs]
        if not doc_list:
            return {"error": "Conta não encontrada para o CNPJ fornecido"}, 404

        account = doc_list[0].to_dict()
        access_token = account.get("access_token")
        if not access_token:
            return {"error": "Token de acesso não disponível para esta conta"}, 404

        return {"cnpj": cnpj, "access_token": access_token}, 200

    except Exception as e:
        return {"error": f"Erro ao buscar conta: {str(e)}"}, 500

# --- Lógica Principal Totalmente Dinâmica ---
@app.route("/", methods=["POST"])
def refresh_all_tokens_dynamically():
    """
    Endpoint acionado pelo Cloud Scheduler.
    Varre TODAS as contas em 'bling_accounts', busca seus segredos dinamicamente
    e tenta renovar seus tokens.
    """
    print("Iniciando processo de renovação dinâmica de tokens do Bling.")
    
    accounts_ref = db.collection("bling_accounts")
    all_accounts = accounts_ref.stream()

    success_count = 0
    failure_count = 0

    for doc in all_accounts:
        doc_id = doc.id
        account_data = doc.to_dict()
        print(f"Processando documento: {doc_id}...")

        try:
            # 1. Obter o identificador a partir do campo 'cnpj'
            cnpj = account_data.get("cnpj")
            if not cnpj or len(cnpj) < 5:
                raise ValueError("Campo 'cnpj' ausente ou inválido no documento.")
            
            account_identifier = cnpj[:5]
            print(f"Identificador da conta derivado do CNPJ: {account_identifier}")

            # 2. Construir o nome dos segredos e buscá-los dinamicamente
            client_id_secret_name = f"BLING_CLIENT_ID_{account_identifier}"
            client_secret_secret_name = f"BLING_SECRET_{account_identifier}"
            
            client_id = get_secret(client_id_secret_name)
            client_secret = get_secret(client_secret_secret_name)

            # 3. Obter o refresh_token do documento
            refresh_token = account_data.get("refresh_token")
            if not refresh_token:
                raise ValueError("'refresh_token' não encontrado no documento.")

            # 4. Chamar a função de renovação com as credenciais específicas da conta
            new_tokens = refresh_bling_token(refresh_token, client_id, client_secret)

            # 5. Atualizar o documento no Firestore com sucesso
            update_data = {
                "access_token": new_tokens["access_token"],
                "refresh_token": new_tokens["refresh_token"],
                "updated_at": datetime.now(timezone.utc),
                "last_token_update_utc": datetime.now(timezone.utc),
                "token_expires_in": new_tokens["expires_in"],
                "last_token_update_error": firestore.DELETE_FIELD
            }
            accounts_ref.document(doc_id).update(update_data)
            
            print(f"SUCESSO: Token para a conta {account_identifier} (doc: {doc_id}) atualizado.")
            success_count += 1

        except Exception as e:
            # Em caso de qualquer erro (segredo não encontrado, CNPJ inválido, erro de API), registre-o
            error_message = f"ERRO ao processar doc {doc_id}: {e}"
            print(error_message)
            failure_count += 1
            accounts_ref.document(doc_id).update({
                "last_token_update_error": str(e),
                "updated_at": datetime.now(timezone.utc),
                "last_token_update_utc": datetime.now(timezone.utc)
            })

    summary = f"Processo finalizado. Sucessos: {success_count}, Falhas: {failure_count}."
    print(summary)
    return summary, 200

# --- Função Auxiliar Modificada ---
def refresh_bling_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """
    Chama a API do Bling para renovar um token usando credenciais específicas.
    """
    url = "https://www.bling.com.br/Api/v3/oauth/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    
    # As credenciais agora são passadas como parâmetros
    auth = (client_id, client_secret)

    response = requests.post(url, data=payload, auth=auth)
    response.raise_for_status()
    return response.json()

# --- Bloco de Execução (sem alteração) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))