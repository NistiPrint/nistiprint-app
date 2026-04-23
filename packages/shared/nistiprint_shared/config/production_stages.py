"""
Módulo responsável por definir o mapeamento entre os campos do dashboard de produção
e as regras de negócio relacionadas à movimentação de estoque de componentes.
"""

ESTAGIOS_PRODUCAO = {
    'capas_impressas_qtd': {
        'config_key': 'producao_capas_impressas_category_id',
        'descricao': 'Impressão de Capa',
        'depende_de': None,
        'permite_producao_jit': True
    },
    'capas_produzidas_qtd': {
        'config_key': 'producao_capas_category_id',
        'descricao': 'Produção de Capa Acabada (Laminação/Corte)',
        'depende_de': 'capas_impressas_qtd',
        'permite_producao_jit': True
    },
    'capas_prontas_retirada_qtd': {
        'config_key': None,  # Etapa administrativa (usa produto da categoria capa se houver)
        'descricao': 'Capa Pronta para Retirada (Casamento)',
        'depende_de': 'capas_produzidas_qtd',
        'permite_producao_jit': False
    },
    'miolos_prontos_retirada_qtd': {
        'config_key': 'producao_miolos_category_id',
        'descricao': 'Produção de Miolo',
        'depende_de': None,
        'permite_producao_jit': True
    },
    'expedicao_capas_retiradas_qtd': {
        'config_key': None, # Puxa do produto pai/intermediário
        'descricao': 'Retirada de Capas para Montagem',
        'depende_de': 'capas_prontas_retirada_qtd',
        'permite_producao_jit': True
    },
    'expedicao_miolos_retirados_qtd': {
        'config_key': 'producao_miolos_category_id',
        'descricao': 'Retirada de Miolos para Montagem',
        'depende_de': 'miolos_prontos_retirada_qtd',
        'permite_producao_jit': True
    },
    'finalizados_qtd': {
        'config_key': None, # Produto Final (Acabado)
        'descricao': 'Item Finalizado (Liquidação de Estoque)',
        'depende_de': ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd'],
        'permite_producao_jit': True
    }
}
