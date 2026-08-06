import os
import json
import logging
import time
from datetime import datetime, timedelta
from sqlalchemy import text
import requests
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

DEFAULT_AI_PROVIDER = os.getenv('AI_PERSONALIZATION_PROVIDER', 'google').strip().lower()
DEFAULT_GOOGLE_MODEL = os.getenv('GOOGLE_GENERATIVE_MODEL', 'gemini-2.5-flash-lite').strip()
DEFAULT_OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free').strip()
DEFAULT_DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat').strip()

_AI_CLIENT_CACHE = {}


class AIProviderClient:
    provider_name = 'unknown'
    timeout = 120

    def __init__(self, model_name):
        self.model_name = model_name

    def generate_content(self, prompt):
        raise NotImplementedError

    def describe(self):
        return {
            'provider': self.provider_name,
            'model': self.model_name,
            'source': f'{self.provider_name}:{self.model_name}'
        }

    def _build_messages(self, prompt):
        return [
            {
                'role': 'user',
                'content': prompt
            }
        ]

    def _handle_http_error(self, response):
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise _build_provider_error(self.provider_name, response) from exc


class GoogleAIClient(AIProviderClient):
    provider_name = 'google'

    def __init__(self, model_name, api_key):
        super().__init__(model_name)
        if not api_key:
            raise RuntimeError('AISTUDIO_APIKEY environment variable not found.')

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)
        logger.info("Google Generative AI model initialized successfully.")

    def generate_content(self, prompt):
        response = self._model.generate_content(prompt)
        return getattr(response, 'text', None)


class OpenRouterAIClient(AIProviderClient):
    provider_name = 'openrouter'

    def __init__(self, model_name, api_key):
        super().__init__(model_name)
        if not api_key:
            raise RuntimeError('OPENROUTER_API_KEY environment variable not found.')
        self.api_key = api_key
        self.endpoint = os.getenv('OPENROUTER_API_URL', 'https://openrouter.ai/api/v1/chat/completions').strip()
        fallback_models = os.getenv('OPENROUTER_FALLBACK_MODELS', '').strip()
        self.fallback_models = [model.strip() for model in fallback_models.split(',') if model.strip()]
        self.max_retries = max(1, int(os.getenv('OPENROUTER_MAX_RETRIES', '2')))
        self.retry_delay_seconds = max(0, int(os.getenv('OPENROUTER_RETRY_DELAY_SECONDS', '2')))

    def _build_payload(self, prompt, model_name):
        return {
            'model': model_name,
            'messages': self._build_messages(prompt),
            'response_format': {
                'type': 'json_object'
            }
        }

    def _build_headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'HTTP-Referer': os.getenv('OPENROUTER_HTTP_REFERER', 'https://nistiprint.local'),
            'X-OpenRouter-Title': os.getenv('OPENROUTER_APP_NAME', 'NistiPrint AI Personalization')
        }

    def generate_content(self, prompt):
        candidate_models = [self.model_name] + [model for model in self.fallback_models if model != self.model_name]
        last_error = None

        for model_name in candidate_models:
            for attempt in range(1, self.max_retries + 1):
                response = requests.post(
                    self.endpoint,
                    headers=self._build_headers(),
                    json=self._build_payload(prompt, model_name),
                    timeout=self.timeout
                )

                if response.ok:
                    payload = response.json()
                    if model_name != self.model_name:
                        logger.warning(
                            f"OpenRouter fallback model '{model_name}' used after failing primary model '{self.model_name}'."
                        )
                    return _extract_chat_completion_text(payload)

                last_error = _build_provider_error(self.provider_name, response)
                if response.status_code != 429:
                    raise last_error

                logger.warning(
                    f"OpenRouter rate limit for model '{model_name}' on attempt {attempt}/{self.max_retries}: {last_error}"
                )
                if attempt < self.max_retries and self.retry_delay_seconds:
                    time.sleep(self.retry_delay_seconds)

            logger.warning(f"OpenRouter exhausted retries for model '{model_name}'.")

        raise last_error or RuntimeError('OpenRouter request failed without a detailed error.')


class DeepSeekAIClient(AIProviderClient):
    provider_name = 'deepseek'

    def __init__(self, model_name, api_key):
        super().__init__(model_name)
        if not api_key:
            raise RuntimeError('DEEPSEEK_API_KEY environment variable not found.')
        self.api_key = api_key
        self.endpoint = os.getenv('DEEPSEEK_API_URL', 'https://api.deepseek.com/chat/completions').strip()

    def generate_content(self, prompt):
        response = requests.post(
            self.endpoint,
            headers={
                'Authorization': f'Bearer {self.api_key}'
            },
            json={
                'model': self.model_name,
                'messages': self._build_messages(prompt),
                'response_format': {
                    'type': 'json_object'
                }
            },
            timeout=self.timeout
        )
        self._handle_http_error(response)
        payload = response.json()
        return _extract_chat_completion_text(payload)


def _build_provider_error(provider_name, response):
    response_body = response.text.strip()
    if len(response_body) > 2000:
        response_body = response_body[:2000] + '...'

    if provider_name == 'openrouter' and 'No endpoints available matching your guardrail restrictions and data policy' in response_body:
        return RuntimeError(
            'openrouter account policy blocked this request. Review privacy/guardrail settings at '
            'https://openrouter.ai/settings/privacy and allow at least one compatible endpoint.'
        )

    return RuntimeError(
        f"{provider_name} API request failed with status {response.status_code}: {response_body or response.reason}"
    )


def _extract_chat_completion_text(payload):
    choices = payload.get('choices') or []
    if not choices:
        raise RuntimeError('AI provider returned no choices.')

    message = choices[0].get('message') or {}
    content = message.get('content')

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'text':
                text_parts.append(part.get('text', ''))
        combined = ''.join(text_parts).strip()
        if combined:
            return combined

    raise RuntimeError('AI provider returned an unsupported message format.')


def _normalize_ai_json_text(response_text):
    normalized = (response_text or '').replace('```json', '').replace('```', '').strip()

    start = normalized.find('{')
    end = normalized.rfind('}')
    if start != -1 and end != -1 and end >= start:
        normalized = normalized[start:end + 1]

    return normalized.strip()


def _strip_invalid_json_literal_suffixes(raw_json):
    cleaned = []
    in_string = False
    escape = False
    literal_buffer = []

    def flush_literal(next_char=None):
        nonlocal literal_buffer
        if not literal_buffer:
            return
        literal = ''.join(literal_buffer)
        valid_literals = {'null', 'true', 'false'}
        if literal in valid_literals or literal.isdigit() or _is_float_literal(literal):
            cleaned.append(literal)
        else:
            for candidate in ('null', 'true', 'false'):
                if literal.startswith(candidate):
                    cleaned.append(candidate)
                    break
            else:
                trimmed = literal.rstrip('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ×•™š')
                cleaned.append(trimmed or literal)
        literal_buffer = []

    for char in raw_json:
        if in_string:
            cleaned.append(char)
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            flush_literal(char)
            in_string = True
            cleaned.append(char)
            continue

        if literal_buffer:
            if char in ',}] \n\r\t':
                flush_literal(char)
                cleaned.append(char)
            else:
                literal_buffer.append(char)
            continue

        if char in 'ntf-0123456789':
            literal_buffer.append(char)
            continue

        cleaned.append(char)

    flush_literal()
    return ''.join(cleaned)


def _is_float_literal(value):
    try:
        float(value)
        return any(separator in value for separator in ('.', 'e', 'E'))
    except ValueError:
        return False


def parse_ai_json_response(response_text):
    normalized = _normalize_ai_json_text(response_text)
    if not normalized:
        raise json.JSONDecodeError('Empty AI response after normalization', response_text or '', 0)

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        repaired = _strip_invalid_json_literal_suffixes(normalized)
        decoder = json.JSONDecoder()
        parsed, end = decoder.raw_decode(repaired)
        trailing = repaired[end:].strip()
        if trailing:
            logger.warning(f'Ignored trailing content after JSON response: {trailing[:200]}')
        return parsed


def _resolve_model_name(provider_name, model_name=None):
    if model_name:
        return model_name

    if provider_name == 'google':
        return DEFAULT_GOOGLE_MODEL
    if provider_name == 'openrouter':
        return DEFAULT_OPENROUTER_MODEL
    if provider_name == 'deepseek':
        return DEFAULT_DEEPSEEK_MODEL

    raise RuntimeError(f"Unsupported AI provider: {provider_name}")


def get_ai_client(provider_name=None, model_name=None):
    provider_name = (provider_name or DEFAULT_AI_PROVIDER).strip().lower()
    resolved_model_name = _resolve_model_name(provider_name, model_name)
    cache_key = f'{provider_name}:{resolved_model_name}'

    if cache_key in _AI_CLIENT_CACHE:
        return _AI_CLIENT_CACHE[cache_key]

    logger.info(f"Initializing AI client for provider '{provider_name}' with model '{resolved_model_name}'")

    if provider_name == 'google':
        client = GoogleAIClient(resolved_model_name, os.getenv('AISTUDIO_APIKEY'))
    elif provider_name == 'openrouter':
        client = OpenRouterAIClient(resolved_model_name, os.getenv('OPENROUTER_API_KEY'))
    elif provider_name == 'deepseek':
        client = DeepSeekAIClient(resolved_model_name, os.getenv('DEEPSEEK_API_KEY'))
    else:
        raise RuntimeError(f"Unsupported AI provider: {provider_name}")

    _AI_CLIENT_CACHE[cache_key] = client
    return client


def get_active_ai_settings(provider_name=None, model_name=None):
    provider_name = (provider_name or DEFAULT_AI_PROVIDER).strip().lower()
    resolved_model_name = _resolve_model_name(provider_name, model_name)
    return {
        'provider': provider_name,
        'model': resolved_model_name,
        'source': f'{provider_name}:{resolved_model_name}'
    }


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


def _has_meaningful_text(value):
    if value is None:
        return False
    return bool(str(value).strip())


def has_customer_personalization_input(order):
    if _has_meaningful_text(order.get('message_to_seller')):
        return True

    buyer_username = ((order.get('buyer_info') or {}).get('username') or '').strip()
    for msg in order.get('chat_messages') or []:
        if msg.get('type') == 'bundle_message':
            continue
        if buyer_username and msg.get('from_user_name') != buyer_username:
            continue
        if _has_meaningful_text(msg.get('display_content')) or _has_meaningful_text(msg.get('content')):
            return True

    return False


def build_no_customer_input_result(order):
    return {
        'order_id': str(order['order_id']),
        'shopee_order_sn': order['shopee_order_sn'],
        'status': 'NO_PERSONALIZATION_FOUND',
        'reasoning': 'No buyer message to seller or buyer chat message was available, so AI processing was skipped.',
        'personalized_items': [
            {
                'item_id': str(item['id']),
                'item_description': item.get('descricao', ''),
                'quantity_to_personalize': int(item.get('quantidade', 1) or 1),
                'customization_name': None,
                'name_source_message_id': None,
                'customization_initial': None,
                'initial_source_message_id': None,
            }
            for item in (order.get('items') or [])
        ]
    }


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


def run_model(prompt_payload, provider_name=None, model_name=None):
    """
    Runs the configured AI provider against the assembled prompt.
    """
    prompt = f"{PROMPT_TEMPLATE}\n{prompt_payload}"
    client = get_ai_client(provider_name=provider_name, model_name=model_name)

    try:
        response_text = client.generate_content(prompt)
    except Exception as e:
        logging.error(f"Falha ao processar prompt, error: {e}")
        raise

    return response_text, client.describe()

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


def save_extraction_results(order_data, extraction_result, model_info=None):
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
                    'source': (model_info or {}).get('source', 'unknown'),
                    'provider': (model_info or {}).get('provider'),
                    'model': (model_info or {}).get('model'),
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


def _process_single_order(app, order, processed_count, total_orders, provider_name=None, model_name=None):
    with app.app_context():
        order_sn = order.get('shopee_order_sn') or order.get('numeroLoja')
        model_info = get_active_ai_settings(provider_name=provider_name, model_name=model_name)
        logger.info(
            f"Processing order {processed_count} of {total_orders} (Order SN: {order_sn}, AI: {model_info['source']})"
        )

        chat_context = order.get('chat_messages', [])
        prompt_payload = generate_prompt_payload(order)

        ai_result = None
        ai_response_text = None
        error_message = None
        status = 'success'

        try:
            if not has_customer_personalization_input(order):
                logger.info(f"Skipping AI processing for order {order_sn}: no buyer message to seller or buyer chat content.")
                ai_result = build_no_customer_input_result(order)
                save_success = save_extraction_results(
                    order,
                    ai_result,
                    model_info={
                        'provider': 'system',
                        'model': 'no-ai',
                        'source': 'system:no-ai'
                    }
                )
                if not save_success:
                    status = 'db_error'
                    error_message = 'Failed to save shortcut extraction results.'
                else:
                    status = 'skipped_no_customer_input'
            else:
                response_text, model_info = run_model(
                    prompt_payload,
                    provider_name=provider_name,
                    model_name=model_name
                )
                if response_text:
                    ai_response_text = response_text
                    ai_result = parse_ai_json_response(ai_response_text)

                    if not isinstance(ai_result, dict):
                        raise RuntimeError(f"AI response must be a JSON object, got {type(ai_result).__name__}.")

                    save_success = save_extraction_results(order, ai_result, model_info=model_info)
                    if not save_success:
                        status = 'db_error'
                        error_message = 'Failed to save extraction results.'
                else:
                    status = 'no_response'
                    error_message = 'No response from AI model.'
        except json.JSONDecodeError as e:
            status = 'invalid_json'
            error_message = f'Failed to decode AI response as JSON: {e}'
            logger.error(f"Error processing order {order_sn}: {error_message}", exc_info=True)
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
                extracted_personalization=ai_result.get('personalized_items') if isinstance(ai_result, dict) else None,
                model_result=ai_result,
                status=status,
                error_message=error_message
            )
        return status


def process_orders(limit=None, order_sn=None):
    """Main function to process orders and extract personalizations."""
    try:
        ai_settings = get_active_ai_settings()
        logger.info(f"Starting order processing with AI provider '{ai_settings['source']}'")
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
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Create a future for each order
            futures = {
                executor.submit(
                    _process_single_order,
                    app,
                    order,
                    i + 1,
                    total_orders,
                    ai_settings['provider'],
                    ai_settings['model']
                ): order
                for i, order in enumerate(orders)
            }

            for future in as_completed(futures):
                order = futures[future]
                try:
                    # Get the result of the future
                    status = future.result()
                    if status in ('success', 'skipped_no_customer_input'):
                        processed_count += 1
                except Exception as exc:
                    order_sn_exc = order.get('shopee_order_sn') or order.get('numeroLoja')
                    logger.error(f'Order {order_sn_exc} generated an exception: {exc}')

        logger.info("Order processing completed.")
        return True, f"Successfully processed {processed_count} of {total_orders} orders."

    except Exception as e:
        logger.error(f"Error in process_orders: {str(e)}", exc_info=True)
        return False, str(e)