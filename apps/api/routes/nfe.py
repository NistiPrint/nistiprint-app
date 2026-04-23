import json
from flask import request, jsonify, Blueprint, Response, stream_with_context
from nistiprint_shared.services.installed_integration_service import installed_integration_service
from nistiprint_shared.services.bling.bling_client_updated import BlingClient

nfe_bp = Blueprint('nfe', __name__)

@nfe_bp.route('/generate_nfe', methods=['GET', 'POST'])
def generate_nfe():
    if request.method == 'POST':
        data = request.get_json()
        platform = data.get('platform')
        bling_orders = data.get('bling_orders', [])
        # Permite passar explicitamente qual instância usar
        instance_id = data.get('instance_id')
    else:  # GET request (for EventSource)
        platform = request.args.get('platform')
        instance_id = request.args.get('instance_id')
        try:
            bling_orders = json.loads(request.args.get('bling_orders', '[]'))
        except json.JSONDecodeError:
            bling_orders = []

    if not (platform or instance_id) or not bling_orders:
        return jsonify({'error': 'Missing platform/instance_id or bling_orders'}), 400

    try:
        # 1. Tentar encontrar a instância responsável pela emissão de NF
        bling_instance = None
        
        if instance_id:
            # Se ID foi passado diretamente, usar ele
            bling_instance = installed_integration_service.get_installed_by_id(instance_id)
        elif platform:
            # Se apenas plataforma foi passada, buscar via roteamento inteligente
            # Primeiro, precisamos encontrar a instalação desta plataforma
            marketplace_insts = installed_integration_service.get_installed_by_module(platform.lower())
            if marketplace_insts:
                # Usar a primeira (ou poderíamos filtrar por nome de instância se tivéssemos)
                bling_instance = installed_integration_service.get_routing_for_function(
                    marketplace_insts[0].id, 
                    'INVOICING'
                )
        
        # 2. Se não encontrou via novo sistema, retorna erro
        if not bling_instance:
            return jsonify({'error': f'Nenhuma instância de faturamento configurada para: {platform}'}), 400
        elif bling_instance:
            # Criar cliente a partir da instância encontrada
            account_data = bling_instance.to_dict()
            account_data['id'] = bling_instance.id
            # Garantir tokens no top-level
            if bling_instance.access_token:
                account_data['access_token'] = bling_instance.access_token
            if bling_instance.refresh_token:
                account_data['refresh_token'] = bling_instance.refresh_token
                
            bling_client = BlingClient(account_data)
        else:
            return jsonify({'error': 'Instância de faturamento não localizada'}), 404
            
    except Exception as e:
        error_msg = f"Falha ao obter cliente Bling: {str(e)}"
        print(error_msg)
        return jsonify({'error': error_msg}), 401

    def generate():
        for order in bling_orders:
            try:
                result = bling_client.generate_nfe(order)
                response = {
                    'status': 'processing',
                    'order': {
                        'id': order.get('id'),
                        'numero': order.get('numero'),
                        'nfe_id': result.get('nfe_id'),
                        'contato': order.get('contato', {}),
                        'numeroLoja': order.get('numeroLoja')
                    },
                    'success': True
                }

                if result.get('error'):
                    response['success'] = False
                    response['error'] = result.get(
                        'error_message', 'Erro desconhecido ao gerar NFe')
                    # Include full error details if available
                    if result.get('error_details'):
                        response['error_details'] = result.get('error_details')
                    print(
                        f"Erro ao gerar NFe para pedido {order.get('id')}: {response['error']}")

                yield f"data: {json.dumps(response)}\n\n"

            except Exception as e:
                error_response = {
                    'status': 'error',
                    'order': {
                        'id': order.get('id'),
                        'numero': order.get('numero'),
                        'contato': order.get('contato', {}),
                        'numeroLoja': order.get('numeroLoja')
                    },
                    'error': str(e),
                    'success': False
                }
                print(
                    f"Exceção ao processar pedido {order.get('id')}: {str(e)}")
                yield f"data: {json.dumps(error_response)}\n\n"

        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')





