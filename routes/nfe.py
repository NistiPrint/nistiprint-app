import json
from flask import request, jsonify, Blueprint, Response, stream_with_context
from nistiprint_shared.services.bling.bling_client import BlingClient
from constants import PLATFORM_X_BLING_VERSION, PLATFORM_X_CNPJ

nfe_bp = Blueprint('nfe', __name__)

@nfe_bp.route('/generate_nfe', methods=['GET', 'POST'])
def generate_nfe():
    if request.method == 'POST':
        data = request.get_json()
        platform = data.get('platform')
        bling_orders = data.get('bling_orders', [])
    else:  # GET request (for EventSource)
        platform = request.args.get('platform')
        try:
            bling_orders = json.loads(request.args.get('bling_orders', '[]'))
        except json.JSONDecodeError:
            bling_orders = []

    if not platform or not bling_orders:
        return jsonify({'error': 'Missing platform or bling_orders'}), 400

    try:
        # Obter CNPJ da plataforma
        cnpj = PLATFORM_X_CNPJ.get(platform.lower())
        if not cnpj:
            return jsonify({'error': f'Plataforma não encontrada: {platform}'}), 400

        # Criar cliente Bling usando CNPJ
        bling_client = BlingClient.create_client(cnpj=cnpj)
    except ValueError as e:
        error_msg = f"Falha ao obter cliente Bling para a plataforma: {platform} - {str(e)}"
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





