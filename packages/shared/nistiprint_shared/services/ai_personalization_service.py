import os
import json
import logging
from datetime import datetime, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app

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

# Load prompt template from DB, then env, then file, then default
def load_prompt_template():
    """
    Carrega o prompt template com a seguinte prioridade:
    1. Banco de dados (configuracoes_aplicacao) — salvo via UI de configuração
    2. Variável de ambiente AI_PROMPT_TEMPLATE
    3. Arquivo prompt_template.txt
    4. Fallback hardcoded
    """
    # 1. Try loading from database (highest priority — user-configured via UI)
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        db_config = app_config_service.get_config('prompt_template')
        if db_config:
            # Pode vir como string ou objeto { text: ... }
            if isinstance(db_config, dict):
                prompt = db_config.get('text', '')
            else:
                prompt = db_config
            if prompt:
                logger.info("Prompt template carregado do banco de dados (%d caracteres)", len(prompt))
                return prompt
    except Exception as e:
        logger.warning(f"Não foi possível carregar prompt do DB: {e}")

    # 2. Try loading from environment variable
    env_prompt = os.environ.get("AI_PROMPT_TEMPLATE")
    if env_prompt:
        logger.info("Prompt template carregado da variável de ambiente")
        return env_prompt

    # 3. Fallback to file using absolute path relative to this script
    base_path = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_path, "..", "templates", "prompts", "prompt_template.txt")

    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                logger.info("Prompt template carregado do arquivo %s", file_path)
                return file.read()
        else:
            logger.warning(f"Prompt template file not found at {file_path}. Using default.")
    except Exception as e:
        logger.error(f"Error loading prompt template from file: {e}")

    # 4. Last resort fallback
    logger.warning("Usando prompt template fallback (nenhuma fonte configurada)")
    return "Você é um assistente especialista em extrair nomes de textos. Extraia os nomes do seguinte texto: {context}"

# Load prompt template
PROMPT_TEMPLATE = load_prompt_template()

def get_orders_with_chats(order_sn=None, limit=None, mode=None):
    """
    Retrieve orders with their related items and chat messages using Supabase Views.

    Args:
        order_sn: Optional Shopee order SN to filter by
        limit: Optional limit on number of orders
        mode: 'v3' for unified model, 'legacy' for Bling MySQL view (default: 'legacy')
    """
    if not mode:
        from nistiprint_shared.services.app_config_service import app_config_service
        mode = 'v3' if app_config_service.get_operational_mode() == 'v2' else 'legacy'

    if mode == 'v3':
        return _get_orders_with_chats_v3(order_sn=order_sn, limit=limit)
    return _get_orders_with_chats_legacy(order_sn=order_sn, limit=limit)


def _get_orders_with_chats_v3(order_sn=None, limit=None):
    """
    Retrieve orders using unified model view (pedidos + itens_pedido).
    Uses view_vendas_personalizadas_v3 which filters by itens_pedido.personalizado=true.
    """
    try:
        logger.info(f"get_orders_with_chats V3 called with order_sn={order_sn}, limit={limit}")

        query = supabase_db.table('view_vendas_personalizadas_v3') \
            .select('*') \
            .order('data_pedido', desc=True)

        if order_sn:
            query = query.eq('numero_loja', order_sn)

        if limit and not order_sn:
            query = query.limit(limit)

        response = query.execute()
        rows = response.data if response else []

        if not rows:
            logger.info("No orders found (V3 view).")
            return []

        now = datetime.now()
        processed_orders = []

        for row in rows:
            # Filter: only orders with buyer_username (Shopee data)
            buyer_username = row.get('buyer_username')
            if not buyer_username:
                continue

            order_date_str = row.get('data_pedido')
            try:
                if isinstance(order_date_str, str):
                    order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                else:
                    order_date = datetime.combine(order_date_str, datetime.min.time())
            except Exception:
                order_date = now

            # Parse buyer_info
            buyer_info = row.get('informacoes_comprador') or {}
            if isinstance(buyer_info, str):
                try:
                    buyer_info = json.loads(buyer_info)
                except Exception:
                    buyer_info = {}

            # Parse items (view returns JSONB)
            items = row.get('itens') or []
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            # Construct the order dictionary
            order_dict = {
                'order_id': str(row.get('id', '')),
                'bling_number': row.get('numero_pedido', ''),
                'shopee_order_sn': row.get('numero_loja', ''),
                'order_date': order_date.isoformat(),
                'bling_id': row.get('bling_id', ''),
                'buyer_info': buyer_info,
                'message_to_seller': row.get('shopee_message') or '',
                'items': items
            }

            # Fetch chat messages using view_mensagens_chat
            try:
                chat_query = supabase_db.table('view_mensagens_chat') \
                    .select("*") \
                    .or_(f"from_user_name.eq.{buyer_username},to_user_name.eq.{buyer_username}")

                if order_sn:
                    start_date = (order_date - timedelta(days=30)).isoformat()
                    end_date = (order_date + timedelta(days=2)).isoformat()
                    chat_query = chat_query.gte('created_at', start_date).lte('created_at', end_date)
                else:
                    fourteen_days_ago_iso = (now - timedelta(days=14)).isoformat()
                    chat_query = chat_query.gt('created_at', fourteen_days_ago_iso)

                chat_data = chat_query.order('created_at', desc=False).execute()
                chat_rows = chat_data.data if chat_data else []
            except Exception as e:
                logger.error(f"Error fetching chats from view for {buyer_username}: {e}")
                chat_rows = []

            processed_messages = []
            for msg_row in chat_rows:
                message = {
                    'id': str(msg_row.get('id')),
                    'from_user_name': msg_row.get('from_user_name') or '',
                    'to_user_name': msg_row.get('to_user_name') or '',
                    'content': msg_row.get('content', ''),
                    'created_at': msg_row.get('created_at'),
                    'type': (msg_row.get('type') or 'text').lower(),
                    'display_content': msg_row.get('display_content', ''),
                    'is_sender': msg_row.get('from_user_name') == buyer_username
                }
                processed_messages.append(message)

            order_dict['chat_messages'] = processed_messages
            processed_orders.append(order_dict)

        logger.info(f"Returning {len(processed_orders)} orders with chats (V3).")
        return processed_orders

    except Exception as e:
        logger.error(f"Error fetching orders with chats (V3): {str(e)}")
        raise


def _get_orders_with_chats_legacy(order_sn=None, limit=None):
    """
    Retrieve orders using legacy Bling MySQL view (pedidos_bling + itens_pedido_bling).
    Kept for backward compatibility during migration.
    """
    try:
        logger.info(f"get_orders_with_chats LEGACY called with order_sn={order_sn}, limit={limit}")

        query = supabase_db.table('view_vendas_personalizadas') \
            .select('*') \
            .order('data_pedido', desc=True)

        if order_sn:
            query = query.eq('numero_loja', order_sn)

        if limit and not order_sn:
            query = query.limit(limit)

        response = query.execute()
        rows = response.data if response else []

        if not rows:
            logger.info("No orders found (Legacy view).")
            return []

        now = datetime.now()
        processed_orders = []

        for row in rows:
            buyer_username = row.get('buyer_username')
            if not buyer_username:
                continue

            order_date_str = row.get('data_pedido')
            try:
                if isinstance(order_date_str, str):
                    order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                else:
                    order_date = datetime.combine(order_date_str, datetime.min.time())
            except Exception:
                order_date = now

            buyer_info = row.get('informacoes_comprador') or {}
            if isinstance(buyer_info, str):
                try:
                    buyer_info = json.loads(buyer_info)
                except Exception:
                    buyer_info = {}

            items = row.get('itens') or []
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            order_dict = {
                'order_id': str(row.get('id', '')),
                'bling_number': row.get('numero_pedido', ''),
                'shopee_order_sn': row.get('numero_loja', ''),
                'order_date': order_date.isoformat(),
                'bling_id': row.get('bling_id', ''),
                'buyer_info': buyer_info,
                'message_to_seller': row.get('shopee_message') or '',
                'items': items
            }

            try:
                chat_query = supabase_db.table('view_mensagens_chat') \
                    .select("*") \
                    .or_(f"from_user_name.eq.{buyer_username},to_user_name.eq.{buyer_username}")

                if order_sn:
                    start_date = (order_date - timedelta(days=30)).isoformat()
                    end_date = (order_date + timedelta(days=2)).isoformat()
                    chat_query = chat_query.gte('created_at', start_date).lte('created_at', end_date)
                else:
                    fourteen_days_ago_iso = (now - timedelta(days=14)).isoformat()
                    chat_query = chat_query.gt('created_at', fourteen_days_ago_iso)

                chat_data = chat_query.order('created_at', desc=False).execute()
                chat_rows = chat_data.data if chat_data else []
            except Exception as e:
                logger.error(f"Error fetching chats from view for {buyer_username}: {e}")
                chat_rows = []

            processed_messages = []
            for msg_row in chat_rows:
                message = {
                    'id': str(msg_row.get('id')),
                    'from_user_name': msg_row.get('from_user_name') or '',
                    'to_user_name': msg_row.get('to_user_name') or '',
                    'content': msg_row.get('content', ''),
                    'created_at': msg_row.get('created_at'),
                    'type': (msg_row.get('type') or 'text').lower(),
                    'display_content': msg_row.get('display_content', ''),
                    'is_sender': msg_row.get('from_user_name') == buyer_username
                }
                processed_messages.append(message)

            order_dict['chat_messages'] = processed_messages
            processed_orders.append(order_dict)

        logger.info(f"Returning {len(processed_orders)} orders with chats (Legacy).")
        return processed_orders

    except Exception as e:
        logger.error(f"Error fetching orders with chats (Legacy): {str(e)}")
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
    try:
        shopee_order_sn = order_data.get('shopee_order_sn')
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


def _resolve_item_pedido_id(shopee_order_sn: str, item_description: str) -> int | None:
    """
    Resolve o ID do itens_pedido unificado a partir do shopee_order_sn e descricao.
    Retorna None se não encontrar.
    """
    try:
        # 1. Encontrar o pedido unificado pelo codigo_pedido_externo
        pedido_result = supabase_db.table('pedidos') \
            .select('id') \
            .eq('codigo_pedido_externo', shopee_order_sn) \
            .execute()

        if not pedido_result.data:
            logger.debug(
                "Pedido unificado não encontrado para shopee_order_sn=%s",
                shopee_order_sn
            )
            return None

        pedido_id = pedido_result.data[0]['id']

        # 2. Encontrar o item pela descricao
        item_result = supabase_db.table('itens_pedido') \
            .select('id') \
            .eq('pedido_id', pedido_id) \
            .eq('descricao', item_description) \
            .execute()

        if item_result.data:
            return item_result.data[0]['id']

        # 3. Fallback: tentativa por parcial match na descricao
        item_result = supabase_db.table('itens_pedido') \
            .select('id') \
            .eq('pedido_id', pedido_id) \
            .ilike('descricao', f'%{item_description[:50]}%') \
            .execute()

        if item_result.data:
            logger.info(
                "Match parcial de descricao para item_pedido_id: '%s' -> %d",
                item_description[:50], item_result.data[0]['id']
            )
            return item_result.data[0]['id']

        logger.debug(
            "Item não encontrado para pedido_id=%d, descricao=%s",
            pedido_id, item_description[:50]
        )
        return None

    except Exception as e:
        logger.error(f"Erro ao resolver item_pedido_id: {e}", exc_info=True)
        return None


def save_extraction_results(order_data, extraction_result):
    """
    Save the extraction results to the Supabase database.
    Uses direct supabase_db.insert for reliability.
    Resolves item_pedido_id for direct match with unified itens_pedido table.
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

        shopee_order_sn = extraction_result['shopee_order_sn']

        # Delete existing records first
        delete_extraction_records(order_data)

        # Insert each personalized item
        items_to_insert = []
        for item in extraction_result.get('personalized_items', []):
            item_description = (item.get('item_description', '') or '')[:1000]

            # Resolver item_pedido_id para match direto com itens_pedido
            item_pedido_id = _resolve_item_pedido_id(
                shopee_order_sn, item_description
            )

            # Move extra fields to detalhes_personalizacao JSONB
            detalhes = {
                'quantity_to_personalize': item.get('quantity_to_personalize', 1),
                'initial_source_message_id': item.get('initial_source_message_id')
            }

            record = {
                'codigo_pedido': str(shopee_order_sn),
                'shopee_order_sn': str(shopee_order_sn),
                'bling_id': str(order_data.get('bling_id') or ''),
                'status': extraction_result['status'],
                'reasoning': extraction_result.get('reasoning'),
                'item_id': str(item.get('item_id') or ''),
                'item_description': item_description,
                'item_pedido_id': item_pedido_id,
                'customization_name': item.get('customization_name'),
                'name_source_message_id': str(item.get('name_source_message_id') or '') if item.get('name_source_message_id') else None,
                'customization_initial': item.get('customization_initial'),
                'dados_cliente': order_data.get('buyer_info', {}),
                'detalhes_personalizacao': detalhes,
                'metadata': {
                    'extraction_timestamp': datetime.utcnow().isoformat(),
                    'source': model_name,
                    'version': '2.1',
                    'processed_at': datetime.utcnow().isoformat()
                },
                'updated_at': datetime.utcnow().isoformat()
            }
            items_to_insert.append(record)

        if items_to_insert:
            supabase_db.table('personalizacoes_pedido').insert(items_to_insert).execute()

        logger.info(f"Successfully saved {len(items_to_insert)} extraction results for order {shopee_order_sn}")
        return True

    except Exception as e:
        logger.error(f"Error in save_extraction_results: {str(e)}", exc_info=True)
        return False


def log_ai_execution(order_sn, input_data, chat_context, extracted_personalization, model_result, status, error_message=None, user_feedback_id=None):
    """Log AI execution to logs_execucao_ia table."""
    try:
        supabase_db.table('logs_execucao_ia').insert({
            'order_sn': order_sn,
            'executed_at': datetime.utcnow().isoformat(),
            'input_data': input_data,
            'chat_context': chat_context,
            'extracted_personalization': extracted_personalization,
            'model_result': model_result,
            'status': status,
            'error_message': error_message,
            'user_feedback_id': user_feedback_id,
            'metadata': {
                'logged_at': datetime.utcnow().isoformat(),
                'source': model_name
            }
        }).execute()
    except Exception as e:
        logger.error(f"Error logging AI execution: {str(e)}", exc_info=True)


def get_logs_by_order_sn(order_sn):
    """
    Retrieve AI execution logs for a specific order SN from Supabase.
    """
    try:
        response = supabase_db.table('logs_execucao_ia') \
            .select('*') \
            .eq('order_sn', order_sn) \
            .order('executed_at', desc=True) \
            .execute()

        logs = response.data if response else []
        return [
            {
                'id': log.get('id'),
                'order_sn': log.get('order_sn'),
                'executed_at': log.get('executed_at'),
                'input_data': log.get('input_data'),
                'chat_context': log.get('chat_context'),
                'extracted_personalization': log.get('extracted_personalization'),
                'model_result': log.get('model_result'),
                'status': log.get('status'),
                'error_message': log.get('error_message'),
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
        logger.info(f"Starting order processing... Limit: {limit}, Order SN: {order_sn}")
        app = current_app._get_current_object()

        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        total_orders = len(orders)
        logger.info(f"Found {total_orders} orders to process")

        if total_orders == 0:
            return True, "No orders to process."

        processed_count = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_process_single_order, app, order, i + 1, total_orders): order for i, order in enumerate(orders)}

            for future in as_completed(futures):
                order = futures[future]
                try:
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

