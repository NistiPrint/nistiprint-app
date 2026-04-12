import os
import json
import time
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
logger.info("[IA] PROMPT_TEMPLATE carregado: %d caracteres, inicia com: %s",
            len(PROMPT_TEMPLATE), PROMPT_TEMPLATE[:100].replace('\n', ' '))

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
    Uses view_vendas_personalizadas_v3 which filters by:
    - itens_pedido.personalizado = true
    - UPPER(origem) IN ('SHOPEE', 'BLING', 'MARKETPLACE')
    """
    try:
        logger.info("=" * 60)
        logger.info("[V3] INÍCIO: _get_orders_with_chats_v3(order_sn=%s, limit=%s)", order_sn, limit)
        logger.info("[V3] View filtra: personalizado=true + origem IN (SHOPEE, BLING, MARKETPLACE)")
        print(f"[V3] >>> Query view_vendas_personalizadas_v3: personalizado=true + buyer_username (Shopee)")
        logger.info("=" * 60)

        logger.info("[V3] Passo 1: Montando query na view_vendas_personalizadas_v3")
        query = supabase_db.table('view_vendas_personalizadas_v3') \
            .select('*') \
            .order('data_pedido', desc=True)

        if order_sn:
            logger.info("[V3] Passo 1b: Filtrando por numero_loja = %s", order_sn)
            query = query.eq('numero_loja', order_sn)

        if limit and not order_sn:
            logger.info("[V3] Passo 1c: Limitando a %d", limit)
            query = query.limit(limit)

        logger.info("[V3] Passo 2: Executando query...")
        response = query.execute()
        rows = response.data if response else []
        logger.info("[V3] Passo 2: query retornou %d rows", len(rows))

        if rows:
            logger.info("[V3] Passo 2b: Tipos das rows: %s", [type(r).__name__ for r in rows[:3]])
            logger.info("[V3] Passo 2c: Primeira row keys: %s", list(rows[0].keys()) if isinstance(rows[0], dict) else type(rows[0]))

        if not rows:
            logger.info("[V3] Nenhum order encontrado na view.")
            return []

        now = datetime.now()
        processed_orders = []

        for i, row in enumerate(rows):
            logger.info("[V3] Passo 3: Processando row %d (tipo=%s)", i, type(row).__name__)

            if not isinstance(row, dict):
                logger.warning("[V3] Row %d não é dict (tipo=%s, valor=%r) — pulando", i, type(row).__name__, row)
                continue

            # Filter: only orders with buyer_username (Shopee data)
            buyer_username = row.get('buyer_username')
            logger.info("[V3] Passo 3b: buyer_username = %s", buyer_username)
            if not buyer_username:
                logger.info("[V3] Passo 3b: Sem buyer_username — pulando row %d", i)
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

            # CRÍTICO: injetar buyer_username no buyer_info para o prompt payload
            # A view retorna buyer_username separado, mas buyer_info vem do Bling sem 'username'
            if not buyer_info.get('username'):
                buyer_info['username'] = buyer_username

            # Parse items (view returns JSONB)
            items = row.get('itens') or []
            logger.info("[V3] Passo 3c: items tipo=%s, len=%s", type(items).__name__, len(items) if hasattr(items, '__len__') else 'N/A')
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
            logger.info("[V3] Passo 3d: order_dict criado — shopee_order_sn=%s", order_dict['shopee_order_sn'])

            # Fetch chat messages using view_mensagens_chat
            try:
                logger.info("[V3] Passo 4: Buscando chat messages para buyer_username=%s", buyer_username)
                chat_query = supabase_db.table('view_mensagens_chat') \
                    .select("*") \
                    .or_(f"from_user_name.eq.{buyer_username},to_user_name.eq.{buyer_username}")

                if order_sn:
                    start_date = (order_date - timedelta(days=30)).isoformat()
                    end_date = (order_date + timedelta(days=2)).isoformat()
                    logger.info("[V3] Passo 4b: Filtrando chat por data [%s, %s]", start_date, end_date)
                    chat_query = chat_query.gte('created_at', start_date).lte('created_at', end_date)
                else:
                    fourteen_days_ago_iso = (now - timedelta(days=14)).isoformat()
                    chat_query = chat_query.gt('created_at', fourteen_days_ago_iso)

                chat_data = chat_query.order('created_at', desc=False).execute()
                chat_rows = chat_data.data if chat_data else []
                logger.info("[V3] Passo 4: %d mensagens de chat encontradas", len(chat_rows))
            except Exception as e:
                logger.error("[V3] Erro ao buscar chat para %s: %s", buyer_username, e, exc_info=True)
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
            logger.info("[V3] Passo 5: order_dict adicionado a processed_orders (total=%d)", len(processed_orders))

        logger.info("[V3] FIM: Retornando %d orders com chats.", len(processed_orders))
        logger.info("=" * 60)
        return processed_orders

    except Exception as e:
        logger.error("[V3] ERRO CRÍTICO em _get_orders_with_chats_v3: %s", e, exc_info=True)
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
    Includes retry with backoff for transient network errors.
    """
    if not client:
        raise RuntimeError("AI model (client) is not initialized. Check startup logs for errors.")

    prompt = f"{PROMPT_TEMPLATE}\n{prompt_payload}"
    prompt_len = len(prompt)
    template_len = len(PROMPT_TEMPLATE)
    payload_len = len(prompt_payload)

    logger.info("[IA] Enviando para Gemini: model=%s, prompt_len=%d (template=%d + payload=%d)",
                model_name, prompt_len, template_len, payload_len)
    print(f"[IA] >>> Enviando para Gemini ({model_name}): prompt={prompt_len} chars (template={template_len} + payload={payload_len})")

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            start_time = time.time()
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            elapsed = time.time() - start_time
            resp_len = len(response.text) if response and response.text else 0
            logger.info("[IA] Resposta recebida: %d caracteres em %.1fs", resp_len, elapsed)
            print(f"[IA] <<< Resposta recebida: {resp_len} chars em {elapsed:.1f}s")
            return response
        except Exception as e:
            if attempt < max_retries:
                wait = 2 * (attempt + 1)  # 2s, 4s
                logger.warning("[IA] Tentativa %d/%d falhou: %s — retry em %ds", attempt + 1, max_retries + 1, e, wait)
                print(f"[IA] ⚠ Tentativa {attempt+1}/{max_retries+1} falhou: {e} — retry em {wait}s")
                time.sleep(wait)
            else:
                logger.error("[IA] Falha definitiva após %d tentativas: %s", max_retries + 1, e, exc_info=True)
                print(f"[IA] ✗ Falha definitiva após {max_retries+1} tentativas: {e}")
                raise

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


def _batch_resolve_item_pedido_ids(shopee_order_sn: str, item_descriptions: list[str]) -> dict:
    """
    Resolve múltiplos item_pedido_ids em batch (2 queries ao invés de 2*N).
    Retorna dict: {descricao: item_pedido_id ou None}
    """
    results = {desc: None for desc in item_descriptions}

    if not item_descriptions:
        return results

    try:
        # 1. Encontrar o pedido (1 query)
        pedido_result = supabase_db.table('pedidos') \
            .select('id') \
            .eq('codigo_pedido_externo', shopee_order_sn) \
            .execute()

        if not pedido_result.data:
            return results

        pedido_id = pedido_result.data[0]['id']

        # 2. Buscar todos os itens do pedido em 1 query
        items_result = supabase_db.table('itens_pedido') \
            .select('id, descricao') \
            .eq('pedido_id', pedido_id) \
            .execute()

        if not items_result.data:
            return results

        # Build lookup: descricao -> id
        items_by_desc = {item['descricao']: item['id'] for item in items_result.data}

        # Match exato
        for desc in item_descriptions:
            if desc in items_by_desc:
                results[desc] = items_by_desc[desc]

        # Fallback: match parcial para os que não bateram
        for desc, resolved_id in results.items():
            if resolved_id is not None:
                continue
            # Tenta match parcial com os primeiros 50 chars
            search_term = desc[:50].lower()
            for item_desc, item_id in items_by_desc.items():
                if search_term in item_desc.lower():
                    results[desc] = item_id
                    logger.info("Batch match parcial: '%s' -> '%s' (id=%d)", desc[:50], item_desc[:50], item_id)
                    break

    except Exception as e:
        logger.error(f"Erro no batch resolve item_pedido_ids: {e}")

    return results


def _truncate(value, max_len=30000):
    """Trunca string para não exceder o limite do Cloudflare."""
    if value is None:
        return None
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"\n... (truncado de {len(value)} para {max_len} chars)"
    return value


def _truncate_json(value, max_len=30000):
    """Trunca valor JSON para não exceder o limite do Cloudflare."""
    if value is None:
        return None
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if len(s) > max_len:
        return s[:max_len] + f"\n... (truncado de {len(s)} para {max_len} chars)"
    return s


def save_extraction_results(order_data, extraction_result):
    """
    Save the extraction results to the Supabase database.
    Build-then-insert: inserts new records BEFORE deleting old ones,
    preventing data loss if inserts fail.
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

        # STEP 1: Batch resolve all item_pedido_ids (2 queries instead of 2*N)
        personalized_items = extraction_result.get('personalized_items', [])
        item_descriptions = [(item.get('item_description', '') or '')[:1000] for item in personalized_items]
        resolved_ids = _batch_resolve_item_pedido_ids(shopee_order_sn, item_descriptions)
        print(f"[DB] Batch resolve: {len(item_descriptions)} items → {sum(1 for v in resolved_ids.values() if v is not None)} encontrados")

        # STEP 2: Build all records (no DB changes yet)
        records_to_insert = []
        for idx, item in enumerate(personalized_items):
            item_description = item_descriptions[idx]
            item_pedido_id = resolved_ids.get(item_description)

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
                'reasoning': _truncate(extraction_result.get('reasoning'), 2000),
                'item_id': str(item.get('item_id') or ''),
                'item_description': item_description,
                'item_pedido_id': item_pedido_id,
                'customization_name': _truncate(item.get('customization_name'), 500),
                'name_source_message_id': str(item.get('name_source_message_id') or '') if item.get('name_source_message_id') else None,
                'customization_initial': _truncate(item.get('customization_initial'), 100),
                'dados_cliente': _truncate_json(order_data.get('buyer_info', {}), 2000),
                'detalhes_personalizacao': detalhes,
                'metadata': {
                    'extraction_timestamp': datetime.utcnow().isoformat(),
                    'source': model_name,
                    'version': '3.0',
                    'processed_at': datetime.utcnow().isoformat()
                },
                'updated_at': datetime.utcnow().isoformat()
            }
            records_to_insert.append(record)

        # STEP 3: Insert all new records (with retry)
        items_saved = 0
        for record in records_to_insert:
            for attempt in range(3):
                try:
                    supabase_db.table('personalizacoes_pedido').insert(record).execute()
                    items_saved += 1
                    break
                except Exception as insert_err:
                    logger.warning(f"Insert attempt {attempt+1}/3 failed for {shopee_order_sn}: {insert_err}")
                    if attempt == 2:
                        raise
                    import time
                    time.sleep(1 * (attempt + 1))  # Backoff: 1s, 2s

        # STEP 4: Only delete old records AFTER successful inserts
        # This prevents data loss: if inserts failed, exception is raised
        # and we never reach here. Old records remain intact.
        delete_extraction_records(order_data)

        logger.info(f"Successfully saved {items_saved} extraction results for order {shopee_order_sn}")
        return True

    except Exception as e:
        logger.error(f"Error in save_extraction_results: {str(e)}", exc_info=True)
        return False


def log_ai_execution(order_sn, input_data, chat_context, extracted_personalization, model_result, status, error_message=None, user_feedback_id=None):
    """Log AI execution to logs_execucao_ia table. Includes retry with backoff."""
    # Truncar campos grandes para evitar bloqueio do Cloudflare (400)
    truncated_input = _truncate(input_data, 25000)
    truncated_model = _truncate_json(model_result, 15000)
    truncated_extracted = _truncate_json(extracted_personalization, 15000)

    log_record = {
        'order_sn': order_sn,
        'executed_at': datetime.utcnow().isoformat(),
        'input_data': truncated_input,
        'chat_context': truncated_extracted,
        'extracted_personalization': truncated_extracted,
        'model_result': truncated_model,
        'status': status,
        'error_message': _truncate(error_message, 1000),
        'user_feedback_id': user_feedback_id,
        'metadata': {
            'logged_at': datetime.utcnow().isoformat(),
            'source': model_name,
            'input_original_size': len(input_data) if isinstance(input_data, str) else None,
            'model_original_size': len(json.dumps(model_result)) if model_result else None,
        }
    }

    # Retry com backoff para evitar perda de logs em falhas transient
    max_retries = 3
    for attempt in range(max_retries):
        try:
            supabase_db.table('logs_execucao_ia').insert(log_record).execute()
            print(f"[LOG] ✓ Log salvo para {order_sn} status={status}")
            return  # Success
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 1 * (attempt + 1)
                logger.warning("[LOG] Tentativa %d/%d falhou para %s: %s — retry em %ds", attempt + 1, max_retries, order_sn, e, wait)
                time.sleep(wait)
            else:
                logger.error(f"[LOG] ✗ Falha definitiva ao salvar log para {order_sn}: {e}", exc_info=True)
                print(f"[LOG] ✗ Falha ao salvar log para {order_sn}: {e}")


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
        logger.info("[PROC] >>> INÍCIO _process_single_order [%d/%d]", processed_count, total_orders)
        logger.info("[PROC] Tipo do order: %s", type(order).__name__)

        if isinstance(order, str):
            logger.error("[PROC] order é string: %s — pulando", order)
            return 'error'

        order_sn = order.get('shopee_order_sn') or order.get('numeroLoja')
        print(f"[PROC] >>> [{processed_count}/{total_orders}] Iniciando {order_sn}")
        logger.info("[PROC] order_sn = %s", order_sn)
        logger.info("[PROC] order keys = %s", list(order.keys()) if isinstance(order, dict) else 'N/A')

        chat_context = order.get('chat_messages', [])
        logger.info("[PROC] chat_messages count = %d", len(chat_context))
        print(f"[PROC] [{processed_count}/{total_orders}] {order_sn}: {len(chat_context)} msgs chat, {len(order.get('items', []))} itens")

        logger.info("[PROC] Gerando prompt_payload (texto)...")
        prompt_payload = generate_prompt_payload(order)
        items_in_order = order.get('items') or []
        logger.info("[PROC] Itens no pedido: %d, prompt_payload tipo=%s, len=%d", len(items_in_order), type(prompt_payload).__name__, len(prompt_payload) if isinstance(prompt_payload, str) else 0)

        ai_result = None
        ai_response_text = None
        error_message = None
        status = 'success'

        try:
            logger.info("[PROC] Chamando modelo IA...")
            response = run_model(prompt_payload)
            if response and response.text:
                ai_response_text = response.text
                logger.info("[PROC] Resposta IA recebida (%d caracteres)", len(ai_response_text))
                ai_result = ai_response_text.replace("```json", "").replace("```", "")
                ai_result = json.loads(ai_result)
                logger.info("[PROC] Resultado parseado: %d itens personalizados", len(ai_result.get('personalized_items', [])))
                logger.info("[PROC] Salvando resultados no DB...")
                save_success = save_extraction_results(order, ai_result)
                if not save_success:
                    status = 'db_error'
                    error_message = 'Failed to save extraction results.'
                    logger.warning("[PROC] Falha ao salvar resultados no DB")
                else:
                    logger.info("[PROC] Resultados salvos com sucesso")
            else:
                status = 'no_response'
                error_message = 'No response from AI model.'
                logger.warning("[PROC] IA não retornou resposta")
        except Exception as e:
            status = 'error'
            error_message = str(e)
            logger.error("[PROC] Erro no pedido %s: %s", order_sn, e, exc_info=True)
        finally:
            # Save detailed logs
            if ai_response_text:
                # Input data para log = APENAS payload (template é muito longo)
                # Mas garantimos que run_model envia template + payload
                saved_locations = save_processing_log(
                    order_sn,
                    PROMPT_TEMPLATE,
                    prompt_payload,
                    ai_response_text
                )
                logger.info("[PROC] Logs salvos para %s: %s", order_sn, saved_locations)

            # Save execution summary to database
            logger.info("[PROC] Salvando log de execução...")
            log_ai_execution(
                order_sn=order_sn,
                input_data=prompt_payload,
                chat_context=chat_context,
                extracted_personalization=ai_result.get('personalized_items') if ai_result else None,
                model_result=ai_result,
                status=status,
                error_message=error_message
            )
            logger.info("[PROC] <<< FIM _process_single_order [%d/%d] status=%s", processed_count, total_orders, status)
            print(f"[PROC] <<< [{processed_count}/{total_orders}] {order_sn} → status={status}")
        return status


def process_orders(limit=None, order_sn=None):
    """
    Main function to process orders and extract personalizations via IA.

    REGRAS DE EXECUÇÃO:
    - Executado EXCLUSIVAMENTE sob demanda manual (botão na UI)
    - Processa APENAS pedidos da Shopee com itens.personalizado = true
    - A view_vendas_personalizadas_v3 já filtra por personalizado=true
    - O filtro buyer_username garante que só pedidos com dados Shopee são processados
    """
    print(f"{'=' * 60}")
    print(f">>> INÍCIO: process_orders(limit={limit}, order_sn={order_sn})")
    print(f">>> IA Processing: execução MANUAL — somente Shopee + personalizados")
    print(f"{'=' * 60}")

    try:
        logger.info("=" * 60)
        logger.info(">>> INÍCIO: process_orders(limit=%s, order_sn=%s)", limit, order_sn)
        logger.info("=" * 60)
        app = current_app._get_current_object()

        print("[PROC-MAIN] Chamando get_orders_with_chats...")
        logger.info("[PROC-MAIN] Chamando get_orders_with_chats...")
        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        total_orders = len(orders)
        print(f"[PROC-MAIN] Pedidos encontrados: {total_orders}")
        logger.info("[PROC-MAIN] Pedidos encontrados: %d", total_orders)
        print(f"[PROC-MAIN] Tipos: {[type(o).__name__ for o in orders[:5]]}")
        logger.info("[PROC-MAIN] Tipos dos primeiros orders: %s", [type(o).__name__ for o in orders[:5]])
        if orders:
            print(f"[PROC-MAIN] Primeiros orders: {orders[:3]}")
            logger.info("[PROC-MAIN] Primeiros orders: %s", orders[:3])

        if total_orders == 0:
            logger.warning("Nenhum pedido encontrado. Verifique:")
            logger.warning("  1. Os pedidos têm itens com 'personaliza' na descrição?")
            logger.warning("  2. Os itens estão marcados com personalizado=true?")
            logger.warning("  3. Os pedidos têm buyer_username (dados Shopee)?")
            logger.warning("  4. Rode: python scripts/backfill_personalizados.py --diagnose")
            return True, "No orders to process. Nenhum pedido encontrado com itens personalizados."

        logger.info("[PROC-MAIN] Submetendo %d orders para ThreadPoolExecutor", total_orders)
        processed_count = 0
        # Use 5 workers for sync path to avoid overwhelming DB connections
        # Celery worker path can use 10 for true parallel processing
        max_workers = min(5, total_orders)
        logger.info("[PROC-MAIN] max_workers=%d", max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            logger.info("[PROC-MAIN] Criando futures...")
            futures = {executor.submit(_process_single_order, app, order, i + 1, total_orders): order for i, order in enumerate(orders)}

            logger.info("[PROC-MAIN] Aguardando resultados...")
            for future in as_completed(futures):
                order = futures[future]
                try:
                    logger.info("[PROC-MAIN] Future completou, obtendo resultado...")
                    status = future.result()
                    logger.info("[PROC-MAIN] Resultado: status=%s", status)
                    if status == 'success':
                        processed_count += 1
                except Exception as exc:
                    order_sn_exc = order.get('shopee_order_sn') if isinstance(order, dict) else str(order)
                    logger.error('[PROC-MAIN] Pedido %s gerou exceção: %s', order_sn_exc, exc, exc_info=True)

        logger.info("=" * 60)
        logger.info("<<< FIM: process_orders — %d/%d processados com sucesso", processed_count, total_orders)
        logger.info("=" * 60)
        return True, f"Successfully processed {processed_count} of {total_orders} orders."

    except Exception as e:
        logger.error("ERRO CRÍTICO em process_orders: %s", e, exc_info=True)
        return False, str(e)

