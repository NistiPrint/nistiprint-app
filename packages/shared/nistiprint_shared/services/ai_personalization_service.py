import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.supabase_ai_log import LogsExecucaoIA
from nistiprint_shared.models.supabase_personalizacao import PersonalizacaoPedido

logger = logging.getLogger(__name__)

# AI Model Initialization
model_name = "gemini-2.5-flash"
client = None
try:
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        from google import genai
        client = genai.Client(api_key=api_key)
        logger.info("Google GenAI model initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize AI model: {e}")

def load_prompt_template():
    env_prompt = os.environ.get("AI_PROMPT_TEMPLATE")
    if env_prompt: return env_prompt
    
    # Simple hardcoded fallback for this refactor to ensure it works
    return """Você é um assistente especialista em extrair dados de personalização de pedidos.
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
"""

PROMPT_TEMPLATE = load_prompt_template()

def _load_pedido_com_itens(pedido_id: int) -> Dict:
    """Carrega dados do pedido, itens e chat para processamento IA."""
    # 1. Dados básicos do pedido
    res = supabase_db.table('pedidos').select('*, pedidos_bling(bling_id, numero_loja, numero, raw_payload)').eq('id', pedido_id).single().execute()
    if not res.data:
        raise ValueError(f"Pedido {pedido_id} não encontrado")
    
    pedido = res.data
    shopee_order_sn = pedido.get('pedidos_bling', {}).get('numero_loja')
    
    # 2. Itens do pedido
    res_itens = supabase_db.table('view_vendas_personalizadas_v3').select('itens').eq('id', pedido_id).maybe_single().execute()
    itens = res_itens.data.get('itens', []) if res_itens.data else []
    
    # 3. Chat (se houver Shopee SN)
    chat_messages = []
    if shopee_order_sn:
        # Busca username do comprador primeiro (ou tenta via view)
        res_view = supabase_db.table('view_vendas_personalizadas_v3').select('buyer_username').eq('id', pedido_id).maybe_single().execute()
        username = res_view.data.get('buyer_username') if res_view.data else None
        
        if username:
            res_chat = supabase_db.table('view_mensagens_chat')\
                .select('*')\
                .or_(f"from_user_name.eq.{username},to_user_name.eq.{username}")\
                .order('created_at', desc=False)\
                .limit(50).execute()
            chat_messages = res_chat.data if res_chat.data else []

    return {
        'order_id': pedido_id,
        'bling_id': pedido.get('pedidos_bling', {}).get('bling_id'),
        'shopee_order_sn': shopee_order_sn,
        'bling_number': pedido.get('pedidos_bling', {}).get('numero'),
        'items': itens,
        'chat_messages': chat_messages,
        'message_to_seller': pedido.get('pedidos_bling', {}).get('raw_payload', {}).get('observacoes', '')
    }

def _run_ia_for_order(pedido: Dict) -> Dict:
    """Gera o prompt e chama o modelo Gemini."""
    if not client:
        raise RuntimeError("AI model client not initialized")

    # Monta payload do prompt
    prompt_payload = f">>> ORDER DATA\nID: {pedido['order_id']}\nSN: {pedido['shopee_order_sn']}\n"
    prompt_payload += "\n>>> ITEMS:\n"
    for item in (pedido.get('items') or []):
        prompt_payload += f"- {item.get('quantidade')}x {item.get('descricao')}\n"
    
    prompt_payload += f"\n>>> MESSAGE TO SELLER:\n{pedido['message_to_seller']}\n"
    prompt_payload += "\n>>> CHAT MESSAGES:\n"
    for msg in (pedido.get('chat_messages') or []):
        prompt_payload += f"[{msg.get('created_at')}] {msg.get('from_user_name')}: {msg.get('display_content')}\n"

    prompt = f"{PROMPT_TEMPLATE}\n{prompt_payload}"
    
    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    
    if not response or not response.text:
        raise ValueError("Empty response from AI")
        
    text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

def _persistir_personalizacao(pedido: Dict, resultado: Dict):
    """Salva os resultados da extração no banco."""
    shopee_order_sn = str(pedido['shopee_order_sn'])
    
    # 1. Limpa anteriores
    supabase_db.table('personalizacoes_pedido').delete().eq('shopee_order_sn', shopee_order_sn).execute()
    
    # 2. Insere novos
    items_to_save = []
    for item in resultado.get('personalized_items', []):
        items_to_save.append({
            'shopee_order_sn': shopee_order_sn,
            'codigo_pedido': shopee_order_sn,
            'bling_id': str(pedido.get('bling_id') or ''),
            'status': resultado.get('status', 'success'),
            'reasoning': resultado.get('reasoning'),
            'item_id': str(item.get('item_id') or ''),
            'item_description': item.get('item_description', '')[:1000],
            'customization_name': item.get('customization_name'),
            'customization_initial': item.get('customization_initial'),
            'metadata': {
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'quantity': item.get('quantity_to_personalize', 1),
                'msg_id': item.get('name_source_message_id')
            },
            'updated_at': datetime.now(timezone.utc).isoformat()
        })
    
    if items_to_save:
        supabase_db.table('personalizacoes_pedido').insert(items_to_save).execute()

    # 3. Log de execução
    supabase_db.table('logs_execucao_ia').insert({
        'order_sn': shopee_order_sn,
        'executed_at': datetime.now(timezone.utc).isoformat(),
        'model_result': resultado,
        'status': resultado.get('status', 'success')
    }).execute()

@shared_task(name='services.ai_personalization.processar_batch', bind=True, max_retries=0)
def processar_batch_ia(self, batch_id: str):
    """Orquestrador: cria uma task-filha por pedido."""
    batch_res = supabase_db.table('execucoes_ai_batch').select('*').eq('id', batch_id).single().execute()
    if not batch_res.data: return
    
    supabase_db.table('execucoes_ai_batch').update({'status': 'RODANDO'}).eq('id', batch_id).execute()
    
    for pid in batch_res.data['pedido_ids']:
        processar_pedido_ia.apply_async(
            args=[batch_id, pid],
            queue='ai_personalization',
        )

@shared_task(name='services.ai_personalization.processar_pedido',
             bind=True, max_retries=2, default_retry_delay=30, acks_late=True)
def processar_pedido_ia(self, batch_id: str, pedido_id: int):
    """Task isolada por pedido."""
    t0 = time.monotonic()
    status, erro = 'OK', None
    resultado_ia = None
    
    try:
        pedido = _load_pedido_com_itens(pedido_id)
        resultado_ia = _run_ia_for_order(pedido)
        _persistir_personalizacao(pedido, resultado_ia)
    except httpx.PoolTimeout as e:
        raise self.retry(exc=e)
    except Exception as e:
        status, erro = 'ERRO', str(e)[:500]
        logger.error(f"Erro no pedido {pedido_id}: {e}")
    finally:
        # Registra item individual
        supabase_db.table('execucoes_ai_item').insert({
            'batch_id': batch_id,
            'pedido_id': pedido_id,
            'status': status,
            'erro': erro,
            'duracao_ms': int((time.monotonic() - t0) * 1000),
        }).execute()
        
        # Incrementa contador atômico no batch
        supabase_db.rpc('incrementar_batch_ia', {
            'p_batch_id': batch_id,
            'p_sucesso': 1 if status == 'OK' else 0,
            'p_falha':   1 if status == 'ERRO' else 0,
        }).execute()

def get_logs_by_order_sn(order_sn):
    """Recupera logs para UI."""
    res = supabase_db.table('logs_execucao_ia').select('*').eq('order_sn', order_sn).order('executed_at', desc=True).execute()
    return res.data if res.data else []

def _listar_pendentes(limit=50):
    """Helper para listar pedidos que precisam de IA."""
    # Implementação simplificada: pedidos Shopee sem personalização salva
    res = supabase_db.rpc('get_pedidos_pendentes_ia', {'p_limit': limit}).execute()
    return [r['id'] for r in res.data] if res.data else []
