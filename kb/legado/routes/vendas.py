from flask import Blueprint, render_template, jsonify
from services.database.database import db
from models.v2_chat_events import V2ChatEvents
from routes.auth import login_required
from sqlalchemy import text
import json

vendas_bp = Blueprint('vendas', __name__, url_prefix='/vendas')

@vendas_bp.route('/personalizadas')
@login_required
def personalizadas():
    try:
        # Query to get orders with their items from the new tables
        query = """
            SELECT
                p.id,
                p.numero,
                p.numeroLoja,
                p.data,
                p.contato,
                p.personalizado,
                p.criado_em,
                p.atualizado_em,
                GROUP_CONCAT(
                    JSON_OBJECT(
                        'id', i.id,
                        'codigo', i.codigo,
                        'unidade', i.unidade,
                        'quantidade', i.quantidade,
                        'valor', i.valor,
                        'descricao', i.descricao,
                        'personalizado', i.personalizado,
                        'produto', i.produto,
                        'personalizations', (
                            SELECT JSON_ARRAYAGG(
                                JSON_OBJECT(
                                    'item_id', op.item_id,
                                    'item_description', op.item_description,
                                    'quantity_to_personalize', op.quantity_to_personalize,
                                    'customization_name', op.customization_name,
                                    'name_source_message_id', op.name_source_message_id,
                                    'customization_initial', op.customization_initial,
                                    'initial_source_message_id', op.initial_source_message_id,
                                    'status', op.status,
                                    'reasoning', op.reasoning
                                )
                            )
                            FROM order_personalizations op
                            WHERE op.order_id = p.id AND op.item_id = i.id
                        )
                    )
                    ORDER BY i.id
                    SEPARATOR '|||'
                ) as itens_json,
                s.order_sn,
                s.buyer_info,
                s.message,
                s.created_at as shopee_created_at
            FROM bling_pedidos p
            LEFT JOIN bling_pedido_itens i ON p.id = i.pedido_id
            LEFT JOIN shopee_orders s ON p.numeroLoja = s.order_sn
            WHERE p.deletado = 0
            GROUP BY p.id, p.numero, p.numeroLoja, p.data, p.contato, p.personalizado,
                     p.criado_em, p.atualizado_em, s.order_sn, s.buyer_info, s.message, s.created_at
            ORDER BY p.data DESC
        """

        result = db.session.execute(text(query))

        # Process the orders to include related data
        processed_orders = []
        for row in result:
            try:
                # Parse the contato field as JSON if it's a string
                contato = {}
                if row.contato and isinstance(row.contato, str):
                    contato = json.loads(row.contato)

                # Parse buyer_info from shopee_orders if it exists
                buyer_info = {}
                if row.buyer_info and isinstance(row.buyer_info, str):
                    try:
                        buyer_info = json.loads(row.buyer_info)
                    except json.JSONDecodeError:
                        buyer_info = {}

                # Process items
                itens = []
                if row.itens_json:
                    for item_str in row.itens_json.split('|||'):
                        try:
                            item = json.loads(item_str)
                            # Parse the produto field if it's a string
                            if 'produto' in item and isinstance(item['produto'], str):
                                item['produto'] = json.loads(item['produto'])
                            itens.append(item)
                        except json.JSONDecodeError as e:
                            print(f"Error parsing item JSON: {e}")
                            continue

                # Personalizations are now included in each item

                # Get related Shopee order data if it exists
                shopee_data = {}
                if row.order_sn:
                    shopee_data = {
                        'username': buyer_info.get('username', '') if buyer_info else '',
                        'order_sn': row.order_sn,
                        'message': row.message
                    }

                has_chat_messages = False
                if shopee_data and shopee_data['username']:
                    # query v2_chat_events for the username, if there's rows, set has_chat_messages to True
                    has_chat_messages = db.session.query(V2ChatEvents).filter(V2ChatEvents.from_user_name == shopee_data['username']).count() > 0

                order_data = {
                    'id': row.id,
                    'numero': row.numero,
                    'numeroLoja': row.numeroLoja,
                    'data': row.data,
                    'contato': contato,
                    'itens': itens,
                    'shopee': shopee_data,
                    'personalizado': bool(row.personalizado),
                    'has_chat_messages': has_chat_messages
                }

                processed_orders.append(order_data)

            except Exception as e:
                print(f"Error processing order {row.numero if hasattr(row, 'numero') else 'unknown'}: {e}")
                import traceback
                traceback.print_exc()
                continue

    
        return render_template('vendas/personalizadas.html', bling_orders=processed_orders)

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
