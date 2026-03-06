"""
Módulo responsável por definir o mapeamento entre os campos do dashboard de produção
e as regras de negócio relacionadas à movimentação de estoque de componentes.
"""

ESTAGIOS_PRODUCAO = {
    'capas_impressas_qtd': {
        'role_produto_gerado': 'CAPA_IMPRESSAO',
        'descricao': 'Impressão de Capa',
        'depende_de': None,
        'permite_producao_jit': True  # Pode produzir se não houver estoque
    },
    'capas_produzidas_qtd': {
        'role_produto_gerado': 'CAPA_ACABADA',
        'descricao': 'Produção de Capa Acabada (Laminação/Corte)',
        'depende_de': 'capas_impressas_qtd',
        'permite_producao_jit': True  # Pode produzir se não houver estoque
    },
    'capas_prontas_retirada_qtd': {
        'role_produto_gerado': None,  # Etapa administrativa
        'descricao': 'Capa Pronta para Retirada (Casamento)',
        'depende_de': 'capas_produzidas_qtd',
        'permite_producao_jit': False  # Apenas alocação/casamento
    },
    'miolos_prontos_retirada_qtd': {
        'role_produto_gerado': 'MIOLO',
        'descricao': 'Produção de Miolo',
        'depende_de': None,
        'permite_producao_jit': True  # Modificado para True para permitir produção JIT
    },
}
