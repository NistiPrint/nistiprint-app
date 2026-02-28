import logging
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("AttributeService")

class AttributeService:
    """
    Serviço para gerenciar definições de atributos e valores de variações.
    Implementa a Task 4.1 do PRD V3.
    """

    def __init__(self):
        self.attr_table = supabase_db.table('atributos_variacao')
        self.val_table = supabase_db.table('valores_variacao')
        self.prod_val_table = supabase_db.table('produto_valores_variacao')

    def get_or_create_attribute(self, name: str) -> str:
        """Busca ou cria uma definição de atributo (ex: 'Cor')."""
        name = name.strip().capitalize()
        res = self.attr_table.select("id").eq('nome', name).execute()
        if res.data:
            return res.data[0]['id']
        
        res = self.attr_table.insert({'nome': name}).execute()
        return res.data[0]['id']

    def get_or_create_value(self, attribute_id: str, value: str) -> str:
        """Busca ou cria um valor para um atributo (ex: 'Azul' para o atributo 'Cor')."""
        value = value.strip()
        res = self.val_table.select("id").eq('atributo_id', attribute_id).eq('valor', value).execute()
        if res.data:
            return res.data[0]['id']
        
        res = self.val_table.insert({'atributo_id': attribute_id, 'valor': value}).execute()
        return res.data[0]['id']

    def link_product_to_attribute_value(self, product_id: int, value_id: str):
        """Associa um produto (variação) a um valor de atributo específico."""
        self.prod_val_table.upsert({
            'produto_id': product_id,
            'valor_id': value_id
        }, on_conflict='produto_id,valor_id').execute()

    def get_product_attributes(self, product_id: int) -> List[Dict[str, Any]]:
        """Retorna todos os atributos e valores vinculados a um produto."""
        res = self.prod_val_table.select("""
            valor_id,
            valores_variacao (
                valor,
                atributos_variacao (nome)
            )
        """).eq('produto_id', product_id).execute()
        
        formatted = []
        for item in res.data:
            val_data = item.get('valores_variacao', {})
            attr_data = val_data.get('atributos_variacao', {})
            formatted.append({
                'atributo': attr_data.get('nome'),
                'valor': val_data.get('valor'),
                'valor_id': item.get('valor_id')
            })
        return formatted

attribute_service = AttributeService()

