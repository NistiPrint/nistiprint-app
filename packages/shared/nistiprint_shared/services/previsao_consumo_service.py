from typing import List, Dict, Any
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
            # 1. Limpar previsões antigas da demanda para evitar duplicidade em re-cálculos
            supabase_db.table(self.table_name).delete().eq('demanda_id', demanda_id).execute()

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

            # 4. Salvar previsões consolidadas no banco
            if consumo_consolidado:
                payload = []
                for comp_id, dados in consumo_consolidado.items():
                    payload.append({
                        'demanda_id': demanda_id,
                        'produto_id': comp_id,
                        'quantidade_prevista': dados['quantidade'],
                        'unidade': dados['unidade'],
                        'status': 'PLANEJADO'
                    })
                
                supabase_db.table(self.table_name).insert(payload).execute()
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
                pid = p['produto_id']
                previsao_map[pid] = {
                    'produto_id': pid,
                    'nome': p['produtos']['nome'],
                    'sku': p['produtos']['sku'],
                    'previsto': float(p['quantidade_prevista']),
                    'unidade': p['unidade'],
                    'realizado': 0.0
                }

            # 2. Obter Movimentações Reais
            # Busca por documento_referencia (ID da demanda)
            mov_res = supabase_db.table('movimentacoes_estoque')\
                .select('produto_id, quantidade, tipo_movimentacao')\
                .eq('documento_referencia', str(demanda_id))\
                .execute()
            
            all_movements = mov_res.data or []
            
            # Fallback por motivo se não houver doc_ref (compatibilidade)
            if not all_movements:
                mov_res_motivo = supabase_db.table('movimentacoes_estoque')\
                    .select('produto_id, quantidade, tipo_movimentacao')\
                    .ilike('motivo', f'%{demanda_id}%')\
                    .execute()
                all_movements = mov_res_motivo.data or []

            for m in all_movements:
                pid = m['produto_id']
                qty = abs(float(m['quantidade']))
                
                if pid in previsao_map:
                    if m['tipo_movimentacao'] == 'SAIDA':
                        previsao_map[pid]['realizado'] += qty
                    elif m['tipo_movimentacao'] == 'ENTRADA': # Estorno
                        previsao_map[pid]['realizado'] -= qty

            # 3. Formatar Resultado
            report = []
            for pid, data in previsao_map.items():
                data['diferenca'] = data['previsto'] - data['realizado']
                data['status'] = 'OK' if abs(data['diferenca']) < 0.001 else 'DISCREPANCIA'
                report.append(data)

            return {
                'success': True,
                'demanda_id': demanda_id,
                'audit_report': report
            }
        except Exception as e:
            logging.error(f"Erro na auditoria de consumo para demanda {demanda_id}: {e}")
            return {'success': False, 'message': str(e)}

previsao_consumo_service = PrevisaoConsumoService()
