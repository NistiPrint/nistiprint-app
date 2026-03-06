import os
import json
import logging
import traceback
from datetime import datetime, timedelta
from sqlalchemy import text
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session as get_supabase_session, supabase_db
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app

from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.models.shopee_orders import ShopeeOrders
# from nistiprint_shared.models.v2_chat_events import V2ChatEvents # Deprecated
# from nistiprint_shared.models.order_personalizations import OrderPersonalizations # Deprecated
# from nistiprint_shared.models.ai_execution_log import AiExecutionLog # Deprecated
from nistiprint_shared.models.supabase_chat import MensagemChatShopee
from nistiprint_shared.models.supabase_ai_log import LogsExecucaoIA
from nistiprint_shared.models.supabase_personalizacao import PersonalizacaoPedido

from nistiprint_shared.utils import process_message_content

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
model_name = "gemini-2.5-flash" # Updated to a supported stable version for the new SDK
client = None
try:
    # Unified AI Model Initialization using API Key from environment variable
    logger.info("Attempting to initialize Google GenAI model...")
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        from google import genai
        client = genai.Client(api_key=api_key)
        logger.info("Google GenAI model initialized successfully using API key.")
    else:
        logger.error("GEMINI_API_KEY not found in environment variables.")
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

# Load prompt template from file or environment
def load_prompt_template():
    # 1. Try loading from environment variable for easy updates without redeploy
    env_prompt = os.environ.get("AI_PROMPT_TEMPLATE")
    if env_prompt:
        return env_prompt

    # 2. Fallback to file using absolute path relative to this script
    base_path = os.path.dirname(os.path.abspath(__file__))
    # Look for templates in the package directory
    file_path = os.path.join(base_path, "..", "templates", "prompts", "prompt_template.txt")
    
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.warning(f"Prompt template file not found at {file_path}. Using default.")
    except Exception as e:
        logger.error(f"Error loading prompt template from file: {e}")
    
    # 3. Last resort fallback
    return "Você é um assistente especialista em extrair nomes de textos. Extraia os nomes do seguinte texto: {context}"

# Load prompt template
PROMPT_TEMPLATE = load_prompt_template()

def get_orders_with_chats(order_sn=None, limit=None):
    """
    Retrieve orders with their related items and chat messages using Supabase Views.
    Optimized to use view_vendas_personalizadas and view_mensagens_chat.
    """
    try:
        logger.info(f"get_orders_with_chats optimized called with order_sn={order_sn}, limit={limit}")
        
        # 1. Fetch Orders from the NEW View V3 (Unified Model)
        query = supabase_db.table('view_vendas_personalizadas_v3') \
            .select('*') \
            .order('data_pedido', desc=True)

        if order_sn:
            query = query.eq('numero_loja', order_sn)
        
        # We need a strict filter here: only orders that have shopee data (buyer_username)
        # to match the original logic. The view does a LEFT JOIN, so we filter in memory or query.
        # Original logic: WHERE so.informacoes_comprador IS NOT NULL
        query = query.not_.is_('buyer_username', 'null')

        if limit and not order_sn:
            query = query.limit(limit)

        response = query.execute()
        rows = response.data if response else []
        
        if not rows:
            return []

        now = datetime.now()
        
        for row in rows:
            order_date_str = row['data_pedido']
            try:
                if isinstance(order_date_str, str):
                    order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                else:
                    order_date = datetime.combine(order_date_str, datetime.min.time())
            except:
                order_date = now

            # Construct the order dictionary matching the expected structure
            order_dict = {
                'order_id': row['id'],
                'bling_number': row['numero_pedido'],
                'shopee_order_sn': row['numero_loja'],
                'order_date': order_date.isoformat(),
                'bling_id': row['bling_id'],
                'buyer_info': row['informacoes_comprador'],
                'message_to_seller': row['shopee_message'],
                'items': row['itens'] if row['itens'] else []
            }

            # Parse buyer_info if it's a string (though view tries to handle it)
            if isinstance(order_dict['buyer_info'], str):
                try:
                    order_dict['buyer_info'] = json.loads(order_dict['buyer_info'])
                except:
                    order_dict['buyer_info'] = {}
            elif not order_dict['buyer_info']:
                order_dict['buyer_info'] = {}

            # Fetch chat messages using the view_mensagens_chat
            # If order_sn is provided, we look 30 days around the order date
            # Otherwise, we look at last 7 days from now
            username = row.get('buyer_username')
            if username:
                try:
                    chat_query = supabase_db.table('view_mensagens_chat') \
                        .select("*") \
                        .or_(f"from_user_name.eq.{username},to_user_name.eq.{username}")
                    
                    if order_sn:
                        # Window: 30 days before order date until 2 days after
                        start_date = (order_date - timedelta(days=30)).isoformat()
                        end_date = (order_date + timedelta(days=2)).isoformat()
                        chat_query = chat_query.gte('created_at', start_date).lte('created_at', end_date)
                    else:
                        fourteen_days_ago_iso = (now - timedelta(days=14)).isoformat()
                        chat_query = chat_query.gt('created_at', fourteen_days_ago_iso)
                    
                    chat_data = chat_query.order('created_at', desc=False).execute()
                    chat_rows = chat_data.data if chat_data else []
                except Exception as e:
                    logger.error(f"Error fetching chats from view for {username}: {e}")
                    chat_rows = []

                processed_messages = []
                for msg_row in chat_rows:
                    # Message is already formatted by the view
                    message = {
                        'id': str(msg_row.get('id')),
                        'from_user_name': msg_row.get('from_user_name') or '',
                        'to_user_name': msg_row.get('to_user_name') or '',
                        'content': msg_row.get('content', ''),
                        'created_at': msg_row.get('created_at'),
                        'type': msg_row.get('type', 'text').lower(),
                        'display_content': msg_row.get('display_content'),
                        'is_sender': msg_row.get('from_user_name') == username
                    }
                    processed_messages.append(message)

                order_dict['chat_messages'] = processed_messages
            else:
                order_dict['chat_messages'] = []

            processed_orders.append(order_dict)

        return processed_orders

    except Exception as e:
        logger.error(f"Error fetching orders with chats: {str(e)}")
        raise



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
    if not client:
        raise RuntimeError("AI model (client) is not initialized. Check startup logs for errors.")

    prompt = f"{PROMPT_TEMPLATE}\n{prompt_payload}"

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
    except Exception as e:
        logging.error(f"Falha ao processar prompt, error: {e}")
        raise

    return response

def delete_extraction_records(order_data, session=None):
    """
    Delete extraction records from the Supabase database.
    """
    # Using SupabaseDBService directly since we don't have scoped session management same as Flask-SQLAlchemy
    try:
        shopee_order_sn = order_data.get('shopee_order_sn') or order_data.get('loja_id') # loja_id fallback
        if not shopee_order_sn:
             logger.warning("No shopee_order_sn provided for deletion.")
             return

        # Delete from Supabase table 'personalizacoes_pedido'
        supabase_db.table('personalizacoes_pedido') \
            .delete() \
            .eq('shopee_order_sn', shopee_order_sn) \
            .execute()
            
    except Exception as e:
        logger.error(f"Error deleting extraction records: {str(e)}")
        # Raise if critical, but for delete we might just log
        raise


def save_extraction_results(order_data, extraction_result):
    """
    Save the extraction results to the Supabase database.
    """
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

        # Delete existing records first
        delete_extraction_records(order_data)

        # Insert each personalized item using Supabase Session
        with get_supabase_session() as session:
            for item in extraction_result.get('personalized_items', []):
                personalization = PersonalizacaoPedido()
                personalization.shopee_order_sn = str(extraction_result['shopee_order_sn'])
                personalization.codigo_pedido = str(extraction_result['shopee_order_sn'])
                personalization.bling_id = str(order_data.get('bling_id') or '')
                personalization.status = extraction_result['status']
                personalization.reasoning = extraction_result.get('reasoning')
                personalization.item_id = str(item.get('item_id') or '')
                personalization.item_description = item.get('item_description', '')[:1000]
                personalization.customization_name = item.get('customization_name')
                personalization.name_source_message_id = str(item.get('name_source_message_id') or '')
                personalization.customization_initial = item.get('customization_initial')
                personalization.updated_at = datetime.utcnow()
                
                # Metadata field in Supabase is JSONB, handle appropriately
                metadata = {
                    'extraction_timestamp': datetime.utcnow().isoformat(),
                    'source': model_name,
                    'version': '2.0',
                    'processed_at': datetime.utcnow().isoformat(),
                    'quantity_to_personalize': item.get('quantity_to_personalize', 1),
                    'initial_source_message_id': item.get('initial_source_message_id')
                }
                # The model wrapper might expect a dict for JSONB columns if using Supabase client directly,
                # but since we are using get_supabase_session (simulated SQLAlchemy), we use json.dumps
                personalization.metadata = json.dumps(metadata)

                session.add(personalization)
            
            # The context manager handles commit/rollback simulation
            pass

        logger.info(f"Successfully saved extraction results for order {extraction_result['order_id']}")
        return True

    except Exception as e:
        logger.error(f"Error in save_extraction_results: {str(e)}", exc_info=True)
        return False


def log_ai_execution(order_sn, input_data, chat_context, extracted_personalization, model_result, status, error_message=None, user_feedback_id=None):
    try:
        with get_supabase_session() as session:
            log_entry = LogsExecucaoIA()
            log_entry.order_sn = order_sn
            log_entry.executed_at = datetime.utcnow()
            
            # Supabase handles JSONB, but model defines as Text for compatibility, so dumps.
            log_entry.input_data = json.dumps(input_data, ensure_ascii=False, default=str)
            log_entry.chat_context = json.dumps(chat_context, ensure_ascii=False, default=str)
            log_entry.extracted_personalization = json.dumps(extracted_personalization, ensure_ascii=False, default=str) if extracted_personalization else None
            log_entry.model_result = json.dumps(model_result, ensure_ascii=False, default=str) if model_result else None
            
            log_entry.status = status
            log_entry.error_message = error_message
            log_entry.user_feedback_id = user_feedback_id
            
            session.add(log_entry)
            
    except Exception as e:
        logger.error(f"Error logging AI execution: {str(e)}", exc_info=True)


def get_logs_by_order_sn(order_sn):
    """
    Retrieve AI execution logs for a specific order SN from Supabase.
    """
    try:
        # Use SupabaseQueryInterface via Model
        # Pass string 'executed_at desc' for ordering as SupabaseQueryInterface handles it, 
        # whereas the mock Column object doesn't have a .desc() method.
        logs = LogsExecucaoIA.query.filter_by(order_sn=order_sn).order_by('executed_at desc').all()
        return [
            {
                'id': log.id,
                'order_sn': log.order_sn,
                'executed_at': log.executed_at.isoformat() if hasattr(log.executed_at, 'isoformat') else str(log.executed_at),
                'input_data': json.loads(log.input_data) if isinstance(log.input_data, str) else log.input_data,
                'chat_context': json.loads(log.chat_context) if isinstance(log.chat_context, str) else log.chat_context,
                'extracted_personalization': json.loads(log.extracted_personalization) if isinstance(log.extracted_personalization, str) else log.extracted_personalization,
                'model_result': json.loads(log.model_result) if isinstance(log.model_result, str) else log.model_result,
                'status': log.status,
                'error_message': log.error_message,
            }
            for log in logs
        ]
    except Exception as e:
        logger.error(f"Error fetching logs for order_sn {order_sn}: {e}", exc_info=True)
        return []


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
        logger.info(f"Starting order processing... Limit: {limit}, Order SN: {order_sn}") # DEBUG LOG
        print(f"DEBUG PRINT: Starting process_orders. Order SN: {order_sn}") # EXTREME DEBUG
        app = current_app._get_current_object()

        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        # Slicing is no longer needed here as it is handled in the query, but we keep it safe for now or remove if confident.
        # If limit was passed, orders should already be limited. 
        # But wait, we fetch Bling orders with limit, then we filter by Shopee. 
        # So we might get fewer than 'limit' orders.
        # If we really need 'limit' processed orders, we'd need to fetch more and slice here.
        # For now, let's assume the query limit is a "fetch limit" strategy.

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

