from flask import Blueprint, jsonify, request
from nistiprint_shared.database.database import db
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.models.order_personalizations import OrderPersonalizations
from nistiprint_shared.models.shopee_orders import ShopeeOrders
from nistiprint_shared.models.v2_chat_events import V2ChatEvents
from routes.auth import login_required
from sqlalchemy import text
from utils import process_message_content
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.uom_conversion_service import uom_conversion_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.ai_personalization_service import get_logs_by_order_sn
from utils.api_response import ApiResponse
import json

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/messages/<username>', methods=['GET'])
@login_required
def get_messages(username):
    # print(f"Fetching messages for user: {username}")
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        # Prioritize mode from request param
        mode = request.args.get('mode') or app_config_service.get_operational_mode()
        
        rows = []
        if mode == 'legacy':
            from nistiprint_shared.services.legacy_sync_service import LegacySyncService
            conn = LegacySyncService._get_legacy_connection()
            with conn:
                # Use the new MySQL View for chat messages
                query = text("""
                    SELECT * FROM view_mensagens_chat 
                    WHERE from_user_name = :username OR to_user_name = :username
                    ORDER BY created_at ASC
                """)
                result = conn.execute(query, {"username": username}).mappings().all()
                rows = [dict(row) for row in result]
                
                # Fetch bundle information separately to maintain grouping logic
                if rows:
                    msg_ids = [str(r['id']) for r in rows]
                    try:
                        query_bundles = text("""
                            SELECT * FROM v2_bundle_messages 
                            WHERE msg_id IN :ids OR event_id IN :ids
                        """)
                        bundle_result = conn.execute(query_bundles, {"ids": tuple(msg_ids)}).mappings().all()
                        
                        # MySQL schema: event_id is the 'bundle container', msg_id is the individual message
                        msg_to_bundle = {str(b['msg_id']): str(b['event_id']) for b in bundle_result}
                        
                        for row in rows:
                            row_id = str(row['id'])
                            if row_id in msg_to_bundle:
                                row['parent_bundle_id'] = msg_to_bundle[row_id]
                            
                            is_bundle_container = any(str(b['event_id']) == row_id for b in bundle_result)
                            if is_bundle_container:
                                row['type'] = 'bundle_message'
                                associated_msgs = [str(b['msg_id']) for b in bundle_result if str(b['event_id']) == row_id]
                                row['content'] = json.dumps({'messages': associated_msgs})
                    except Exception as bundle_err:
                        print(f"Warning: Could not fetch chat bundles: {bundle_err}")
        else:
            # Get all messages for this conversation using the View
            from nistiprint_shared.database.supabase_db_service import supabase_db
            
            # Query the view which already handles basic filtering and content processing
            result = supabase_db.client.table('view_mensagens_chat').select("*") \
                .or_(f"from_user_name.eq.{username},to_user_name.eq.{username}") \
                .order("created_at", desc=False).execute()
            rows = result.data

        processed_messages = []
        bundle_messages = {}
        regular_messages = []
        for row_dict in rows:
            try:
                # Initialize message
                created_at_raw = row_dict.get('created_at')
                
                # In MySQL it might be datetime, in Supabase it's ISO string
                if hasattr(created_at_raw, 'isoformat'):
                    created_at_raw = created_at_raw.isoformat()

                # Process content if it's from MySQL (Supabase view already processes it)
                display_content = row_dict.get('display_content')
                if not display_content:
                    # Logic from utils.process_message_content
                    content_raw = row_dict.get('content', '')
                    if isinstance(content_raw, str):
                        try:
                            c_json = json.loads(content_raw)
                            display_content = c_json.get('text') or c_json.get('url') or str(c_json)
                        except:
                            display_content = content_raw
                    else:
                        display_content = str(content_raw)

                message = {
                    'id': str(row_dict.get('id')),
                    'from_user_name': row_dict.get('from_user_name') or '',
                    'to_user_name': row_dict.get('to_user_name') or '',
                    'content': row_dict.get('content', ''),
                    'created_at': created_at_raw,
                    'type': row_dict.get('type', 'text').lower(),
                    'is_sender': row_dict.get('from_user_name') == username,
                    'display_content': display_content or 'Mensagem sem conteúdo'
                }

                # Ensure 'message' key for backward compatibility
                message['message'] = message['display_content']

                # Check if this is a bundle message
                if message.get('type') == 'bundle_message':
                    content = message['content']
                    if isinstance(content, str):
                        try: content = json.loads(content)
                        except: pass

                    if isinstance(content, dict) and 'messages' in content and isinstance(content['messages'], list):
                        bundle_messages[str(message['id'])] = {
                            'bundle_info': message,
                            'message_ids': [str(msg_id) for msg_id in content['messages']]
                        }
                        continue

                regular_messages.append(message)

            except Exception as e:
                print(f"Error processing message: {str(e)}")
                continue

        # Process bundles (legacy logic)
        for message in regular_messages:
            message_id = str(message.get('id'))
            added_to_bundle = False

            for bundle_id, bundle_data in bundle_messages.items():
                if message_id in bundle_data['message_ids']:
                    bundle_data.setdefault('messages', []).append(message)
                    added_to_bundle = True
                    break

            if not added_to_bundle:
                processed_messages.append(message)

        for bundle_id, bundle_data in bundle_messages.items():
            if bundle_data.get('messages'):
                bundle_data['messages'].sort(key=lambda x: x.get('created_at', ''))
                bundle_data['bundle_info']['bundle_messages'] = bundle_data['messages']
                bundle_data['bundle_info']['oldest_message_time'] = min(
                    msg.get('created_at', '') for msg in bundle_data['messages']
                )
                processed_messages.append(bundle_data['bundle_info'])

        processed_messages.sort(key=lambda x: x.get('oldest_message_time') if 'oldest_message_time' in x else x.get('created_at', ''))

        return ApiResponse.success(data=processed_messages)

    except Exception as e:
        print(f"Error in get_messages: {str(e)}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@api_bp.route('/convert_order_ids', methods=['POST'])
@login_required
def convert_order_ids():
    print("🎯 API convert_order_ids chamada!")
    try:
        data = request.get_json()

        platform = data.get('platform')
        order_ids = data.get('order_ids', [])

        if not platform or not order_ids:
            return ApiResponse.error(message='Plataforma e IDs de pedidos são obrigatórios', status_code=400)

        # Converte os IDs usando o BlingClient
        result = BlingClient.convert_order_ids(platform, order_ids)
        print("✅ Conversão concluída!")

        return ApiResponse.success(data=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@api_bp.route('/products/<product_id>/uom-conversions', methods=['GET'])
@login_required
def get_uom_conversions(product_id):
    """Returns all UoM conversions for a given product."""
    try:
        conversions = uom_conversion_service.get_conversions_for_product(str(product_id))
        return ApiResponse.success(data=conversions)
    except Exception as e:
        return ApiResponse.error(message=str(e), status_code=500)

@api_bp.route('/products/search_internal', methods=['GET'])
@login_required
def search_internal_products():
    """Search for internal products based on query, platform, SKU, name, and account ID."""
    query = request.args.get('query', '')
    platform = request.args.get('platform')
    external_sku = request.args.get('external_sku')
    external_name = request.args.get('external_name')
    external_account_id = request.args.get('external_account_id')

    try:
        # Use the find_internal_product method for comprehensive search
        # For a generic search, we might just use the query against name/sku
        # For this endpoint, let's assume 'query' is the primary search term
        # and other external details are for more specific matching if needed.
        
        # If a specific external_sku or external_name is provided, prioritize that
        if external_sku or external_name:
            matches = product_service.find_internal_product(
                platform=platform,
                external_sku=external_sku,
                external_name=external_name,
                external_account_id=external_account_id
            )
        else:
            # Fallback to a general search if no specific external details are given
            # This will search internal product name and sku
            matches = product_service.search_produtos(query=query, limit=50)
            
        # Ensure 'id' is present in each product dict
        for match in matches:
            if 'id' not in match:
                match['id'] = match.get('id') # Should already be there from Firestore doc.id

        return jsonify([{'id': p['id'], 'name': p.get('name'), 'sku': p.get('sku')} for p in matches])
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/products/link_external', methods=['POST'])
@login_required
def link_external_product():
    """Links an external product to an internal product."""
    data = request.get_json()
    product_id = data.get('internal_product_id')
    platform = data.get('platform')
    external_id = data.get('external_id')
    external_sku = data.get('external_sku')
    external_name = data.get('external_name')
    external_account_id = data.get('external_account_id')

    if not all([product_id, platform]):
        return jsonify({'error': 'internal_product_id and platform are required.'}), 400

    try:
        product_service.add_external_product_link(
            product_id=product_id,
            external_id=external_id,
            external_sku=external_sku,
            external_name=external_name
        )
        return jsonify({'success': True, 'message': 'Link externo adicionado com sucesso.'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/products/unlink_external', methods=['POST'])
@login_required
def unlink_external_product():
    """Unlinks an external product from an internal product."""
    data = request.get_json()
    product_id = data.get('internal_product_id')
    platform = data.get('platform')
    external_id = data.get('external_id')
    external_sku = data.get('external_sku')
    external_name = data.get('external_name')
    external_account_id = data.get('external_account_id')

    if not all([product_id, platform]):
        return jsonify({'error': 'internal_product_id and platform are required.'}), 400

    try:
        product_service.remove_external_product_link(
            product_id=product_id,
            external_id=external_id,
            external_sku=external_sku,
            external_name=external_name
        )
        return jsonify({'success': True, 'message': 'Link externo removido com sucesso.'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/products/create_and_link', methods=['POST'])
@login_required
def create_and_link_product():
    """Creates a new internal product and links an external product to it."""
    data = request.get_json()
    new_product_data = data.get('new_product_data')
    external_link_data = data.get('external_link_data')

    if not new_product_data or not external_link_data:
        return jsonify({'error': 'new_product_data and external_link_data are required.'}), 400

    try:
        # Create the new product
        new_product = product_service.create(new_product_data)
        new_product_id = new_product['id']

        # Link the external product to the newly created internal product
        product_service.add_external_product_link(
            product_id=new_product_id,
            external_id=external_link_data.get('external_id'),
            external_sku=external_link_data.get('external_sku'),
            external_name=external_link_data.get('external_name')
        )
        return jsonify({'success': True, 'message': 'Produto criado e linkado com sucesso.', 'product_id': new_product_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
@api_bp.route('/ai_logs/<order_sn>', methods=['GET'])
@login_required
def get_ai_logs(order_sn):
    """Returns all AI execution logs for a given order SN."""
    try:
        logs = get_logs_by_order_sn(order_sn)
        return ApiResponse.success(data=logs)
    except Exception as e:
        return ApiResponse.error(message=str(e), status_code=500)

@api_bp.route('/submit_feedback', methods=['POST'])
@login_required
def api_submit_feedback():
    """Submits user feedback for an order's personalization."""
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        feedback_val = data.get('feedback')
        notes = data.get('feedback_notes', '')

        if order_id is None or feedback_val is None:
            return ApiResponse.error(message='Dados incompletos', status_code=400)

        from datetime import datetime
        from nistiprint_shared.database.supabase_db_service import supabase_db

        # Usar Supabase como fonte primária
        supabase_db.table('feedback_pedido').insert({
            'codigo_pedido': str(order_id),
            'avaliacao': int(feedback_val),
            'texto_feedback': notes,
            'updated_at': datetime.utcnow().isoformat()
        }).execute()

        return ApiResponse.success(message='Feedback enviado com sucesso')

    except Exception as e:
        print(f"Error submitting feedback: {e}")
        return ApiResponse.error(message=str(e), status_code=500)





