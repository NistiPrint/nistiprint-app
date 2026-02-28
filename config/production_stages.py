"""
Módulo responsável por definir o mapeamento entre os campos do dashboard de produção
e as regras de negócio relacionadas à movimentação de estoque de componentes.
"""

ESTAGIOS_PRODUCAO = {
    'capas_impressas_qtd': {
        'role_produto_gerado': 'CAPA_IMPRESSAO',
        'descricao': 'Impressão de Capa'
    },
    'capas_produzidas_qtd': {
        'role_produto_gerado': 'CAPA_ACABADA',
        'descricao': 'Produção de Capa Acabada (Laminação/Corte)'
    },
    'miolos_prontos_retirada_qtd': {
        'role_produto_gerado': 'MIOLO',
        'descricao': 'Produção de Miolo'
    },
    # Adicionar aqui outros estágios, como 'Wire-O Aplicado', se necessário
}




