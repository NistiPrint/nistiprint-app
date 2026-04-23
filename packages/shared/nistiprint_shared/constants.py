# Constants for column names
COLUMNS = {
    "mercadolivre": ['N.º de venda', 'Estado', 'Unidades', 'SKU', 'Título do anúncio', 'Variação', 'Forma de entrega'],
    # "amazon": ['Customer Order ID', 'Shipment ID','MSKU', 'Title', 'Units', 'Status', 'ExSD'],
    "amazon": ['ID do pedido do cliente', 'ID da remessa', 'SKU', 'Título', 'Unidades', 'Status', 'Data prevista para envio'],
    "shopee": ['ID do pedido', 'Status do pedido', 'Opção de envio', 'Data prevista de envio', 'Número de referência SKU', 'Nome do Produto', 'Nome da variação', 'Quantidade', 'Nome de usuário (comprador)', 'Observação do comprador'],
    "shein": ['Número do pedido', 'SKU do vendedor', 'Nome do produto', 'Status do pedido', 'Prazo final de impressão de etiqueta', 'Data e hora requeridas para coleta']
}

COLUMN_SHIP_DATE = {
    "mercadolivre": "",
    # "amazon": "ExSD",
    "amazon": "Data prevista para envio",
    "shopee": "Data prevista de envio",
    "shein": ["Prazo final de impressão de etiqueta", "Prazo para imprimir etiqueta", "Data e hora requeridas para coleta"]
}

CAPAS_GROUP = {
    "mercadolivre": ['Título do anúncio', 'SKU', 'Variação'],
    "amazon": ['Título', 'SKU'],
    "shopee": ['Nome do Produto', 'Número de referência SKU', 'Nome da variação'],
    "shein": ['Nome do produto', 'SKU do vendedor']
}

# Create the month name mapping
MONTH_MAP = {
    'janeiro': 'January',
    'fevereiro': 'February',
    'março': 'March',
    'abril': 'April',
    'maio': 'May',
    'junho': 'June',
    'julho': 'July',
    'agosto': 'August',
    'setembro': 'September',
    'outubro': 'October',
    'novembro': 'November',
    'dezembro': 'December',
}

"""
Constantes globais para sincronização de ciclo de vida Pedido-Demanda.
"""

# =============================================================================
# STATUS DE PEDIDO PARA SINCRONIZAÇÃO
# =============================================================================

# IDs das situações_pedido no banco de dados
STATUS_PEDIDO_PENDENTE = 1           # "Pendente"
STATUS_PEDIDO_PAGO = 2               # "Pago"
STATUS_PEDIDO_EM_PRODUCAO = 3        # "Processando" - Pedido em produção
STATUS_PEDIDO_PRONTO_ENVIO = 4       # "Pronto para Envio" - Pedido liberado para expedição
STATUS_PEDIDO_ENVIADO = 5            # "Enviado"
STATUS_PEDIDO_ENTREGUE = 6           # "Entregue"
STATUS_PEDIDO_CANCELADO = 7          # "Cancelado"

# Mapeamento de nomes para IDs
STATUS_PEDIDO_MAP = {
    'PENDENTE': STATUS_PEDIDO_PENDENTE,
    'PAGO': STATUS_PEDIDO_PAGO,
    'EM_PRODUCAO': STATUS_PEDIDO_EM_PRODUCAO,
    'PROCESSANDO': STATUS_PEDIDO_EM_PRODUCAO,
    'PRONTO_ENVIO': STATUS_PEDIDO_PRONTO_ENVIO,
    'PRONTO_PARA_ENVIO': STATUS_PEDIDO_PRONTO_ENVIO,
    'ENVIADO': STATUS_PEDIDO_ENVIADO,
    'ENTREGUE': STATUS_PEDIDO_ENTREGUE,
    'CANCELADO': STATUS_PEDIDO_CANCELADO,
}

# Status usados na sincronização automática
STATUS_SINCRONIZACAO = {
    'ao_criar_demanda': STATUS_PEDIDO_EM_PRODUCAO,
    'ao_finalizar_demanda': STATUS_PEDIDO_PRONTO_ENVIO,
    'ao_cancelar_demanda': STATUS_PEDIDO_PAGO,  # Reverte para Pago
}

# =============================================================================
# STATUS DE DEMANDA
# =============================================================================

STATUS_DEMANDA_AGUARDANDO = 'AGUARDANDO'
STATUS_DEMANDA_EM_PRODUCAO = 'EM_PRODUCAO'
STATUS_DEMANDA_COLETA_PARCIAL = 'COLETA_PARCIAL'
STATUS_DEMANDA_COLETADO = 'COLETADO'
STATUS_DEMANDA_CONCLUIDO = 'CONCLUIDO'
STATUS_DEMANDA_CANCELADO = 'CANCELADO'

# Status que indicam demanda ativa (não finalizada)
STATUS_DEMANDA_ATIVOS = [
    STATUS_DEMANDA_AGUARDANDO,
    STATUS_DEMANDA_EM_PRODUCAO,
    STATUS_DEMANDA_COLETA_PARCIAL,
    STATUS_DEMANDA_COLETADO,
]

# Status que indicam demanda finalizada
STATUS_DEMANDA_FINALIZADOS = [
    STATUS_DEMANDA_CONCLUIDO,
    STATUS_DEMANDA_CANCELADO,
]

# =============================================================================
# TIPOS DE ALERTA
# =============================================================================

ALERTA_PEDIDO_CANCELADO = 'PEDIDO_CANCELADO'
ALERTA_DEMANDA_ATRASADA = 'DEMANDA_ATRASADA'
ALERTA_ESTOQUE_INSUFICIENTE = 'ESTOQUE_INSUFICIENTE'
ALERTA_PEDIDO_ORFAO = 'PEDIDO_ORFAO'

# Severidades de alerta
ALERTA_SEVERIDADE_ALTA = 'alta'
ALERTA_SEVERIDADE_MEDIA = 'media'
ALERTA_SEVERIDADE_BAIXA = 'baixa'

# =============================================================================
# CONSTANTES DE TEMPO
# =============================================================================

# Horas mínimas para considerar pedido órfão
HORAS_PEDIDO_ORFAO = 24

# Horas para alerta FLEX urgente
HORAS_FLEX_URGENTE = 48

# =============================================================================
# OUTRAS CONSTANTES
# =============================================================================

# Limite de itens por demanda para consolidação automática
LIMITE_ITENS_CONSOLIDACAO = 100

# Margem de segurança para prazo de entrega (dias)
MARGEM_PRAZO_ENTREGA_DIAS = 2

# =============================================================================
# CONFIGURAÇÕES DE PLATAFORMA E INTEGRAÇÃO
# =============================================================================

APP_TIMEZONE = 'America/Sao_Paulo'

BLING_ID_LOJA = {
    # antiga
    204047801: 'Shopee', 
    203726842: 'Amazon',
    203753446: 'MercadoLivre',
    204698686: 'Shein',
    # nova
    205218967: 'Shopee', 
    205228669: 'Amazon',
    # cnpj03
    205533791: 'Shein'
}

PLATFORM_ICONS = {
    # antiga
    204047801: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
    204698686: 'https://app.nistiprint.com.br/assets/img/shein.svg',
    203726842: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
    203753446: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
    # nova
    205218967: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
    205228669: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
    # cnpj03
    205533791: 'https://app.nistiprint.com.br/assets/img/shein.svg'
}

CUSTOM_ITEMS_MAP = {
    ('personaliz', 'agenda', 'barbearia'): 'barbearia',
    ('personaliz', 'planner', 'mensal', 'life'): 'life planner',
    ('personaliz', 'agenda', 'manicure', '2025'): 'manicure profissional',
    ('personaliz', 'agenda', 'manicure', 'pedicure', '2025'): 'manicure 1',
    ('personaliz', 'caderno', 'pedagogia'): 'pedagogia',
    ('personaliz', 'caderno', 'receita', 'nome'): 'receita menina',
    ('personaliz', 'caderno', 'receita', 'black'): 'receita black',
    ('personaliz', 'vacinação','menino','safari'): 'safari',
    ('personaliz', 'vacinação', 'menina', 'floral'): 'floral',
    ('personaliz', 'vacinação', 'menino', 'blue'): 'blue',
    ('personaliz', 'devocional', 'curvas', 'coloridas'): 'devocional colorido',
    ('personaliz', 'devocional', 'floral'): 'devocional floral',
    ('combo', 'casamento'): 'casamento',
    ('personaliz', 'spring', 'breeze'): 'spring breeze',
    ('personaliz', 'florescer'): 'florescer',
    ('personaliz', 'agenda', 'infantil', 'raposa'): 'raposa',
    ('personaliz', 'agenda', 'infantil', 'girafa'): 'girafa',
    ('personaliz', 'agenda', 'infantil', 'panda'): 'panda',
    ('personaliz', 'doramas', 'saranghae'): 'dorama',
    ('personaliz', 'doramas', 'forever'): 'dorama',
    ('personaliz', 'kit', 'caderneta', 'vacina', 'livro', 'bebê', 'menina', 'rosa'): 'kit eloa',
    ('personaliz', 'kit', 'caderneta', 'vacina', 'livro', 'bebê', 'menina', 'lilás'): 'kit aurora',
    ('personaliz', 'kit', 'caderneta', 'vacina', 'livro', 'bebê', 'menino'): 'kit ravi',
    ('personaliz', 'agenda', 'executiva', 'capa', 'dura', 'diária', 'anual'): 'executive',
    ('personaliz', 'caderneta', 'vacina', 'infantil', 'menina', 'lilás'): 'aurora / lilás',
    ('nisti', 'print', 'agenda', '2026', 'nome', 'capa', 'dura'): 'barbie',
    ('Caderneta', 'De', 'Vacinação', 'Menino', 'Capa', 'Dura', 'Versão', 'Atualizada'): 'nuvem',
}

SITUACOES_PEDIDOS_BLING = {
    'Em Produção': 451955,
    'Atendido': 9,
    'Cancelado': 12,
    'Em Aberto': 6,
    'Em Andamento': 15,
    'Verificado': 24,
}

PLATFORM_X_BLING_VERSION = {
    'shopee': 'nova',
    'amazon': 'nova',
    'mercadolivre': 'antiga',
    'shein': 'cnpj03',
    'shopeeflex': 'nova'
}

PLATFORM_X_CNPJ = {
    'shopee': '54533',  # CNPJ nova
    'amazon': '54533',  # CNPJ nova
    'mercadolivre': '13597',  # CNPJ antiga
    'shein': '30301',  # CNPJ cnpj03
    'shopeeflex': '54533'  # CNPJ nova
}

# Fuso horário padrão da aplicação
APP_TIMEZONE = 'America/Sao_Paulo'

features = [
            {'route': '/consolidar', 'name': 'Consolidar Produção', 'disabled': False},
            {'route': '/personalizados_v2', 'name': 'Relatório de Personalizados', 'disabled': False},
            {'route': '/produtos', 'name': 'Cadastro de Produtos', 'disabled': True}
            ]





