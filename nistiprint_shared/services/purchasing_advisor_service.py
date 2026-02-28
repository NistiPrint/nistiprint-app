from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.consumption_service import consumption_service
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

class PurchasingAdvisorService:
    """
    Serviço que gera recomendações de compra de insumos
    baseado no consumo, estoque atual e dados de fornecedores.
    """

    def __init__(self):
        self.estoque_atual_table = supabase_db.table('estoque_atual')
        self.fornecedor_insumos_table = supabase_db.table('fornecedor_insumos')
        self.produtos_table = supabase_db.table('produtos')

    def generate_purchase_recommendations(self, days_of_consumption_history: int = 30) -> List[Dict[str, Any]]:
        """
        Gera uma lista de recomendações de compra para insumos.
        """
        recommendations = []
        
        # 1. Obter o consumo médio diário de todos os insumos
        daily_consumptions = consumption_service.get_daily_consumption(days=days_of_consumption_history)

        # 2. Obter todos os produtos que são insumos (com estoque_seguranca_dias > 0 ou que aparecem no BOM)
        # Mais robusto seria identificar insumos através de sua categoria ou por fazerem parte de um BOM
        # Por simplicidade, vamos considerar produtos que possuem entrada em fornecedor_insumos ou estoque_seguranca_dias configurado
        
        # Fetch all products with relevant fields for ROP calculation
        all_products_response = self.produtos_table.select("id, nome, estoque_seguranca_dias, lote_economico")\
            .or_('estoque_seguranca_dias.gt.0', 'id.in.({})'.format(list(daily_consumptions.keys())))\
            .execute()
        
        insumos = {p['id']: p for p in all_products_response.data}
        
        # 3. Iterar sobre os insumos e calcular ROP
        for produto_id, product_data in insumos.items():
            produto_nome = product_data.get('nome', 'N/A')
            
            # Obter consumo médio diário para este produto
            consumption_data = daily_consumptions.get(produto_id)
            media_diaria = consumption_data['media_diaria'] if consumption_data else 0.0

            if media_diaria == 0:
                # Se não há consumo registrado, mas o produto tem estoque de segurança, podemos pular a recomendação
                # ou criar uma regra específica (ex: verificar estoque_minimo)
                continue 

            # Obter estoque atual
            estoque_response = self.estoque_atual_table.select("saldo_atual")\
                .eq('produto_id', produto_id).limit(1).single().execute()
            saldo_atual = estoque_response.data['saldo_atual'] if estoque_response.data else 0

            # Obter dados do fornecedor (lead time, MOQ)
            fornecedor_insumo_response = self.fornecedor_insumos_table.select("*")\
                .eq('produto_id', produto_id).order('preferencial', ascending=False).limit(1).execute()
            
            fornecedor_insumo_data = fornecedor_insumo_response.data[0] if fornecedor_insumo_response.data else None

            if not fornecedor_insumo_data:
                # Não é possível recomendar compra sem dados do fornecedor
                continue

            lead_time_dias = fornecedor_insumo_data.get('lead_time_dias', 0)
            moq = fornecedor_insumo_data.get('moq', 0)
            fornecedor_nome = fornecedor_insumo_data.get('fornecedor_nome', 'N/A') # Requires join or separate fetch

            # Obter estoque de segurança em dias do produto
            estoque_seguranca_dias = product_data.get('estoque_seguranca_dias', 0)

            # Cálculo do ROP (Reorder Point)
            # ROP = (CME * Lead Time) + (CME * Estoque de Segurança em Dias)
            # estoque_necessario_para_lead_time = media_diaria * lead_time_dias
            # estoque_para_seguranca = media_diaria * estoque_seguranca_dias
            # rop = estoque_necessario_para_lead_time + estoque_para_seguranca
            rop = (media_diaria * lead_time_dias) + (media_diaria * estoque_seguranca_dias)
            
            # Verificar se o estoque atual está abaixo do ROP
            if saldo_atual <= rop:
                quantidade_sugerida = rop - saldo_atual
                
                # Arredondar para o próximo MOQ se for o caso
                if moq > 0 and quantidade_sugerida % moq != 0:
                    quantidade_sugerida = (quantidade_sugerida // moq + 1) * moq
                elif product_data.get('lote_economico', 0) > 0:
                    quantidade_sugerida = max(quantidade_sugerida, product_data['lote_economico'])
                
                # Garantir que a quantidade sugerida seja positiva
                quantidade_sugerida = max(quantidade_sugerida, moq if moq > 0 else 1) # Comprar pelo menos 1 ou MOQ

                data_esgotamento_estimada = (datetime.utcnow() + timedelta(days=saldo_atual / media_diaria)).strftime('%Y-%m-%d') if media_diaria > 0 else 'N/A'
                
                recommendations.append({
                    'produto_id': produto_id,
                    'produto_nome': produto_nome,
                    'fornecedor_id': fornecedor_insumo_data['fornecedor_id'],
                    'fornecedor_nome': fornecedor_insumo_data.get('nome', 'N/A'), # Placeholder, will need to fetch from Fornecedor table
                    'saldo_atual': saldo_atual,
                    'media_diaria_consumo': round(media_diaria, 2),
                    'lead_time_dias': lead_time_dias,
                    'estoque_seguranca_dias_config': estoque_seguranca_dias,
                    'rop_calculado': round(rop, 2),
                    'quantidade_sugerida': round(quantidade_sugerida, 2),
                    'justificativa': f"Estoque ({saldo_atual}) abaixo do Ponto de Ressuprimento ({round(rop, 2)}). "
                                     f"Consumo diário médio: {round(media_diaria, 2)} unid/dia. "
                                     f"Prazo de entrega ({fornecedor_nome}): {lead_time_dias} dias. "
                                     f"Estoque de segurança configurado: {estoque_seguranca_dias} dias. "
                                     f"Estoque atual deve durar até aproximadamente {data_esgotamento_estimada}.",
                    'data_limite_pedido': (datetime.utcnow() + timedelta(days=lead_time_dias - (saldo_atual / media_diaria))).strftime('%Y-%m-%d') # Aproximado
                })
        
        return recommendations

purchasing_advisor_service = PurchasingAdvisorService()

