from flask import Blueprint, jsonify, request
from services.database.database import db
from models.bling_pedidos import BlingPedidos
from models.bling_pedido_itens import BlingPedidoItens
from models.order_personalizations import OrderPersonalizations
from models.shopee_orders import ShopeeOrders
from models.v2_chat_events import V2ChatEvents
from routes.auth import login_required
from sqlalchemy import text
from utils import process_message_content
from services.bling.bling_client import BlingClient
from services.uom_conversion_service import uom_conversion_service
from services.ai_personalization_service import get_logs_by_order_sn
import json

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/messages/<username>', methods=['GET'])
@login_required
def get_messages(username):
    # print(f"Fetching messages for user: {username}")
    try:
        # Get all messages for this conversation
        query = """
            SELECT * FROM v2_chat_events
            WHERE (from_user_name = :username OR to_user_name = :username)
            AND type NOT IN ('faq_unsupported', 'faq_question_list', 'faq_category_choice', 'faq_feedback_prompt')
            ORDER BY created_at ASC
        """
        result = db.session.execute(text(query), {'username': username})

        processed_messages = []
        bundle_messages = {}
        regular_messages = []
        for row in result:
            try:
                # Convert row to dict for easier access
                row_dict = dict(row._mapping) if hasattr(row, '_mapping') else dict(row)

                # Get message content from the content JSON field
                content = {}
                try:
                    if 'content' in row_dict and row_dict['content']:
                        if isinstance(row_dict['content'], str):
                            content = json.loads(row_dict['content'])
                        elif isinstance(row_dict['content'], dict):
                            content = row_dict['content']
                except json.JSONDecodeError as e:
                    print(f"Error parsing content JSON: {e}")

                # Initialize message with basic fields
                message = {
                    'id': str(row_dict.get('id')),  # Ensure ID is string
                    'from_user_name': row_dict.get('from_user_name') or '',
                    'to_user_name': row_dict.get('to_user_name') or '',
                    'content': row_dict.get('content', ''),
                    'created_at': row_dict.get('created_at').isoformat() if row_dict.get('created_at') else None,
                    'type': row_dict.get('type', 'text').lower(),  # Ensure type is lowercase
                    'is_sender': row_dict.get('from_user_name') == username
                }

                # Process message content
                try:
                    # Try to parse content as JSON if it's a string
                    if isinstance(message['content'], str) and message['content'].strip():
                        try:
                            message['content'] = json.loads(message['content'])
                        except json.JSONDecodeError:
                            pass  # Keep as string if not valid JSON

                    # Process message content if the function exists
                    message = process_message_content(message)

                    # Ensure display_content exists
                    if 'display_content' not in message:
                        message['display_content'] = str(message.get('content', ''))

                    # Add message text for backward compatibility
                    if 'message' not in message:
                        message['message'] = message.get('display_content', '')

                except Exception as e:
                    print(f"Error processing message {message.get('id')}: {str(e)}")
                    message['display_content'] = str(message.get('content', 'Error processing message'))

                # Check if this is a bundle message
                if message.get('type') == 'bundle_message' and 'content' in message:
                    try:
                        # Get the content, handling both string and dict cases
                        content = message['content']
                        if isinstance(content, str):
                            content = json.loads(content)

                        if isinstance(content, dict) and 'messages' in content and isinstance(content['messages'], list):
                            # Store the message IDs for later processing
                            bundle_messages[str(message['id'])] = {
                                'bundle_info': message,
                                'message_ids': [str(msg_id) for msg_id in content['messages']]
                            }
                            continue  # Skip to next message as this is a bundle header
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        print(f"Error processing bundle message {message.get('id')}: {e}")
                        continue

                # Skip faq_unsupported messages
                if message.get('type') == 'faq_unsupported':
                    continue

                regular_messages.append(message)

            except Exception as e:
                print(f"Error processing message: {str(e)}")
                print(f"Row data: {row_dict}")
                continue

        # Now process regular messages and check if they belong to any bundle
        for message in regular_messages:
            message_id = str(message.get('id'))
            added_to_bundle = False

            # Skip faq_unsupported messages
            if message.get('type') == 'faq_unsupported':
                continue

            # Check if this message is part of any bundle
            for bundle_id, bundle_data in bundle_messages.items():
                if message_id in bundle_data['message_ids']:
                    if 'messages' not in bundle_data:
                        bundle_data['messages'] = []
                    bundle_data['messages'].append(message)
                    added_to_bundle = True
                    break

            # If not part of any bundle, add as a regular message
            if not added_to_bundle:
                processed_messages.append(message)

        # Add all bundles to the messages list with their messages
        for bundle_id, bundle_data in bundle_messages.items():
            if 'messages' in bundle_data and bundle_data['messages']:
                # Filter out faq_unsupported messages from bundle
                bundle_data['messages'] = [msg for msg in bundle_data['messages']
                                        if msg.get('type') != 'faq_unsupported']

                if bundle_data['messages']:  # Only add bundle if it has messages after filtering
                    # Sort messages within the bundle by created_at
                    bundle_data['messages'].sort(key=lambda x: x.get('created_at', ''))
                    bundle_data['bundle_info']['bundle_messages'] = bundle_data['messages']

                    # Set the bundle's timestamp to the oldest message in the bundle
                    if bundle_data['messages']:
                        bundle_data['bundle_info']['oldest_message_time'] = min(
                            msg.get('created_at', '') for msg in bundle_data['messages']
                        )
                    processed_messages.append(bundle_data['bundle_info'])

        # Sort all messages by the oldest message time for bundles, or created_at for regular messages
        def get_sort_key(msg):
            if 'bundle_messages' in msg and 'oldest_message_time' in msg:
                return msg['oldest_message_time']
            return msg.get('created_at', '')

        processed_messages.sort(key=get_sort_key)

        return jsonify(processed_messages)  # Return just the array of messages as expected by the frontend

    except Exception as e:
        print(f"Error in get_messages: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route('/convert_order_ids', methods=['POST'])
@login_required
def convert_order_ids():
    print("🎯 API convert_order_ids chamada!")
    try:
        data = request.get_json()

        platform = data.get('platform')
        order_ids = data.get('order_ids', [])

        if not platform or not order_ids:
            return jsonify({
                'success': False,
                'error': 'Plataforma e IDs de pedidos são obrigatórios'
            }), 400

        # Converte os IDs usando o BlingClient
        result = BlingClient.convert_order_ids(platform, order_ids)
        print("✅ Conversão concluída!")

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route('/products/<product_id>/uom-conversions', methods=['GET'])
@login_required
def get_uom_conversions(product_id):
    """Returns all UoM conversions for a given product."""
    try:
        conversions = uom_conversion_service.get_conversions_for_product(product_id)
        return jsonify(conversions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/ai_logs/<order_sn>', methods=['GET'])
@login_required
def get_ai_logs(order_sn):
    """Returns all AI execution logs for a given order SN."""
    try:
        logs = get_logs_by_order_sn(order_sn)
        return jsonify(logs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500