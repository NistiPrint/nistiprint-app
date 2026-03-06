"""
Bling Client for Integration with Bling API

This module has been updated to use Supabase instead of Firestore for storing account information.
"""
import datetime
import base64
import requests
import time
from typing import List

from nistiprint_shared.database.supabase_db_service import supabase_db
from ...constants import PLATFORM_X_CNPJ


class BlingClient:
    """Cliente para integração com a API do Bling.

    Encapsula todas as operações de autenticação e comunicação com a API do Bling,
    usando credenciais recebidas como parâmetro.
    """

    def __init__(self, account_data):
        """Inicializa o cliente Bling com dados de uma conta específica.

        Args:
            account_data (dict): Dados da conta incluem:
                - access_token (str)
                - refresh_token (str)
                - expires_in (int)
                - client_id (str)
                - client_secret (str)
                - created_at (datetime/str)
                - updated_at (datetime/str)
                - platform (str, opcional)
        """
        # Configurar credenciais diretamente dos dados fornecidos
        self.access_token = account_data.get('access_token')
        self.refresh_token = account_data.get('refresh_token')
        # Converter expires_in para int se vier como string do Supabase
        expires_in = account_data.get('expires_in')
        if isinstance(expires_in, str):
            try:
                self.expires_in = int(expires_in)
            except ValueError:
                self.expires_in = 0  # Valor padrão se conversão falhar
        else:
            self.expires_in = expires_in or 0
        self.client_id = account_data.get('client_id')
        self.client_secret = account_data.get('client_secret')

        # Timestamp da criação das credenciais
        if 'created_at' in account_data:
            created_at = account_data['created_at']
            if isinstance(created_at, str):
                self.created_at = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                self.created_at = created_at
        else:
            self.created_at = datetime.datetime.now(datetime.timezone.utc)

        # Timestamp da última atualização do token (usado para calcular expiração)
        if 'updated_at' in account_data:
            updated_at = account_data['updated_at']
            if isinstance(updated_at, str):
                self.updated_at = datetime.datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            else:
                self.updated_at = updated_at
        else:
            self.updated_at = self.created_at  # Fallback se não houver updated_at

        # Salvar dados da conta para referência
        self.account_data = account_data
        # Armazenar informações da plataforma e instância
        self.platform = account_data.get('platform_name', '').lower()
        self.instance_name = account_data.get('instance_name', '')
        self.versao = account_data.get('versao_api', '') or self._get_api_version_for_platform(self.platform)

        # Cache de token para evitar múltiplas validações desnecessárias
        self._cached_token = None
        self._token_expires_at = None  # datetime quando o token cacheado expira

    def _get_api_version_for_platform(self, platform: str):
        """Determines the API version for a given platform."""
        from ...constants import PLATFORM_X_BLING_VERSION
        return PLATFORM_X_BLING_VERSION.get(platform, 'antiga')  # Default to 'antiga'

    @staticmethod
    def create_client(**kwargs):
        """Cria uma instância de BlingClient baseado em diferentes identificadores.

        Args:
            **kwargs: Pode incluir:
                - account_name (str): Nome da conta
                - client_id (str): ID do cliente
                - cnpj (str): CNPJ da conta

        Returns:
            BlingClient: Instância configurada com os dados da conta

        Raises:
            ValueError: Se nenhum identificador válido for fornecido ou conta não encontrada
        """
        from nistiprint_shared.database.supabase_db_service import supabase_db

        # Validar parâmetros
        supported_keys = {'account_name', 'client_id', 'cnpj'}
        provided_keys = set(kwargs.keys()) & supported_keys

        if not provided_keys:
            raise ValueError("Pelo menos um dos seguintes identificadores deve ser fornecido: account_name, client_id, cnpj")

        print(f"🔍 BlingClient.create_client - Identificadores fornecidos: {kwargs}")

        # Buscar na tabela bling_accounts no Supabase
        query = supabase_db.table('bling_accounts')
        
        account_data = None

        if 'cnpj' in provided_keys:
            cnpj = kwargs['cnpj']
            print(f"🔍 DEBUG: Buscando conta pelo CNPJ: '{cnpj}'")

            # Busca usando eq query no campo 'cnpj'
            try:
                response = query.select("*").eq('cnpj', cnpj).limit(1).execute()
                if response.data:
                    account_data = response.data[0]
                    print(f"🔍 DEBUG: Document encontrado para CNPJ '{cnpj}': exists={bool(account_data)}")
                else:
                    print(f"🔍 DEBUG: Nenhum documento encontrado para CNPJ '{cnpj}'")
            except Exception as e:
                print(f"❌ DEBUG: Erro na busca por CNPJ: {e}")
                account_data = None
        else:
            print(f"🔍 DEBUG: Busca por outros campos não implementada (account_name/client_id)")
            # Para account_name ou client_id, faremos uma busca mais complexa
            try:
                response = query.select("*").execute()
                for row in response.data:
                    if ('account_name' in provided_keys and row.get('account_name') == kwargs['account_name']) or \
                       ('client_id' in provided_keys and row.get('client_id') == kwargs['client_id']):
                        account_data = row
                        print(f"🔍 DEBUG: Document encontrado por account_name/client_id: exists={bool(account_data)}")
                        break
                else:
                    print(f"🔍 DEBUG: Nenhum documento encontrado para os critérios alternativos")
            except Exception as e:
                print(f"❌ DEBUG: Erro na busca por outros critérios: {e}")
                account_data = None

        if not account_data:
            print(f"❌ ERROR: Conta não encontrada com os identificadores: {kwargs}")
            raise ValueError(f"Conta não encontrada com os identificadores fornecidos: {kwargs}")

        # Preparar dados da conta
        account_data['id'] = account_data.get('id')  # Salvar o ID do registro

        print(f"✅ DEBUG: Conta encontrada! Document ID: '{account_data['id']}', Dados: account_name='{account_data.get('account_name','N/A')}'")

        return BlingClient(account_data)

    @staticmethod
    def create_client_for_platform(platform_name, instance_name: str = None):
        """Cria uma instância de BlingClient para uma plataforma específica, usando configurações.

        Args:
            platform_name (str): Nome da plataforma (ex: 'Shopee', 'Amazon').
            instance_name (str, optional): Nome específico da instância (para múltiplas contas da mesma plataforma).

        Returns:
            BlingClient: Instância configurada.

        Raises:
            ValueError: Se não for possível determinar a conta para a plataforma.
        """
        from nistiprint_shared.services.app_config_service import app_config_service
        from nistiprint_shared.services.conta_bling_service import conta_bling_service
        from ...constants import PLATFORM_X_CNPJ

        print(f"🔍 Buscando cliente Bling para plataforma: {platform_name}, instância: {instance_name}")

        # 1. Tentar buscar configuração dinâmica por binding específico
        bindings = app_config_service.get_config('platform_account_bindings') or {}

        # Criar chave composta se tiver nome de instância
        composite_key = f"{platform_name}:{instance_name}" if instance_name else platform_name

        account_id = bindings.get(composite_key)
        if not account_id:
            # Tentar encontrar por nome da plataforma apenas
            account_id = bindings.get(platform_name)

        if not account_id and instance_name:
            # Tentar encontrar por plataforma + nome da instância
            account_id = bindings.get(f"{platform_name}:{instance_name}")

        if account_id:
            print(f"✅ Configuração encontrada: Chave '{composite_key}' -> Account ID '{account_id}'")
            account = conta_bling_service.get_by_id(account_id)
            if account:
                return BlingClient(account)
            else:
                print(f"⚠️ Conta configurada '{account_id}' não encontrada. Tentando fallback.")

        # 2. Tentar buscar por plataforma e nome da instância (para múltiplas contas da mesma plataforma)
        if instance_name:
            account = conta_bling_service.get_by_platform_and_instance(platform_name, instance_name)
            if account:
                print(f"✅ Conta encontrada por plataforma e instância: {platform_name}:{instance_name}")
                return BlingClient(account)

        # 3. Tentar buscar qualquer conta para a plataforma (retornar primeira encontrada)
        accounts = conta_bling_service.get_by_platform(platform_name)
        if accounts:
            # Retornar a primeira conta encontrada
            print(f"✅ Primeira conta encontrada para plataforma: {platform_name}")
            return BlingClient(accounts[0])

        # 4. Fallback para constantes (legacy)
        cnpj = PLATFORM_X_CNPJ.get(platform_name.lower())
        if cnpj:
            print(f"ℹ️ Fallback para constants: Plataforma '{platform_name}' -> CNPJ '{cnpj}'")
            return BlingClient.create_client(cnpj=cnpj)

        raise ValueError(f"Nenhuma conta Bling configurada ou encontrada para a plataforma: {platform_name}")

    def _get_valid_token(self):
        """Retorna o token de acesso atual."""
        return self.access_token

    def _update_token_cache(self, now):
        """Atualiza o cache de token com tempo de expiração baseado no refresh threshold."""
        # Garantir que updated_at seja um datetime com timezone
        if hasattr(self.updated_at, 'date'):
            if self.updated_at.tzinfo is None:
                token_updated_at = self.updated_at.replace(tzinfo=datetime.timezone.utc)
            else:
                token_updated_at = self.updated_at
        else:
            if isinstance(self.updated_at, datetime.date):
                token_updated_at = datetime.datetime.combine(self.updated_at, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
            elif isinstance(self.updated_at, str):
                try:
                    token_updated_at = datetime.datetime.fromisoformat(self.updated_at.replace('Z', '+00:00'))
                except ValueError:
                    # Fallback para created_at se updated_at estiver mal formatado
                    token_updated_at = self.created_at if hasattr(self, 'created_at') and self.created_at else datetime.datetime.now(datetime.timezone.utc)
            else:
                token_updated_at = self.updated_at

        # Garantir timezone
        if token_updated_at.tzinfo is None:
            token_updated_at = token_updated_at.replace(tzinfo=datetime.timezone.utc)

        full_expiration_time = token_updated_at + datetime.timedelta(seconds=self.expires_in)
        # Cache expira quando chegamos no refresh threshold (15 minutos antes)
        cache_expires_at = full_expiration_time - datetime.timedelta(minutes=15)

        self._cached_token = self.access_token
        self._token_expires_at = cache_expires_at

        print(f"✅ DEBUG: Cache de token atualizado - expira em {(cache_expires_at - now).total_seconds()/60:.1f} minutos")

    def _refresh_token(self):
        """Faz refresh do token de acesso.

        Returns:
            dict: Novos tokens de acesso {'access_token', 'refresh_token', 'expires_in'}
        """
        # Verificar se temos refresh_token válido
        if not self.refresh_token or len(str(self.refresh_token)) == 0:
            print(f"❌ Refresh token não disponível para a conta {self.account_data.get('account_name', 'N/A')}")
            raise Exception("Refresh token não está disponível")

        url = 'https://bling.com.br/Api/v3/oauth/token'
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()}',
        }
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
        }

        print(f"🔄 Debug refresh: Usando refresh_token com {len(str(self.refresh_token))} caracteres")

        try:
            response = requests.post(url, headers=headers, data=data, timeout=30)
            response.raise_for_status()
            response_data = response.json()

            if 'access_token' in response_data:
                new_tokens = {
                    'access_token': response_data['access_token'],
                    'refresh_token': response_data['refresh_token'],
                    'expires_in': response_data['expires_in']
                }

                # Atualizar a instância com os novos tokens
                self.access_token = response_data['access_token']
                self.refresh_token = response_data['refresh_token']
                # Garantir que expires_in seja um inteiro
                expires_in_new = response_data['expires_in']
                if isinstance(expires_in_new, str):
                    try:
                        self.expires_in = int(expires_in_new)
                    except ValueError:
                        self.expires_in = 0
                else:
                    self.expires_in = expires_in_new or 0
                self.updated_at = datetime.datetime.now(datetime.timezone.utc)

                # Invalidar cache do token pois foi atualizado
                self._cached_token = None
                self._token_expires_at = None

                # Atualizar dados no Supabase
                account_id = self.account_data.get('id')
                if account_id:
                    try:
                        update_data = {
                            'access_token': self.access_token,
                            'refresh_token': self.refresh_token,
                            'expires_in': self.expires_in,
                            'updated_at': self.updated_at.isoformat()
                        }
                        
                        # Atualizar no Supabase
                        supabase_db.table('bling_accounts').update(update_data).eq('id', account_id).execute()
                        print(f"✅ Tokens atualizados no Supabase para conta {account_id}")
                    except Exception as e:
                        print(f"⚠️  Falha ao atualizar tokens no Supabase: {e}")

                return new_tokens
            else:
                error_msg = response_data.get('error_description', response_data.get('error', 'Erro desconhecido'))
                print(f"❌ Erro na resposta API refresh: {error_msg}")
                raise Exception(f"Falha ao fazer refresh do token: {error_msg}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Erro de rede no refresh token: {e}")
            raise Exception(f"Erro de rede ao renovar token: {str(e)}")

    def _request(self, method, endpoint, **kwargs):
        """Faz uma requisição HTTP para a API do Bling.

        Args:
            method (str): Método HTTP (GET, POST, PATCH, etc.)
            endpoint (str): Endpoint da API (ex: 'produtos', 'pedidos/vendas/123')
            **kwargs: Parâmetros adicionais para requests (params, data, json, etc.)

        Returns:
            dict: Resposta JSON da API ou False em caso de erro
        """
        time.sleep(0.3)  # Throttle requests

        access_token = self._get_valid_token()

        url = f"https://api.bling.com.br/Api/v3/{endpoint}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        headers.update(kwargs.pop('headers', {}))

        try:
            response = requests.request(method.upper(), url, headers=headers, **kwargs)

            if response.status_code in [200, 201]:
                return response.json()
            else:
                print(f"Erro na API Bling - Status: {response.status_code}, Response: {response.text}")
            return False

        except requests.exceptions.RequestException as e:
            print(f"Erro de conexão com API Bling: {str(e)}")
            return False

    # ==================== MÉTODOS ADMINISTRATIVOS ====================

    def check_token_simple(self):
        """Verifica se o token é válido através de chamada simples à API (/empresas/me/dados-basicos)."""
        try:
            # Chamada direta sem usar _get_valid_token() para evitar refresh automático desnecessário
            url = f"https://api.bling.com.br/Api/v3/empresas/me/dados-basicos"
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.access_token}'
            }

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return 'data' in data

        except Exception:
            pass

        return False

    def get_basic_account_info(self):
        """Obtém informações básicas da conta através da API."""
        try:
            response = self._request('GET', 'empresas/me/dados-basicos')
            return response.get('data') if response else None
        except Exception as e:
            return None

    # ==================== MÉTODOS PÚBLICOS DA API ====================

    def get_product(self, product_id):
        """Busca informações de um produto pelo ID.

        Args:
            product_id (int): ID do produto no Bling

        Returns:
            dict: Dados do produto ou None em caso de erro
        """
        response = self._request('GET', f'produtos/{str(product_id)}')
        return response.get('data') if response else None

    def get_stores(self):
        """Busca a lista de lojas virtuais cadastradas no Bling.

        Returns:
            list: Lista de lojas virtuais ou lista vazia em caso de erro.
        """
        response = self._request('GET', 'lojas-virtuais')
        return response.get('data') if response else []

    def search_products(self, query: str, page: int = 1, per_page: int = 100):
        """Busca produtos no Bling por nome ou SKU.

        Args:
            query (str): Termo de busca (nome ou SKU).
            page (int): Número da página.
            per_page (int): Quantidade de resultados por página (limite Bling é 100).

        Returns:
            list: Lista de produtos encontrados ou lista vazia em caso de erro.
        """
        params = {
            'pagina': page,
            'limite': per_page,
            'q': query # Use 'q' parameter for general search
        }
        response = self._request('GET', 'produtos', params=params)
        return response.get('data') if response else []

    def search_products_by_skus(self, skus: List[str], page: int = 1, per_page: int = 100):
        """Busca produtos no Bling por uma lista de SKUs.

        Args:
            skus (List[str]): Lista de SKUs para buscar.
            page (int): Número da página.
            per_page (int): Quantidade de resultados por página (limite Bling é 100).

        Returns:
            list: Lista de produtos encontrados ou lista vazia em caso de erro.
        """
        if not skus:
            return []

        params = {
            'pagina': page,
            'limite': per_page,
        }
        # Add each SKU as a 'codigos[]' parameter
        for sku in skus:
            params.setdefault('codigos[]', []).append(sku)

        response = self._request('GET', 'produtos', params=params)
        return response.get('data') if response else []

    def get_order(self, order_id):
        """Busca detalhes de um pedido pelo ID.

        Args:
            order_id (int): ID do pedido no Bling

        Returns:
            dict: Dados do pedido ou None em caso de erro
        """
        response = self._request('GET', f'pedidos/vendas/{str(order_id)}')
        return response.get('data') if response else None

    def update_order_status(self, order_id, status_id):
        """Atualiza o status de um pedido.

        Args:
            order_id (int): ID do pedido
            status_id (int): ID do novo status

        Returns:
            bool: True em caso de sucesso
        """
        response = self._request('PATCH', f'pedidos/vendas/{order_id}/situacoes/{status_id}')
        return response is not False

    def generate_nfe(self, order):
        """Gera NFE para um pedido.

        Args:
            order (dict): Dados do pedido para gerar NFE

        Returns:
            dict: Pedido atualizado com status da geração da NFE
        """
        print(f'Gerando NFe para o pedido {order["numero"]}')

        try:
            response = self._request('POST', f'pedidos/vendas/{order["id"]}/gerar-nfe', timeout=30)

            if response:
                response_data = response
                print(f"NFe gerada com sucesso para pedido {order['numero']}")
                order['error'] = False
                order['error_message'] = None
                order['nfe_id'] = response_data.get('data', {}).get('idNotaFiscal')
            else:
                print(f"Falha ao gerar NFe para pedido {order['numero']}")
                order['error'] = True
                order['error_message'] = f"Falha na geração de NFE para pedido {order['numero']}"

            return order

        except requests.exceptions.RequestException as e:
            print(f"Erro na requisição para gerar NFE: {str(e)}")
            order['error'] = True
            order['error_message'] = f"Erro de conexão com a API Bling: {str(e)}"
            return order
        except Exception as e:
            print(f"Erro inesperado ao gerar NFe: {str(e)}")
            order['error'] = True
            order['error_message'] = f"Erro inesperado: {str(e)}"
            return order

    def get_orders_by_store_numbers(self, order_numbers: list):
        """Busca pedidos por números da loja.

        Args:
            order_numbers (list): Lista de números de pedido da loja

        Returns:
            tuple: (ordens_encontradas, dados_das_ordens, ids_com_numeros, pedidos_nao_encontrados)
        """
        order_ids_count = 0
        orders_found_in_bling = 0
        bling_orders_obtained_count = 0
        bling_orders_not_found = []
        bling_orders_id = []
        bling_orders_data = []
        bling_orders_id_numero = []

        # Dividir os pedidos em chunks de 100
        chunks = [order_numbers[i:i + 100] for i in range(0, len(order_numbers), 100)]

        url = "pedidos/vendas"

        for chunk in chunks:
            order_ids_count = order_ids_count + len(chunk)

            payload = '&'.join([f"numerosLojas[]={piece}" for piece in chunk])
            full_params = f"?{payload}"

            formatted_url = url + full_params

            response = self._request('GET', formatted_url)

            if response and response.get('data'):
                orders_found_in_bling += len(response['data'])

                # Criar lista de quais pieces estão faltando
                bling_orders_not_found.extend([
                    piece for piece in chunk
                    if piece not in [item['numeroLoja'] for item in response['data']]
                ])

                # Extrair todos os IDs dos pedidos e adicionar à lista
                bling_orders_id.extend([item['id'] for item in response['data']])

        # Buscar detalhes de cada pedido
        for order_id in bling_orders_id:
            order = self.get_order(order_id)
            if order is not None:
                bling_orders_data.append(order)
                bling_orders_obtained_count += 1

        bling_orders_id_numero = [
            {'id': item['id'], 'numero': item['numero']}
            for item in bling_orders_data
        ]

        return bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found

    def get_orders_by_status(self, status_id, store_id, start_date, end_date):
        """Busca pedidos por status e período.

        Args:
            status_id (int): ID do status dos pedidos
            store_id (int): ID da loja
            start_date (str): Data inicial (formato YYYY-MM-DD)
            end_date (str): Data final (formato YYYY-MM-DD)

        Returns:
            list: Lista de todos os pedidos encontrados
        """
        all_orders = []
        page = 1
        max_pages = 50  # Segurança contra loops infinitos

        while page <= max_pages:
            params = {
                'pagina': page,
                'idsSituacoes[]': status_id,
                'idLoja': store_id,
                'dataInicial': start_date,
                'dataFinal': end_date,
                'limite': 100
            }

            url = "pedidos/vendas"
            response = self._request('GET', url, params=params)

            if not response or not response.get('data'):
                break

            orders_on_page = response['data']
            all_orders.extend(orders_on_page)

            if len(orders_on_page) < 100:
                break  # Última página

            page += 1

        return all_orders

    # ==================== MÉTODOS PARA CONVERSÃO DE IDs ====================

    @staticmethod
    def convert_order_ids(platform, order_ids):
        """
        Converte IDs de pedidos da plataforma para números de pedidos na Bling.
        Faz apenas uma chamada direta para buscar pedidos por números da loja.
        Mantém a ordem original dos IDs de entrada.

        Args:
            platform (str): Nome da plataforma (shopee, amazon, mercadolivre, shein)
            order_ids (list): Lista de IDs de pedidos da plataforma

        Returns:
            dict: {'success': bool, 'converted_orders': list, 'error': str}
        """
        try:
            # Obter CNPJ da plataforma
            cnpj = PLATFORM_X_CNPJ.get(str(platform).lower())
            if not cnpj:
                return {
                    'success': False,
                    'error': f'CNPJ não encontrado para plataforma: {platform}'
                }

            # Criar cliente Bling usando CNPJ
            try:
                bling_client = BlingClient.create_client(cnpj=cnpj)
            except ValueError as e:
                return {
                    'success': False,
                    'error': str(e)
                }

            converted_orders = []
            chunk_size = 100

            for i in range(0, len(order_ids), chunk_size):
                chunk_ids = order_ids[i:i + chunk_size]

                try:
                    # Construir parâmetros da URL
                    payload = '&'.join([f"numerosLojas[]={oid}" for oid in chunk_ids])

                    # Fazer chamada direta usando _request
                    url = "pedidos/vendas"
                    response = bling_client._request('GET', url, params=payload)

                    if response and response.get('data'):
                        chunk_map = {}
                        for item in response['data']:
                            numero_loja = item.get('numeroLoja')
                            numero_pedido = item.get('numero')
                            pedido_id = item.get('id')

                            # Debug todos os campos disponíveis
                            if not numero_loja:
                                print(f"⚠️ numeroLoja não encontrado neste item. Campos disponíveis: {list(item.keys())}")

                            if numero_loja and numero_pedido and pedido_id:
                                chunk_map[str(numero_loja)] = {
                                    'id': pedido_id,
                                    'numero': numero_pedido,
                                    'numeroLoja': numero_loja
                                }
                            else:
                                print(f"⚠️ Item incompleto: numeroLoja={numero_loja}, numero={numero_pedido}, id={pedido_id}")

                        # Adicionar resultados mantendo ordem do chunk
                        for order_id in chunk_ids:
                            result = chunk_map.get(str(order_id))
                            converted_orders.append(result)

                    else:
                        # Se falhou ou não retornou dados, adicionar None para todos do chunk
                        converted_orders.extend([None] * len(chunk_ids))
                        print(f"Aviso: Falha ao buscar chunk {i//chunk_size + 1}, retornando None para {len(chunk_ids)} IDs")

                except Exception as chunk_error:
                    print(f"Erro ao processar chunk {i//chunk_size + 1}: {chunk_error}")
                    # Em caso de erro no chunk, adicionar None para todos
                    converted_orders.extend([None] * len(chunk_ids))

            return {
                'success': True,
                'converted_orders': converted_orders
            }

        except Exception as e:
            print(f"Erro em BlingClient.convert_order_ids: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # ==================== MÉTODOS ADMINISTRATIVOS ====================

    @staticmethod
    def list_accounts():
        """Lista todas as contas Bling integradas do Supabase.

        Returns:
            list: Lista de contas com informações básicas
        """
        try:
            response = supabase_db.table('bling_accounts').select("*").execute()
            accounts = []

            for row in response.data:
                account_info = {
                    'id': row.get('id'),
                    'account_name': row.get('account_name', 'N/A'),
                    'cnpj': row.get('cnpj', 'N/A'),
                    'platform': row.get('platform', 'N/A'),
                    'client_id': BlingClient._mask_sensitive_data(row.get('client_id', '')),
                    'token_status': 'ACTIVE' if row.get('access_token') else 'INACTIVE',
                    'created_at': row.get('created_at', ''),
                    'updated_at': row.get('updated_at', '')
                }
                accounts.append(account_info)

            return accounts
        except Exception as e:
            print(f"Erro ao listar contas Bling: {e}")
            return []

    def check_integration_status(self):
        """Verifica o status completo da integração.

        Returns:
            dict: Status detalhado da integração
        """
        status = {
            'account_name': self.account_data.get('account_name', 'N/A'),
            'cnpj': self.account_data.get('cnpj', 'N/A'),
            'platform': self.platform,
            'versao': self.versao,
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'tests': {}
        }

        try:
            # Teste 1: Verificar se tem token válido
            status['tests']['has_valid_token'] = self._check_token_validity()
            status['tests']['token_expiration'] = self._get_token_expiration_info()

            # Teste 2: Verificar conectividade com API
            status['tests']['api_connectivity'] = self._test_api_connectivity()

            # Teste 3: Verificar permissões (listar produtos)
            status['tests']['api_permissions'] = self._test_api_permissions()

            # Status geral
            all_tests_passed = all(test_result for test_result in status['tests'].values() if isinstance(test_result, bool))
            status['overall_status'] = 'HEALTHY' if all_tests_passed else 'ISSUES_DETECTED'

        except Exception as e:
            status['overall_status'] = 'ERROR'
            status['error'] = str(e)

        return status



    def get_account_info(self):
        """Obtém informações completas da conta integrada.

        Returns:
            dict: Informações detalhadas da conta
        """
        return {
            'account_name': self.account_data.get('account_name'),
            'cnpj': self.account_data.get('cnpj'),
            'platform': self.platform,
            'versao_api': self.versao,
            'client_id': self._mask_sensitive_data(self.account_data.get('client_id', '')),
            'token_status': self._get_token_status(),
            'created_at': self.account_data.get('created_at'),
            'last_updated': self.account_data.get('updated_at'),
            'integration_health': self.check_integration_status()['overall_status']
        }

    # ==================== MÉTODOS AUXILIARES PRIVADOS ====================

    def _check_token_validity(self):
        """Verifica se o token atual é válido."""
        try:
            return self._get_valid_token() is not None
        except Exception:
            return False

    def _get_token_expiration_info(self):
        """Obtém informações sobre expiração do token."""
        now = datetime.datetime.now(datetime.timezone.utc)

        # Usar updated_at para calcular expiração (quando o token atual foi criado/atualizado)
        if hasattr(self.updated_at, 'date'):
            # Se é um DateTime com date(), converter para datetime mantendo timezone se existir
            token_updated_at = self.updated_at
            if token_updated_at.tzinfo is None:
                # Se não tem timezone, assume UTC
                token_updated_at = token_updated_at.replace(tzinfo=datetime.timezone.utc)
        else:
            # Se já é um date ou outro tipo, converter para datetime UTC
            if isinstance(self.updated_at, datetime.date):
                token_updated_at = datetime.datetime.combine(self.updated_at, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
            else:
                # Tentar converter de string ou outro formato
                if isinstance(self.updated_at, str):
                    try:
                        token_updated_at = datetime.datetime.fromisoformat(self.updated_at.replace('Z', '+00:00'))
                    except ValueError:
                        # Fallback para created_at se updated_at estiver mal formatado
                        token_updated_at = self.created_at if hasattr(self, 'created_at') and self.created_at else datetime.datetime.now(datetime.timezone.utc)
                else:
                    token_updated_at = self.updated_at

        # Garantir que token_updated_at tenha timezone
        if token_updated_at.tzinfo is None:
            token_updated_at = token_updated_at.replace(tzinfo=datetime.timezone.utc)

        # Calcular expiração baseado em updated_at + expires_in
        expiration_time = token_updated_at + datetime.timedelta(seconds=self.expires_in)
        remaining_seconds = (expiration_time - now).total_seconds()

        return {
            'expires_at': expiration_time.isoformat(),
            'remaining_seconds': max(0, int(remaining_seconds)),
            'is_expired': remaining_seconds <= 0,
            'remaining_hours': max(0, int(remaining_seconds / 3600))
        }

    def _get_token_status(self):
        """Obtém status simplificado do token."""
        expiration_info = self._get_token_expiration_info()
        if expiration_info['is_expired']:
            return 'EXPIRED'
        elif expiration_info['remaining_hours'] < 24:
            return 'EXPIRING_SOON'
        else:
            return 'VALID'

    def _test_api_connectivity(self):
        """Testa conectividade básica com a API."""
        try:
            # Tenta fazer uma chamada simples (listar produtos com limite 1)
            response = self._request('GET', 'produtos', params={'limite': '1'})
            return response is not False and 'data' in response
        except Exception:
            return False

    def _test_api_permissions(self):
        """Testa se tem permissões adequadas na API."""
        try:
            # Testa listagem de pedidos (mais restritivo)
            response = self._request('GET', 'pedidos/vendas', params={'limite': '1'})
            return response is not False
        except Exception:
            return False

    @staticmethod
    def _mask_sensitive_data(data, show_chars=4):
        """Mascara dados sensíveis para exibição."""
        if not data or len(data) <= show_chars:
            return data
        return '*' * (len(data) - show_chars) + data[-show_chars:]

