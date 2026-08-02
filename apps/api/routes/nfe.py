import json
from flask import request, jsonify, Blueprint, Response, stream_with_context
from nistiprint_shared.services.installed_integration_service import installed_integration_service
from nistiprint_shared.services.integration_capability_service import INVOICING, integration_capability_service
from nistiprint_shared.services.bling.bling_client_updated import BlingClient
from nistiprint_shared.database.supabase_db_service import supabase_db

nfe_bp = Blueprint('nfe', __name__)

@nfe_bp.route('/generate_nfe', methods=['GET', 'POST'])
def generate_nfe():
    if request.method == 'POST':
        data = request.get_json()
        platform = data.get('platform')
        bling_orders = data.get('bling_orders', [])
        # Permite passar explicitamente qual instância usar
        instance_id = data.get('instance_id')
        request_context = {
            'bling_integration_id': data.get('bling_integration_id') or data.get('erp_integration_id'),
            'erp_store_id': data.get('erp_store_id') or data.get('shop_id') or data.get('bling_loja_id'),
            'external_order_id': data.get('external_order_id') or data.get('numeroLoja'),
        }
    else:  # GET request (for EventSource)
        platform = request.args.get('platform')
        instance_id = request.args.get('instance_id')
        request_context = {
            'bling_integration_id': request.args.get('bling_integration_id') or request.args.get('erp_integration_id'),
            'erp_store_id': request.args.get('erp_store_id') or request.args.get('shop_id') or request.args.get('bling_loja_id'),
            'external_order_id': request.args.get('external_order_id') or request.args.get('numeroLoja'),
        }
        try:
            bling_orders = json.loads(request.args.get('bling_orders', '[]'))
        except json.JSONDecodeError:
            bling_orders = []

    if not bling_orders:
        return jsonify({'error': 'Missing platform/instance_id or bling_orders'}), 400

    try:
        def _extract_numero_loja(order_obj):
            if not isinstance(order_obj, dict):
                return None
            return str(order_obj.get('numeroLoja') or '').strip() or None

        numero_loja_list = [
            numero_loja
            for numero_loja in (_extract_numero_loja(order) for order in bling_orders)
            if numero_loja
        ]
        request_context = {k: v for k, v in request_context.items() if v not in (None, '')}

        # Se não vier instance_id explícito, tenta resolver pela origem dos pedidos já persistidos.
        if not instance_id and numero_loja_list:
            pedidos_res = (
                supabase_db.table('pedidos')
                .select('codigo_pedido_externo, erp_integration_id, marketplace_integration_id, erp_store_id')
                .in_('codigo_pedido_externo', numero_loja_list)
                .execute()
            )
            rows = pedidos_res.data or []
            integration_ids = sorted(
                {
                    int(row['erp_integration_id'])
                    for row in rows
                    if row.get('erp_integration_id') is not None
                }
            )
            if len(integration_ids) == 1:
                instance_id = str(integration_ids[0])
            elif len(integration_ids) > 1:
                return jsonify({
                    'error': 'Pedidos pertencem a múltiplas contas Bling. Gere NF por conta separadamente.'
                }), 400
            else:
                marketplace_ids = sorted(
                    {
                        int(row['marketplace_integration_id'])
                        for row in rows
                        if row.get('marketplace_integration_id') is not None
                    }
                )
                if len(marketplace_ids) == 1:
                    resolved_ids = set()
                    ambiguous = False
                    for row in rows:
                        if row.get('marketplace_integration_id') is None:
                            continue
                        resolved = integration_capability_service.resolve(
                            row['marketplace_integration_id'],
                            INVOICING,
                            context={
                                'erp_store_id': row.get('erp_store_id'),
                                'external_order_id': row.get('codigo_pedido_externo'),
                                **request_context,
                            },
                        )
                        if resolved.reason == 'ambiguous_erp_link':
                            ambiguous = True
                            break
                        if resolved.responsible_integration:
                            resolved_ids.add(int(resolved.integration_id))
                    if ambiguous:
                        return jsonify({
                            'error': 'Pedido possui mais de uma conta Bling possivel. Informe shop.id/conta Bling para gerar NF.'
                        }), 400
                    if len(resolved_ids) == 1:
                        instance_id = str(next(iter(resolved_ids)))
                    elif len(resolved_ids) > 1:
                        return jsonify({
                            'error': 'Pedidos resolvem para multiplas contas Bling. Gere NF por conta separadamente.'
                        }), 400
                elif len(marketplace_ids) > 1:
                    return jsonify({
                        'error': 'Pedidos pertencem a multiplas contas de marketplace. Gere NF por conta separadamente.'
                    }), 400

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
                resolved = integration_capability_service.resolve(
                    marketplace_insts[0].id,
                    INVOICING,
                    context=request_context,
                )
                if resolved.reason == 'ambiguous_erp_link':
                    return jsonify({
                        'error': 'Mais de uma conta Bling atende esta origem. Informe shop.id/conta Bling para gerar NF.'
                    }), 400
                bling_instance = resolved.responsible_integration
        
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





