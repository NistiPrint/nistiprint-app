from nistiprint_shared.database.supabase_db_service import supabase_db
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

class ConsumptionService:
    """
    Serviço especializado em calcular o consumo real de insumos
    com base na produção executada e nas Fichas Técnicas (BOM).
    """

    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_demanda_table = supabase_db.table('itens_demanda')
        self.bom_table = supabase_db.table('ficha_tecnica')

    def get_daily_consumption(self, days: int = 30) -> Dict[int, Dict[str, Any]]:
        """
        Calcula o consumo médio diário de cada insumo nos últimos 'days' dias.
        Retorna um dicionário mapeando produto_id -> {media_diaria, total_periodo, nome_insumo}
        """
        start_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # 1. Buscar demandas concluídas no período
        # Nota: Idealmente filtraríamos por data_conclusao, mas usaremos created_at se necessário
        response = self.demandas_table.select("id, quantidade")\
            .eq('status', 'CONCLUIDO')\
            .gte('updated_at', start_date).execute()
        
        demanda_ids = [d['id'] for d in response.data]
        if not demanda_ids:
            return {}

        # 2. Buscar itens dessas demandas
        itens_response = self.itens_demanda_table.select("produto_id, quantidade")\
            .in_('demanda_id', demanda_ids).execute()
        
        # 3. "Explodir" a BOM para cada item produzido
        consumo_total = {} # component_id -> total_quantity
        
        for item in itens_response.data:
            product_id = item['produto_id']
            qtd_produzida = item['quantidade']
            
            if not product_id: continue
            
            # Buscar componentes da BOM para este produto
            bom_response = self.bom_table.select("componente_id, quantidade_necessaria")\
                .eq('produto_pai_id', product_id).execute()
            
            for bom_item in bom_response.data:
                comp_id = bom_item['componente_id']
                qtd_necessaria = bom_item['quantidade_necessaria']
                
                consumo_item = qtd_produzida * qtd_necessaria
                consumo_total[comp_id] = consumo_total.get(comp_id, 0) + consumo_item

        # 4. Calcular médias
        resultado = {}
        for comp_id, total in consumo_total.items():
            resultado[comp_id] = {
                'total_periodo': total,
                'media_diaria': total / days,
                'periodo_dias': days
            }
            
        return resultado

consumption_service = ConsumptionService()

