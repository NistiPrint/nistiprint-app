import os
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from services.database.database import db
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app

from models.bling_pedidos import BlingPedidos
from models.bling_pedido_itens import BlingPedidoItens
from models.shopee_orders import ShopeeOrders
from models.v2_chat_events import V2ChatEvents
from models.order_personalizations import OrderPersonalizations
from models.ai_execution_log import AiExecutionLog
from utils import process_message_content

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# AI Model Initialization
model_version = "gemini-2.5-flash"
model = None
try:
    # Unified AI Model Initialization using API Key from environment variable
    logger.info("Attempting to initialize Google Generative AI model...")
    api_key = os.getenv('AISTUDIO_APIKEY')
    if api_key:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_version)
        logger.info("Google Generative AI model initialized successfully using API key.")
    else:
        logger.warning("AISTUDIO_APIKEY environment variable not found. AI model not initialized.")
except Exception as e:
    logger.error(f"Failed to initialize AI model: {e}")


def save_log_to_file(order_sn, content, log_type="processing"):
    """Save logs to local file (similar to standalone version)."""
    try:
        # Create temp directory if it doesn't exist
        os.makedirs('temp', exist_ok=True)

        timestamp = datetime.now().strftime('%Y-%m-%dT%H_%M_%S_%f')
        filename = f"temp/{log_type}_{order_sn}_{timestamp}.log"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"Saved {log_type} log to file: {filename}")
        return filename
    except Exception as e:
        logger.warning(f"Failed to save {log_type} log to file for {order_sn}: {e}")
        return False


def save_processing_log(order_sn, prompt_template, prompt_payload, ai_response):
    """Save detailed processing information to local files."""

    # Create comprehensive log content
    timestamp = datetime.now().isoformat()
    log_content = f"""
AI Processing Log - Order: {order_sn}
Timestamp: {timestamp}

ORDER DATA:
{prompt_payload}


AI RESPONSE:
{ai_response}

"""

    # Save to local file
    # Save to multiple destinations
    file_path = save_log_to_file(order_sn, log_content, "processing")
    if file_path:
        logger.debug(f"Processing log saved: {file_path}")

    return file_path

# Load prompt template from file
def load_prompt_template():
    try:
        with open('./templates/prompts/prompt_template.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        logger.error("prompt_template.txt not found")
        raise
    except Exception as e:
        logger.error(f"Error reading prompt_template.txt: {e}")
        raise

# Load prompt template
PROMPT_TEMPLATE = load_prompt_template()

def get_orders_with_chats(order_sn=None):
    """
    Retrieve orders with their related items and chat messages.

    Args:
        order_sn (str, optional): The Shopee order SN to retrieve. Defaults to None.

    Returns:
        list: List of orders with related items and chat messages
    """
    session = db.session

    try:
        # Base query
        query = """
        SELECT
            bp.id as order_id,
            bp.numero as bling_number,
            bp.numeroLoja as shopee_order_sn,
            bp.data as order_date,
            bp.bling_id as bling_id,
            (
                SELECT CONCAT('[' ,
                    GROUP_CONCAT(
                        CONCAT(
                            '{"id":', bpi.id,
                            ',"descricao":"', REPLACE(COALESCE(bpi.descricao, ''), '"', '\\"'), '"',
                            ',"quantidade":', COALESCE(bpi.quantidade, 0), '}'
                        )
                        SEPARATOR ','
                    ),
                ']')
                FROM bling_pedido_itens bpi
                WHERE bpi.pedido_id = bp.id
                AND bpi.personalizado = 1
            ) as items_json,
            so.buyer_info as buyer_info,
            so.message as message_to_seller
        FROM bling_pedidos bp
        LEFT JOIN shopee_orders so ON bp.numeroLoja = so.order_sn
        WHERE bp.deletado = 0
        AND so.buyer_info IS NOT NULL
        """

        params = {}
        if order_sn:
            query += " AND bp.numeroLoja = :order_sn"
            params['order_sn'] = order_sn

        query += " ORDER BY bp.data DESC"

        # Execute the query
        result = session.execute(text(query), params)
        orders = result.mappings().all()

        processed_orders = []

        for order in orders:
            order_dict = dict(order)

            # Parse JSON fields
            if order_dict['buyer_info']:
                try:
                    order_dict['buyer_info'] = json.loads(order_dict['buyer_info'])
                except (json.JSONDecodeError, TypeError):
                    order_dict['buyer_info'] = {}

            # Parse items JSON
            order_dict['items'] = []
            if order_dict.get('items_json'):
                try:
                    order_dict['items'] = json.loads(order_dict['items_json'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to parse items JSON: {e}")
                    order_dict['items'] = []
            del order_dict['items_json']  # Remove the temporary field

            # Get last 7 days chat messages if buyer info is available
            username = order_dict.get('buyer_info', {}).get('username')
            if username:
                now = datetime.now()
                seven_days_ago = now - timedelta(days=7)
                chat_query = """
                SELECT * FROM v2_chat_events
                WHERE (from_user_name = :username OR to_user_name = :username)
                AND type NOT IN ('notification', 'faq_unsupported')
                AND created_timestamp > :cutoff
                ORDER BY created_at ASC
                """
                chat_result = session.execute(
                    text(chat_query),
                    {'username': username, 'cutoff': seven_days_ago.strftime('%Y-%m-%d')}
                )
                processed_messages = []
                for row in chat_result.mappings():
                    row_dict = dict(row)

                    # Initialize message with basic fields
                    message = {
                        'id': str(row_dict.get('id')),
                        'from_user_name': row_dict.get('from_user_name') or '',
                        'to_user_name': row_dict.get('to_user_name') or '',
                        'content': row_dict.get('content', ''),
                        'created_at': row_dict.get('created_at').isoformat() if row_dict.get('created_at') else None,
                        'type': (row_dict.get('type') or 'text').lower(),
                        'is_sender': row_dict.get('from_user_name') == username
                    }

                    # Process message content
                    processed_msg = process_message_content(message.copy())
                    processed_messages.append(processed_msg)

                order_dict['chat_messages'] = processed_messages
            else:
                order_dict['chat_messages'] = []

            processed_orders.append(order_dict)

        return processed_orders

    except Exception as e:
        logger.error(f"Error fetching orders with chats: {str(e)}")
        raise
    finally:
        session.close()


def generate_prompt_payload(order):
    prompt_payload = ">>> ORDER DATA\n"
    prompt_payload += f"\n  Order ID: {order['order_id']}"
    prompt_payload += f"\n  Bling ID: {order['bling_id']}"
    prompt_payload += f"\n  Bling Number: {order['bling_number']}"
    prompt_payload += f"\n  Shopee Order SN: {order['shopee_order_sn']}"
    prompt_payload += f"\n  Order Date: {order['order_date']}"


    # Print items
    prompt_payload += "\n\n>>> ITEMS:\n"
    for item in (order.get('items') or []):
        prompt_payload += f"\n  Item ID: {item['id']}"
        prompt_payload += f"\n  {int(item['quantidade'])}x {item['descricao']}"

    prompt_payload += f"\n\n>>> MESSAGE TO SELLER:\n"
    prompt_payload += f"\n  {order['message_to_seller']}"

    # Print chat messages
    prompt_payload += "\n\n>>> CHAT MESSAGES:\n"
    for msg in (order.get('chat_messages') or []):
        if msg.get('type') == 'bundle_message':
            continue
        from_user_name = msg.get('from_user_name', '')
        buyer_username = order['buyer_info'].get('username', '')
        if from_user_name == buyer_username:
            from_ = "Comprador"
        else:
            from_ = "Vendedor"
        prompt_payload += f"\n[{msg.get('id')}][{msg.get('created_at')}] {from_}: {msg.get('display_content', '')}"
    return prompt_payload


def run_model(prompt_payload):
    """
    Runs the generative model using the pre-initialized model instance.
    """
    if not model:
        raise RuntimeError("AI model is not initialized. Check startup logs for errors.")

    prompt = f"{PROMPT_TEMPLATE}\n{prompt_payload}"

    try:
        response = model.generate_content(prompt)
    except Exception as e:
        logging.error(f"Falha ao processar prompt, error: {e}")
        raise

    return response

def delete_extraction_records(order_data, session=None):
    """
    Delete extraction records from the database.
    If a session is provided, it uses it within the existing transaction.
    Otherwise, it creates and manages its own session and transaction.
    """
    # If no session is provided, create and manage one
    if session is None:
        session = db.session
        try:
            session.query(OrderPersonalizations).filter_by(shopee_order_sn=order_data['shopee_order_sn']).delete()
            session.commit()
        except Exception as e:
            logger.error(f"Error deleting extraction records: {str(e)}")
            session.rollback()
            raise
        finally:
            session.close()
    else:
        # Use the provided session, assume transaction is managed by the caller
        try:
            session.query(OrderPersonalizations).filter_by(shopee_order_sn=order_data['shopee_order_sn']).delete()
        except Exception as e:
            logger.error(f"Error deleting extraction records: {str(e)}")
            # Re-raise to allow the caller to handle the transaction
            raise


def save_extraction_results(order_data, extraction_result):
    """
    Save the extraction results to the database.

    Args:
        order_data (dict): The original order data
        extraction_result (dict): The extraction result from the model
    """
    session = db.session
    try:
        # Parse the JSON response if it's a string
        if isinstance(extraction_result, str):
            try:
                extraction_result = json.loads(extraction_result)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse extraction result as JSON: {e}")
                return False

        # Validate required fields
        required_fields = ['order_id', 'shopee_order_sn', 'status', 'personalized_items']
        if not all(field in extraction_result for field in required_fields):
            logger.error(f"Missing required fields in extraction result: {extraction_result}")
            return False

        delete_extraction_records(order_data, session=session)

        # Insert each personalized item
        for item in extraction_result.get('personalized_items', []):
            personalization = OrderPersonalizations(
                order_id=str(extraction_result['order_id']),
                shopee_order_sn=extraction_result['shopee_order_sn'],
                bling_id=str(order_data.get('bling_id')),
                bling_number=str(order_data.get('bling_number')),
                status=extraction_result['status'],
                reasoning=extraction_result.get('reasoning'),
                item_id=str(item.get('item_id')),
                item_description=item.get('item_description', '')[:1000],  # Allow more text
                quantity_to_personalize=item.get('quantity_to_personalize', 1),
                customization_name=item.get('customization_name'),
                name_source_message_id=item.get('name_source_message_id'),
                customization_initial=item.get('customization_initial'),
                initial_source_message_id=item.get('initial_source_message_id'),
                extraction_metadata={
                    'extraction_timestamp': datetime.utcnow().isoformat(),
                    'source': 'gemini-2.5-flash',
                    'version': '1.0',
                    'processed_at': datetime.utcnow().isoformat()
                }
            )
            session.add(personalization)

        # Commit all changes
        session.commit()
        logger.info(f"Successfully saved extraction results for order {extraction_result['order_id']}")
        return True

    except Exception as e:
        logger.error(f"Error in save_extraction_results: {str(e)}", exc_info=True)
        session.rollback()
        return False
    finally:
        session.close()


def log_ai_execution(order_sn, input_data, chat_context, extracted_personalization, model_result, status, error_message=None, user_feedback_id=None):
    session = db.session
    try:
        log_entry = AiExecutionLog(
            order_sn=order_sn,
            input_data=json.dumps(input_data, ensure_ascii=False, default=str),
            chat_context=json.dumps(chat_context, ensure_ascii=False, default=str),
            extracted_personalization=json.dumps(extracted_personalization, ensure_ascii=False, default=str) if extracted_personalization else None,
            model_result=json.dumps(model_result, ensure_ascii=False, default=str) if model_result else None,
            status=status,
            error_message=error_message,
            user_feedback_id=user_feedback_id
        )
        session.add(log_entry)
        session.commit()
    except Exception as e:
        logger.error(f"Error logging AI execution: {str(e)}", exc_info=True)
        session.rollback()
    finally:
        session.close()


def get_logs_by_order_sn(order_sn):
    """
    Retrieve AI execution logs for a specific order SN.
    """
    try:
        logs = AiExecutionLog.query.filter_by(order_sn=order_sn).order_by(AiExecutionLog.executed_at.desc()).all()
        return [
            {
                'id': log.id,
                'order_sn': log.order_sn,
                'executed_at': log.executed_at.isoformat(),
                'input_data': log.input_data,
                'chat_context': log.chat_context,
                'extracted_personalization': log.extracted_personalization,
                'model_result': log.model_result,
                'status': log.status,
                'error_message': log.error_message,
            }
            for log in logs
        ]
    except Exception as e:
        logger.error(f"Error fetching logs for order_sn {order_sn}: {e}", exc_info=True)
        return []


def get_personalizations_by_orders(order_sns):
    """
    Fetch personalization records for a list of Shopee order SNs.
    Returns a dictionary mapping order_sn to a list of personalization records.
    """
    if not order_sns:
        return {}

    try:
        personalizations = OrderPersonalizations.query.filter(
            OrderPersonalizations.shopee_order_sn.in_(order_sns)
        ).all()

        result = {}
        for p in personalizations:
            sn = p.shopee_order_sn
            if sn not in result:
                result[sn] = []

            result[sn].append({
                'item_id': p.item_id,
                'item_description': p.item_description,
                'customization_name': p.customization_name,
                'customization_initial': p.customization_initial,
                'quantity_to_personalize': p.quantity_to_personalize,
                'status': p.status
            })
        return result
    except Exception as e:
        logger.error(f"Error fetching personalizations for orders: {e}", exc_info=True)
        return {}


def get_personalizations_by_bling_orders(bling_order_numbers):
    """
    Fetch personalization records for a list of Bling order numbers.
    Returns a dictionary mapping bling_number to a list of personalization records.
    """
    if not bling_order_numbers:
        return {}

    try:
        from sqlalchemy import cast, String, collate

        # Join with bling_pedido_itens to get the SKU (codigo)
        # We cast BlingPedidoItens.id to String to match OrderPersonalizations.item_id
        # Using collation() to ensure both sides use the same collation (utf8mb4_unicode_ci)
        results = db.session.query(OrderPersonalizations, BlingPedidoItens.codigo).\
            outerjoin(BlingPedidoItens, OrderPersonalizations.item_id == cast(BlingPedidoItens.id, String).collate('utf8mb4_unicode_ci')).\
            filter(OrderPersonalizations.bling_number.in_(bling_order_numbers)).all()

        result = {}
        for p, item_sku in results:
            bling_num = p.bling_number
            if bling_num not in result:
                result[bling_num] = []

            result[bling_num].append({
                'item_id': p.item_id,
                'item_sku': item_sku,
                'item_description': p.item_description,
                'customization_name': p.customization_name,
                'customization_initial': p.customization_initial,
                'quantity_to_personalize': p.quantity_to_personalize,
                'status': p.status
            })
        return result
    except Exception as e:
        logger.error(f"Error fetching personalizations for Bling orders: {e}", exc_info=True)
        return {}


def _process_single_order(app, order, processed_count, total_orders):
    with app.app_context():
        order_sn = order.get('shopee_order_sn') or order.get('numeroLoja')
        logger.info(f"Processing order {processed_count} of {total_orders} (Order SN: {order_sn})")

        chat_context = order.get('chat_messages', [])
        prompt_payload = generate_prompt_payload(order)

        ai_result = None
        ai_response_text = None
        error_message = None
        status = 'success'

        try:
            response = run_model(prompt_payload)
            if response and response.text:
                ai_response_text = response.text
                ai_result = ai_response_text.replace("```json", "").replace("```", "")
                ai_result = json.loads(ai_result)
                save_success = save_extraction_results(order, ai_result)
                if not save_success:
                    status = 'db_error'
                    error_message = 'Failed to save extraction results.'
            else:
                status = 'no_response'
                error_message = 'No response from AI model.'
        except Exception as e:
            status = 'error'
            error_message = str(e)
            logger.error(f"Error processing order {order_sn}: {error_message}", exc_info=True)
        finally:
            # Save detailed logs (similar to standalone version)
            if ai_response_text:
                saved_locations = save_processing_log(
                    order_sn,
                    PROMPT_TEMPLATE,
                    prompt_payload,
                    ai_response_text
                )
                logger.info(f"Processing logs saved for {order_sn}: {saved_locations}")

            # Save execution summary to database
            log_ai_execution(
                order_sn=order_sn,
                input_data=prompt_payload,
                chat_context=chat_context,
                extracted_personalization=ai_result.get('personalized_items') if ai_result else None,
                model_result=ai_result,
                status=status,
                error_message=error_message
            )
        return status


def process_orders(limit=None, order_sn=None):
    """Main function to process orders and extract personalizations."""
    try:
        logger.info("Starting order processing...")
        app = current_app._get_current_object()

        orders = get_orders_with_chats(order_sn=order_sn)
        if limit and not order_sn:
            orders = orders[:limit]

        total_orders = len(orders)
        logger.info(f"Found {total_orders} orders to process")

        if total_orders == 0:
            return True, "No orders to process."

        processed_count = 0
        # Using ThreadPoolExecutor to process orders in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Create a future for each order
            futures = {executor.submit(_process_single_order, app, order, i + 1, total_orders): order for i, order in enumerate(orders)}

            for future in as_completed(futures):
                order = futures[future]
                try:
                    # Get the result of the future
                    status = future.result()
                    if status == 'success':
                        processed_count += 1
                except Exception as exc:
                    order_sn_exc = order.get('shopee_order_sn') or order.get('numeroLoja')
                    logger.error(f'Order {order_sn_exc} generated an exception: {exc}')

        logger.info("Order processing completed.")
        return True, f"Successfully processed {processed_count} of {total_orders} orders."

    except Exception as e:
        logger.error(f"Error in process_orders: {str(e)}", exc_info=True)
        return False, str(e)