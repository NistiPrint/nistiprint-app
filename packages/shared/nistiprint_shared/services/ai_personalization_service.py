import os
import json
import time
import logging
import threading
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
from celery import shared_task
from flask import current_app

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service

# Set up logging
logger = logging.getLogger(__name__)

# AI Model Initialization
model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
client = None
try:
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        from google import genai
        client = genai.Client(api_key=api_key)
        logger.info(f"Google GenAI model ({model_name}) initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize AI model: {e}")

# Global HTTP client with limits (Parte 3.8)
_httpx_client = httpx.Client(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    timeout=httpx.Timeout(30.0, connect=5.0),
)

def load_prompt_template():
    """Carrega o prompt template com prioridade (DB > Env > Fallback)."""
    try:
        db_config = app_config_service.get_config('prompt_template')
        if db_config:
            if isinstance(db_config, dict):
                prompt = db_config.get('text', '')
            else:
                prompt = db_config
            if prompt:
                return prompt
    except Exception as e:
        logger.warning(f"Falha ao carregar prompt do DB: {e}")

    return os.environ.get("AI_PROMPT_TEMPLATE", """Você é um assistente especialista em extrair dados de personalização de pedidos.
Analise os dados do pedido e o histórico do chat abaixo e extraia nomes e iniciais para personalização.
Retorne APENAS um JSON no formato:
{
  "order_id": "...",
  "shopee_order_sn": "...",
  "status": "success",
  "reasoning": "...",
  "personalized_items": [
    {
      "item_id": "...",
      "item_description": "...",
      "customization_name": "...",
      "customization_initial": "...",
      "quantity_to_personalize": 1,
      "name_source_message_id": "..."
    }
  ]
}
""")

PROMPT_TEMPLATE = load_prompt_template()

def _truncate(s, max_len=1000):
    if not s or not isinstance(s, str): return s
    return s[:max_len] + "..." if len(s) > max_len else s

def _truncate_json(data, max_len=5000):
    if not data: return data
    s = json.dumps(data, ensure_ascii=False)
    if len(s) > max_len:
        return s[:max_len] + "... [TRUNCATED]"
    return data

def generate_prompt_payload(order):
    """Gera o payload textual para o prompt da IA."""
    prompt_payload = ">>> ORDER DATA\n"
    prompt_payload += f"  Order ID: {order.get('order_id')}\n"
    prompt_payload += f"  Shopee Order SN: {order.get('shopee_order_sn')}\n"
    prompt_payload += f"  Order Date: {order.get('order_date')}\n"

    prompt_payload += "\n>>> ITEMS:\n"
    for item in (order.get('items') or []):
        prompt_payload += f"- {int(item.get('quantidade', 1))}x {item.get('descricao')}\n"

    prompt_payload += f"\n>>> MESSAGE TO SELLER:\n{order.get('message_to_seller', '')}\n"

    prompt_payload += "\n>>> CHAT MESSAGES:\n"
    for msg in (order.get('chat_messages') or []):
        if msg.get('type') == 'bundle_message': continue
        from_name = msg.get('from_user_name', 'User')
        prompt_payload += f"[{msg.get('created_at')}] {from_name}: {msg.get('display_content', '')}\n"
    
    return prompt_payload

def run_model(prompt_payload):
    """Chama o modelo Generative AI."""
    if not client:
        raise RuntimeError("AI model client not initialized")

    prompt = f"{load_prompt_template()}\n{prompt_payload}"
    
    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    
    if not response or not response.text:
        raise ValueError("Empty response from AI")
        
    text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

def _load_pedido_com_itens(pedido_id: int) -> Dict:
    """Busca dados completos do pedido para a IA."""
    res = supabase_db.table('view_vendas_personalizadas_v3').select('*').eq('id', pedido_id).maybe_single().execute()
    if not res.data:
        # Fallback para busca direta se a view falhar ou não encontrar
        res = supabase_db.table('pedidos').select('*, pedidos_bling(*), pedidos_shopee(*)').eq('id', pedido_id).single().execute()
    
    pedido = res.data
    # Normalizar estrutura esperada pelos helpers
    return {
        'id': pedido['id'],
        'order_id': pedido.get('numero_pedido'),
        'shopee_order_sn': pedido.get('codigo_pedido_externo'),
        'bling_id': pedido.get('pedidos_bling', {}).get('bling_id'),
        'order_date': pedido.get('data_venda'),
        'message_to_seller': pedido.get('pedidos_bling', {}).get('raw_payload', {}).get('observacoes', ''),
        'items': pedido.get('itens_venda', []),
        'chat_messages': pedido.get('chat_messages', []),
        'buyer_info': pedido.get('buyer_info', {})
    }

def _persistir_personalizacao(pedido: Dict, resultado: Dict):
    """Salva os resultados da extração no banco."""
    shopee_order_sn = str(pedido['shopee_order_sn'])
    
    # Limpa extrações anteriores
    supabase_db.table('personalizacoes_pedido').delete().eq('shopee_order_sn', shopee_order_sn).execute()

    personalized_items = resultado.get('personalized_items', [])
    records = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in personalized_items:
        records.append({
            'codigo_pedido': shopee_order_sn,
            'shopee_order_sn': shopee_order_sn,
            'bling_id': str(pedido.get('bling_id', '')),
            'status': resultado.get('status', 'success'),
            'reasoning': _truncate(resultado.get('reasoning'), 1500),
            'item_id': str(item.get('item_id', '')),
            'item_description': item.get('item_description'),
            'customization_name': _truncate(item.get('customization_name'), 500),
            'customization_initial': _truncate(item.get('customization_initial'), 100),
            'name_source_message_id': str(item.get('name_source_message_id', '')) if item.get('name_source_message_id') else None,
            'detalhes_personalizacao': {
                'quantity_to_personalize': item.get('quantity_to_personalize', 1),
                'initial_source_message_id': item.get('initial_source_message_id')
            },
            'metadata': {
                'source': model_name,
                'processed_at': now_iso
            },
            'updated_at': now_iso
        })

    if records:
        supabase_db.table('personalizacoes_pedido').insert(records).execute()

def log_ai_execution(order_sn, input_data, status, result=None, error_message=None):
    """Registra log de execução na tabela logs_execucao_ia."""
    log_record = {
        'order_sn': order_sn,
        'executed_at': datetime.now(timezone.utc).isoformat(),
        'input_data': _truncate(input_data, 25000),
        'model_result': _truncate_json(result, 15000),
        'status': status,
        'error_message': _truncate(error_message, 1000),
    }
    try:
        supabase_db.table('logs_execucao_ia').insert(log_record).execute()
    except Exception as e:
        logger.error(f"Erro ao salvar log de IA para {order_sn}: {e}")

@shared_task(name='services.ai_personalization.processar_batch', bind=True)
def processar_batch_ia(self, batch_id: str):
    """Orquestrador: cria uma task-filha por pedido."""
    batch = supabase_db.table('execucoes_ai_batch').select('*').eq('id', batch_id).single().execute().data
    if not batch: return
    
    supabase_db.table('execucoes_ai_batch').update({'status': 'RODANDO'}).eq('id', batch_id).execute()
    
    for pid in batch['pedido_ids']:
        processar_pedido_ia.apply_async(
            args=[batch_id, pid],
            queue='ai_personalization'
        )

@shared_task(name='services.ai_personalization.processar_pedido', bind=True, max_retries=2)
def processar_pedido_ia(self, batch_id: str, pedido_id: int):
    """Task isolada por pedido."""
    t0 = time.monotonic()
    status, erro = 'OK', None
    order_sn = "unknown"
    resultado = None
    prompt_payload = ""

    try:
        pedido = _load_pedido_com_itens(pedido_id)
        order_sn = pedido['shopee_order_sn']
        prompt_payload = generate_prompt_payload(pedido)
        
        resultado = run_model(prompt_payload)
        _persistir_personalizacao(pedido, resultado)
        
    except httpx.PoolTimeout as e:
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        status, erro = 'ERRO', str(e)
        logger.error(f"Erro processar_pedido_ia {pedido_id}: {e}", exc_info=True)
    finally:
        # Log de item
        supabase_db.table('execucoes_ai_item').insert({
            'batch_id': batch_id,
            'pedido_id': pedido_id,
            'status': status,
            'erro': _truncate(erro, 500),
            'duracao_ms': int((time.monotonic() - t0) * 1000),
        }).execute()
        
        # Log de execução IA (tabela legada/global)
        log_ai_execution(order_sn, prompt_payload, status.lower(), resultado, erro)

        # Incremento atômico no batch
        supabase_db.rpc('incrementar_batch_ia', {
            'p_batch_id': batch_id,
            'p_sucesso': 1 if status == 'OK' else 0,
            'p_falha': 1 if status == 'ERRO' else 0,
        }).execute()

def _listar_pendentes(limit=50):
    """Lista IDs de pedidos que precisam de processamento IA."""
    res = supabase_db.rpc('get_pedidos_pendentes_ia', {'p_limit': limit}).execute()
    return [r['id'] for r in res.data] if res.data else []

def process_orders(limit=None, order_sn=None):
    """Mantido para compatibilidade síncrona, mas agora chama o fluxo de batch se houver muitos."""
    # Se for apenas um, processa direto (reusando lógica da task)
    if order_sn:
        res = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', order_sn).maybe_single().execute()
        if res.data:
            pedido_id = res.data['id']
            try:
                pedido = _load_pedido_com_itens(pedido_id)
                prompt = generate_prompt_payload(pedido)
                resultado = run_model(prompt)
                _persistir_personalizacao(pedido, resultado)
                log_ai_execution(order_sn, prompt, 'success', resultado)
                return True, "Pedido processado com sucesso."
            except Exception as e:
                log_ai_execution(order_sn, "", 'error', error_message=str(e))
                return False, str(e)
    
    # Se for lote, usa o sistema de batch (async)
    ids = _listar_pendentes(limit or 50)
    if not ids:
        return True, "Nada a processar."
    
    batch_res = supabase_db.table('execucoes_ai_batch').insert({
        'pedido_ids': ids,
        'total': len(ids),
        'status': 'PENDENTE'
    }).execute()
    
    if batch_res.data:
        processar_batch_ia.delay(batch_res.data[0]['id'])
        return True, f"Lote de {len(ids)} pedidos agendado (Batch ID: {batch_res.data[0]['id']})"
    
    return False, "Falha ao agendar lote."

def get_logs_by_order_sn(order_sn):
    """Busca logs de execução para um pedido."""
    res = supabase_db.table('logs_execucao_ia').select('*').eq('order_sn', order_sn).order('executed_at', desc=True).execute()
    return res.data or []

def get_orders_with_chats(order_sn=None, limit=None):
    """Busca pedidos que precisam de IA via View."""
    query = supabase_db.table('view_vendas_personalizadas_v3').select('*')
    if order_sn:
        query = query.eq('codigo_pedido_externo', order_sn)
    if limit:
        query = query.limit(limit)
    res = query.execute()
    return res.data or []
