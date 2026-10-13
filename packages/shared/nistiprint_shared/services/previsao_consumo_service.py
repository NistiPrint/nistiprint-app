from typing import List, Dict, Any
from datetime import datetime, timezone
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bom_service import bom_service
import logging

class PrevisaoConsumoService:
    """Serviço para gerenciar e consolidar a previsão de consumo de materiais para as demandas."""

    def __init__(self):
        self.table_name = 'previsao_consumo_demanda'

    def gerar_previsao_para_demanda(self, demanda_id: str, itens: List[Dict[str, Any]]) -> bool:
        """
        Calcula a explosão total da BOM para todos os itens de uma demanda e salva na tabela de previsão.
        Isso permite saber antecipadamente o que será necessário comprar/produzir.
        """
        try:
            demanda_pk = int(demanda_id)
            if demanda_pk <= 0:
                raise ValueError("demanda_id deve ser um inteiro positivo")
            consumo_consolidado = {}

            # 2. Iterar sobre cada item da demanda
            for item in itens:
                produto_id = item.get('produto_id')
                quantidade = float(item.get('quantidade', 0))
                
                if not produto_id or quantidade <= 0:
                    continue

                # 3. Obter explosão recursiva da BOM para este item
                # O BomService já deve lidar com a hierarquia
                componentes = bom_service.get_full_bom_explosion(produto_id, quantidade)
                
                for comp in componentes:
                    comp_id = comp['componente_id']
                    qtd_comp = float(comp['quantidade_total'])
                    unidade = comp.get('unidade')

                    if comp_id in consumo_consolidado:
                        consumo_consolidado[comp_id]['quantidade'] += qtd_comp
                    else:
                        consumo_consolidado[comp_id] = {
                            'produto_id': comp_id,
                            'quantidade': qtd_comp,
                            'unidade': unidade
                        }

            # Validate the entire replacement before the RPC deletes the old plan.
            payload = [
                {
                    'produto_id': int(comp_id),
                    'quantidade_prevista': dados['quantidade'],
                    'unidade': dados['unidade'],
                }
                for comp_id, dados in sorted(consumo_consolidado.items(), key=lambda entry: int(entry[0]))
            ]
            response = supabase_db.rpc('substituir_previsao_consumo_demanda', {
                'p_demanda_id': demanda_pk, 'p_linhas': payload,
            }).execute()
            result = response.data
            if isinstance(result, list):
                result = result[0] if result else None
            if not isinstance(result, dict) or result.get('status') != 'CONFIRMADO':
                raise RuntimeError(f"Banco não confirmou a substituição da previsão: {result}")
            logging.info(f"Previsão de consumo gerada para demanda {demanda_id} com {len(payload)} insumos.")
            
            return True
        except Exception as e:
            logging.error(f"Erro ao gerar previsão de consumo para demanda {demanda_id}: {e}")
            return False

    def audit_consumption_for_demand(self, demanda_id: Any) -> Dict[str, Any]:
        """
        Compara o consumo previsto vs realizado para uma demanda específica.
        """
        try:
            # 1. Obter Previsão
            previsao_res = supabase_db.table(self.table_name)\
                .select('produto_id, quantidade_prevista, unidade, produtos(nome, sku)')\
                .eq('demanda_id', demanda_id)\
                .execute()
            
            if not previsao_res.data:
                return {'success': False, 'message': 'Nenhuma previsão encontrada para esta demanda.'}

            previsao_map = {}
            for p in previsao_res.data:
                pid = int(p['produto_id'])
                product = p.get('produtos') or {}
                previsao_map[pid] = {
                    'produto_id': pid,
                    'nome': product.get('nome'),
                    'sku': product.get('sku'),
                    'previsto': float(p['quantidade_prevista']),
                    'unidade': p['unidade'],
                    'realizado': 0.0
                }

            # Novos movimentos se relacionam pelo item interno; documento_referencia
            # permanece apenas como leitura de compatibilidade do histórico legado.
            demand_pk = int(demanda_id)
            item_res = (supabase_db.table('itens_demanda').select('id')
                        .eq('demanda_id', demand_pk).execute())
            item_ids = [int(row['id']) for row in (item_res.data or [])]
            movement_fields = (
                'id, produto_id, quantidade, tipo_movimentacao, data_movimentacao, '
                'operation_id, item_demanda_id, documento_referencia, correlation_id'
            )
            movements_by_id = {}
            if item_ids:
                linked = (supabase_db.table('movimentacoes_estoque').select(movement_fields)
                          .in_('item_demanda_id', item_ids).execute())
                movements_by_id.update({str(row['id']): row for row in (linked.data or [])})
            legacy = (supabase_db.table('movimentacoes_estoque').select(movement_fields)
                      .eq('documento_referencia', str(demand_pk)).execute())
            movements_by_id.update({str(row['id']): row for row in (legacy.data or [])})

            consumption_types = {
                'CONS_MP', 'CONS_INT', 'SAIDA_INSUMO_PRODUCAO', 'SAIDA', 'SAIDA_RESERVADA'
            }
            compensation_types = {
                'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP', 'COMPENSACAO_CONS_INT',
                'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT', 'ESTORNO'
            }
            all_movements = list(movements_by_id.values())
            audited_movements = []

            for m in all_movements:
                pid = int(m['produto_id'])
                qty = abs(float(m['quantidade']))
                if pid in previsao_map:
                    movement_type = str(m['tipo_movimentacao'] or '').upper()
                    if movement_type in consumption_types:
                        previsao_map[pid]['realizado'] += qty
                    elif movement_type in compensation_types:
                        previsao_map[pid]['realizado'] -= qty
                    else:
                        continue
                    audited_movements.append(m)
                    previsao_map[pid].setdefault('movimentos', []).append({
                        'movimento_id': m.get('id'),
                        'operation_id': m.get('operation_id'),
                        'correlation_id': m.get('correlation_id'),
                        'item_demanda_id': m.get('item_demanda_id'),
                        'tipo': movement_type,
                        'quantidade': float(m['quantidade']),
                        'data_movimentacao': m.get('data_movimentacao'),
                    })

            # 3. Formatar Resultado
            report = []
            for pid, data in previsao_map.items():
                data['diferenca'] = data['previsto'] - data['realizado']
                data['status'] = 'OK' if abs(data['diferenca']) < 0.001 else 'DISCREPANCIA'
                report.append(data)

            return {
                'success': True,
                'demanda_id': demand_pk,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'period_start': min((m.get('data_movimentacao') for m in audited_movements if m.get('data_movimentacao')), default=None),
                'period_end': max((m.get('data_movimentacao') for m in audited_movements if m.get('data_movimentacao')), default=None),
                'audit_report': report
            }
        except Exception as e:
            logging.error(f"Erro na auditoria de consumo para demanda {demanda_id}: {e}")
            return {'success': False, 'message': str(e)}

previsao_consumo_service = PrevisaoConsumoService()
