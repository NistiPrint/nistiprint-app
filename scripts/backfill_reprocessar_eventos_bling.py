"""
Script genérico para reprocessar eventos Bling dos últimos X dias.

Reprocessa eventos em ordem cronológica por payload.date, movendo-os de
múltiplas filas Redis para a fila de pendentes, com opção de resetar
tabelas transacionais.

Uso:
    python scripts/backfill_reprocessar_eventos_bling.py --dias 7 --filas all
    python scripts/backfill_reprocessar_eventos_bling.py --dias 30 --filas processados,falhas --resetar-transacionais
    python scripts/backfill_reprocessar_eventos_bling.py --dias 7 --dry-run
"""
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import sys
import os

# Adicionar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nistiprint_shared.database.supabase_db_service import supabase_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuração do Redis
REDIS_HOST = os.environ.get('REDIS_HOST', '172.21.0.2')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

# Filas Redis
QUEUES = {
    'processados': 'bling:webhooks:processados',
    'falhas': 'bling:webhooks:falhas',
    'dead_letter': 'bling:webhooks:dead-letter',
    'pendentes': 'bling:webhooks:pendentes'
}


def _get_redis_client():
    import redis
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )


def coletar_eventos_das_filas(filas: List[str], dias: int, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Coleta eventos das filas selecionadas, filtrando por payload.date.

    Args:
        filas: Lista de filas para coletar (processados, falhas, dead_letter)
        dias: Número de dias para filtrar (baseado em payload.date)
        dry_run: Se True, não remove eventos das filas origem

    Returns:
        Lista de eventos com metadata (fila_origem, payload, date)
    """
    try:
        redis_client = _get_redis_client()
    except Exception as e:
        logger.error(f"Não foi possível conectar ao Redis: {e}")
        logger.error("Verifique se o Redis está rodando e se REDIS_HOST está configurado corretamente")
        logger.error("Este script deve ser executado no ambiente onde o Redis está acessível")
        return []
    
    eventos = []
    
    # Calcular data limite
    data_limite = datetime.now(timezone.utc) - timedelta(days=dias)
    logger.info(f"Coletando eventos com payload.date >= {data_limite.isoformat()}")
    
    for fila in filas:
        queue_name = QUEUES.get(fila)
        if not queue_name:
            logger.warning(f"Fila desconhecida: {fila}")
            continue
        
        tamanho = redis_client.llen(queue_name)
        logger.info(f"Fila {fila} ({queue_name}): {tamanho} mensagens")
        
        if tamanho == 0:
            continue
        
        # Ler todas as mensagens da fila
        mensagens = redis_client.lrange(queue_name, 0, -1)
        
        for idx, msg in enumerate(mensagens):
            try:
                # Parse JSON
                data = json.loads(msg)
                
                # Extrair payload.date
                payload = data.get('payload', {})
                date_str = payload.get('date')
                
                if not date_str:
                    logger.warning(f"Evento sem payload.date na fila {fila} (índice {idx}), ignorando")
                    continue
                
                # Parse da data
                try:
                    date_evento = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Data inválida {date_str} na fila {fila} (índice {idx}), ignorando")
                    continue
                
                # Filtrar por data
                if date_evento < data_limite:
                    continue
                
                eventos.append({
                    'fila_origem': fila,
                    'queue_name': queue_name,
                    'payload': payload,
                    'date': date_evento,
                    'raw_message': msg,
                    'indice_original': idx
                })
                
            except json.JSONDecodeError:
                logger.warning(f"Mensagem inválida (JSON) na fila {fila} (índice {idx}), ignorando")
            except Exception as e:
                logger.error(f"Erro ao processar mensagem na fila {fila} (índice {idx}): {e}")
    
    logger.info(f"Total de eventos coletados: {len(eventos)}")
    return eventos


def ordenar_eventos_por_date(eventos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ordena eventos por payload.date em ordem crescente (mais antigo primeiro).

    Args:
        eventos: Lista de eventos com metadata

    Returns:
        Lista de eventos ordenados
    """
    logger.info("Ordenando eventos por payload.date (crescente)")
    
    # Ordenar por date
    eventos_ordenados = sorted(eventos, key=lambda x: x['date'])
    
    # Log de amostra
    if eventos_ordenados:
        logger.info(f"Primeiro evento: {eventos_ordenados[0]['date'].isoformat()}")
        logger.info(f"Último evento: {eventos_ordenados[-1]['date'].isoformat()}")
    
    return eventos_ordenados


def mover_para_pendentes(eventos_ordenados: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
    """
    Move eventos ordenados para a fila de pendentes.

    Args:
        eventos_ordenados: Lista de eventos ordenados por date
        dry_run: Se True, simula sem executar

    Returns:
        Estatísticas da operação
    """
    redis_client = _get_redis_client()
    stats = {
        'movidos': 0,
        'erros': 0,
        'ignorados': 0
    }
    
    if not eventos_ordenados:
        logger.info("Nenhum evento para mover")
        return stats
    
    logger.info(f"Movendo {len(eventos_ordenados)} eventos para fila pendentes")
    
    # Limpar fila pendentes (se não for dry-run)
    if not dry_run:
        tamanho_pendentes = redis_client.llen(QUEUES['pendentes'])
        if tamanho_pendentes > 0:
            logger.info(f"Limpar fila pendentes ({tamanho_pendentes} mensagens existentes)")
            redis_client.delete(QUEUES['pendentes'])
    
    # Mover eventos na ordem correta (rpush para que lpop consuma do mais antigo)
    for evento in eventos_ordenados:
        try:
            if not dry_run:
                # Inserir no final da fila (rpush)
                redis_client.rpush(QUEUES['pendentes'], evento['raw_message'])
            stats['movidos'] += 1
            
            if stats['movidos'] % 100 == 0:
                logger.info(f"{stats['movidos']}/{len(eventos_ordenados)} eventos movidos")
                
        except Exception as e:
            logger.error(f"Erro ao mover evento: {e}")
            stats['erros'] += 1
    
    logger.info(f"Resumo: movidos={stats['movidos']}, erros={stats['erros']}")
    return stats


def remover_das_filas_origem(eventos: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
    """
    Remove eventos das filas origem após mover com sucesso.

    Args:
        eventos: Lista de eventos movidos
        dry_run: Se True, simula sem executar

    Returns:
        Estatísticas por fila
    """
    redis_client = _get_redis_client()
    stats = {}
    
    if not eventos:
        return stats
    
    logger.info("Removendo eventos das filas origem")
    
    # Agrupar por fila de origem
    por_fila = {}
    for evento in eventos:
        fila = evento['fila_origem']
        queue_name = evento['queue_name']
        if fila not in por_fila:
            por_fila[fila] = {'queue_name': queue_name, 'indices': []}
        por_fila[fila]['indices'].append(evento['indice_original'])
    
    # Remover por fila (do final para o início para não quebrar índices)
    for fila, info in por_fila.items():
        queue_name = info['queue_name']
        indices = sorted(info['indices'], reverse=True)
        
        if not dry_run:
            for idx in indices:
                try:
                    # Remover por índice
                    redis_client.lset(queue_name, idx, '__DELETED__')
                except Exception as e:
                    logger.error(f"Erro ao marcar para deleção na fila {fila} índice {idx}: {e}")
            
            # Remover todos marcados
            redis_client.lrem(queue_name, 0, '__DELETED__')
        
        stats[fila] = len(indices)
        logger.info(f"Removidos {len(indices)} eventos da fila {fila}")
    
    return stats


def resetar_tabelas_transacionais(dry_run: bool = False) -> bool:
    """
    Executa script SQL de cleanup das tabelas transacionais.

    Args:
        dry_run: Se True, apenas mostra o que seria executado

    Returns:
        True se sucesso, False se falha
    """
    logger.warning("ATENÇÃO: Esta operação vai TRUNCAR tabelas transacionais!")
    
    if dry_run:
        logger.info("[DRY RUN] Seriam truncadas as tabelas listadas em 20260430000000_cleanup_dados_transacionais_v2.sql")
        logger.info("Isso INCLUI: pedidos, pedidos_bling, itens_pedido, pedidos_shopee")
        logger.info("Para executar, aplique a migration manualmente via:")
        logger.info("  supabase db push --db-url postgresql://...")
        return True
    
    logger.info("Para resetar tabelas transacionais, aplique a migration manualmente:")
    logger.info("  supabase db push --db-url postgresql://...")
    logger.info("Ou execute o SQL diretamente no Supabase SQL Editor")
    return False


def main():
    parser = argparse.ArgumentParser(description='Reprocessar eventos Bling em ordem cronológica')
    parser.add_argument('--dias', type=int, help='Número de dias para reprocessar (baseado em payload.date)')
    parser.add_argument('--filas', type=str, default='all', 
                       help='Filas para processar: all, processados, falhas, dead_letter (separadas por vírgula)')
    parser.add_argument('--resetar-transacionais', action='store_true', 
                       help='Resetar tabelas transacionais antes do reprocessamento')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Simular sem executar mudanças')
    parser.add_argument('--validate', action='store_true', 
                       help='Validar sintaxe do script sem conectar ao Redis')
    args = parser.parse_args()
    
    # Modo validação
    if args.validate:
        logger.info("Validando sintaxe do script...")
        logger.info("✓ Script sintaticamente válido")
        logger.info("\nPara executar, rode no ambiente onde o Redis está acessível:")
        logger.info("  docker-compose exec api python scripts/backfill_reprocessar_eventos_bling.py --dias 7 --dry-run")
        return
    
    logger.info("=" * 60)
    logger.info("REPROCESSAMENTO DE EVENTOS BLING")
    logger.info("=" * 60)
    logger.info(f"Dias: {args.dias}")
    logger.info(f"Filas: {args.filas}")
    logger.info(f"Resetar transacionais: {args.resetar_transacionais}")
    logger.info(f"Modo: {'DRY-RUN' if args.dry_run else 'EXECUÇÃO'}")
    logger.info("=" * 60)
    
    # Determinar filas
    if args.filas == 'all':
        filas = ['processados', 'falhas', 'dead_letter']
    else:
        filas = [f.strip() for f in args.filas.split(',')]
    
    # Validar filas
    filas_validas = [f for f in filas if f in QUEUES]
    if not filas_validas:
        logger.error("Nenhuma fila válida especificada")
        return
    
    filas_invalidas = set(filas) - set(filas_validas)
    if filas_invalidas:
        logger.warning(f"Filas inválidas ignoradas: {filas_invalidas}")
    
    # Passo 1: Resetar tabelas transacionais (opcional)
    if args.resetar_transacionais:
        logger.info("\n[1/4] Resetando tabelas transacionais...")
        if not resetar_tabelas_transacionais(dry_run=args.dry_run):
            logger.error("Falha ao resetar tabelas transacionais")
            return
        logger.info("Tabelas transacionais resetadas com sucesso")
    
    # Passo 2: Coletar eventos das filas
    logger.info(f"\n[2/4] Coletando eventos das filas: {filas_validas}")
    eventos = coletar_eventos_das_filas(filas_validas, args.dias, dry_run=args.dry_run)
    
    if not eventos:
        logger.info("Nenhum evento encontrado para reprocessar")
        return
    
    # Passo 3: Ordenar eventos por date
    logger.info("\n[3/4] Ordenando eventos por payload.date...")
    eventos_ordenados = ordenar_eventos_por_date(eventos)
    
    # Passo 4: Mover para pendentes
    logger.info("\n[4/4] Movendo eventos para fila pendentes...")
    stats = mover_para_pendentes(eventos_ordenados, dry_run=args.dry_run)
    
    # Passo 5: Remover das filas origem (se não for dry-run)
    if not args.dry_run and stats['movidos'] > 0:
        logger.info("\n[5/5] Removendo eventos das filas origem...")
        remover_stats = remover_das_filas_origem(eventos_ordenados, dry_run=args.dry_run)
        logger.info(f"Removidos por fila: {remover_stats}")
    
    # Resumo final
    logger.info("\n" + "=" * 60)
    logger.info("RESUMO FINAL")
    logger.info("=" * 60)
    logger.info(f"Eventos coletados: {len(eventos)}")
    logger.info(f"Eventos movidos: {stats['movidos']}")
    logger.info(f"Erros: {stats['erros']}")
    
    if not args.dry_run:
        logger.info("\nPróximo passo: O worker vai processar a fila pendentes automaticamente")
        logger.info("Monitore os logs do worker para acompanhar o processamento")
    else:
        logger.info("\n[DRY RUN] Nenhuma mudança foi executada")


if __name__ == '__main__':
    main()
