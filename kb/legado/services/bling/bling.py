from time import sleep
import os
import requests

import gcp_flask.constants as constants
from gcp_flask.utils import process_string


def bling_get_token(platform):
    """
    Obtém token da Bling chamando endpoint externo do token manager.
    """
    versao = constants.PLATFORM_X_BLING_VERSION.get(str(platform).lower())

    if versao is None:
        print(f"Versão não encontrada para plataforma: {platform}")
        return None

    # Obter CNPJ da plataforma
    cnpj = constants.PLATFORM_X_CNPJ.get(str(platform).lower())

    if not cnpj:
        print(f"CNPJ não encontrado para plataforma: {platform}")
        return None

    # Obter chave API do ambiente
    api_key = os.environ.get('BLING_API_KEY')
    if not api_key:
        print("BLING_API_KEY não definida no ambiente")
        return None

    try:
        # Fazer chamada para o endpoint do token manager
        url = f"https://bling-token-manager-992903106218.us-east1.run.app/token/{cnpj}"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json'
        }

        print(f"🌐 Fazendo chamada GET para: {url}")
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            response_data = response.json()
            token = response_data.get('access_token')
            if token:
                print(f"Token obtido com sucesso para CNPJ {cnpj}")
                return token
            else:
                print(f"Resposta sem access_token para CNPJ {cnpj}: {response_data}")
                return None
        else:
            print(f"Erro ao obter token para CNPJ {cnpj}: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao obter token para CNPJ {cnpj}: {e}")
        return None
    except Exception as e:
        print(f"Erro inesperado ao obter token: {e}")
        return None


def bling_get_product(platform, id):
    bling_token = bling_get_token(platform)
    if bling_token:
        url = "https://api.bling.com.br/Api/v3/produtos/" + str(id)
        payload = {}
        headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + bling_token
        }

        response = requests.request("GET", url, headers=headers, data=payload)
        return response.json()
    return None

def bling_get_order_detail(bling_token, order_id):
    sleep(0.3)

    # API endpoint
    url = f"https://api.bling.com.br/Api/v3/pedidos/vendas/{str(order_id)}"
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Bearer ' + bling_token  # Authorization header
    }
    res = requests.request("GET", url, headers=headers)
    if res.status_code == 200:
        res = res.json()
        return res['data']
    return False

def bling_update_order_status(bling_token, order_id, status_id, platform=None):
    sleep(0.3)

    # Update order status to 451955 (Em Produção)
    if bling_token is None and platform:
        bling_token = bling_get_token(platform)
    if bling_token:
        url = f'https://api.bling.com.br/Api/v3/pedidos/vendas{order_id}/situacoes/{status_id}'
        headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + bling_token  # Authorization header
        }
        res = requests.request("PATCH", url, headers=headers)
        if res.status_code == 204:
            return True

        print(f'Erro update {order_id}: {res.text}')
    return False

def bling_generate_order_nfe(bling_token, order):
    print(f'Gerando NFe para o pedido {order["id"]}')
    sleep(0.3)

    if not bling_token:
        print("Erro: Token Bling não fornecido")
        order['error'] = True
        order['error_message'] = "Token de autenticação Bling não encontrado"
        return order

    try:
        url = f'https://api.bling.com.br/Api/v3/pedidos/vendas/{order["id"]}/gerar-nfe'
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {bling_token}'
        }
        res = requests.request("POST", url, headers=headers, timeout=30)
        print(f"Resposta da API Bling - Status: {res.status_code}")

        if res.status_code == 201:
            response_data = res.json()
            print(f"Resposta da API (201): {response_data}")
            order['error'] = False
            order['error_message'] = None
            order['nfe_id'] = response_data.get('data', {}).get('idNotaFiscal')
        else:
            error_data = res.json()
            print(f"Erro na API Bling: {error_data}")
            order['error'] = True
            # Try to extract the error message from the response
            if 'error' in error_data and 'fields' in error_data['error'] and len(error_data['error']['fields']) > 0:
                order['error_message'] = error_data['error']['fields'][0].get('msg', 'Erro desconhecido ao gerar NFe')
            else:
                order['error_message'] = error_data.get('error', {}).get('message', 'Erro desconhecido ao gerar NFe')

        return order

    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição para a API Bling: {str(e)}")
        order['error'] = True
        order['error_message'] = f"Erro de conexão com a API Bling: {str(e)}"
        return order
    except Exception as e:
        print(f"Erro inesperado ao gerar NFe: {str(e)}")
        order['error'] = True
        order['error_message'] = f"Erro inesperado: {str(e)}"
        return order

def bling_process_orders(ids_pedidos_chunks, platform):
    order_ids_count = 0
    orders_found_in_bling = 0
    bling_orders_obtained_count = 0
    bling_orders_not_found = []
    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = []

    bling_token = bling_get_token(platform)  # Retrieve the Bling API token
    url = "https://api.bling.com.br/Api/v3/pedidos/vendas"  # API endpoint
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Bearer ' + bling_token  # Authorization header
    }
    if bling_token:
        # Initialize an empty list to collect all responses

        for chunk in ids_pedidos_chunks:

            # Split the string by ';'
            split_chunk = chunk.split(';')
            order_ids_count = order_ids_count + len(split_chunk)

            # Construct the URL parameters
            payload = '&'.join(
                [f"numerosLojas[]={piece}" for piece in split_chunk])

            # Append the payload to the URL
            full_url = f"{url}?{payload}"

            response = requests.request("GET", full_url, headers=headers)
            response = response.json()

            orders_found_in_bling = orders_found_in_bling + \
                len(response['data'])

            # create a list of which numerosLojas/pieces are missing in API response
            bling_orders_not_found = [piece for piece in split_chunk if piece not in [item['numeroLoja'] for item in response['data']]]

            # extract all orders' ids and concatenate into a single list
            bling_orders_id.extend([item['id'] for item in response['data']])

            sleep(0.3)

        for id in bling_orders_id:

            # Get order details
            order = bling_get_order_detail(bling_token, id)
            if order is not None:
                bling_orders_data.append(order)
                bling_orders_obtained_count += 1


        bling_orders_id_numero = [{'id': item['id'], 'numero': item['numero']} for item in bling_orders_data]

        # for each order in bling_orders_data, and for each product in itens, run 'descricao' to process_string
        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade']
                                       for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        """ Ordena por:
            1. itens personalizados: não depois sim (agrupa pedidos com item personalizado)
            2. quais itens personalizados: ordem alfabética (agrupa os personalizados por modelo)
            3. quantidade total de itens: ordem crescente
            4. quantos itens diferentes: ordem crescente
        """
        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
            [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

        return bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found
    return None

def bling_get_orders_by_status(platform, id_situacao, id_loja, data_inicial, data_final):
    bling_token = bling_get_token(platform)
    if not bling_token:
        return []

    all_orders = []
    page = 1
    max_pages = 50  # Safety break

    while page <= max_pages:
        sleep(0.3)  # Throttle request

        params = {
            'pagina': page,
            'idsSituacoes[]': id_situacao,
            'idLoja': id_loja,
            'dataInicial': data_inicial,
            'dataFinal': data_final,
            'limite': 100
        }

        url = "https://api.bling.com.br/Api/v3/pedidos/vendas"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {bling_token}'
        }

        try:
            response = requests.get(url, headers=headers, params=params)

            response.raise_for_status()  # Raise an exception for bad status codes

            result = response.json()

            if 'data' in result and isinstance(result['data'], list):
                orders_on_page = result['data']
                all_orders.extend(orders_on_page)

                if len(orders_on_page) < 100:
                    break  # Last page
            else:
                break # No more data

        except requests.exceptions.RequestException as e:
            print(f"Error fetching Bling orders (page {page}): {e}")
            break

        page += 1

    return all_orders
