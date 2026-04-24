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
    
}

PLATFORM_X_BLING_VERSION = {
    'shopee': 'antiga',
    'amazon': 'nova',
    'mercadolivre': 'antiga',
    'shein': 'cnpj03',
    'shopeeflex': 'antiga'
}

PLATFORM_X_CNPJ = {
    'shopee': '13597',  # CNPJ nova
    'amazon': '54533',  # CNPJ nova
    'mercadolivre': '13597',  # CNPJ antiga
    'shein': '30301',  # CNPJ cnpj03
    'shopeeflex': '13597'  # CNPJ nova
}

features = [
            {'route': '/consolidar', 'name': 'Consolidar Produção', 'disabled': False},
            {'route': '/personalizados_v2', 'name': 'Relatório de Personalizados', 'disabled': False},
            {'route': '/produtos', 'name': 'Cadastro de Produtos', 'disabled': True}
            ]
