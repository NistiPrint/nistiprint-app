import os
import re
import shutil
import json
from datetime import datetime
import traceback

import constants


def replace_month(date_str):
    for pt_month, en_month in constants.MONTH_MAP.items():
        date_str = date_str.replace(pt_month, en_month)
    return date_str

def apply_miolo_fixes(miolo):
    """Apply all miolo fixes in sequence while maintaining original order"""
    miolo = fix_combo_vacina(miolo)
    miolo = fix_plangest(miolo)
    miolo = fix_confinnv(miolo)
    miolo = fix_confin25(miolo)
    miolo = fix_pb25(miolo)
    miolo = fix_pb26(miolo)
    miolo = fix_vacmna(miolo)
    miolo = fix_devnp(miolo)
    miolo = fix_cadage(miolo)
    miolo = fix_cadmos(miolo)
    miolo = fix_cadrel(miolo)
    miolo = fix_planpr(miolo)
    miolo = fix_cadfl(miolo)
    
    return miolo

def fix_amazon_25_to_26(miolo):
    if 'MANI25' in miolo or 'AGMT25' in miolo:
        return 'AGMT26'
    if 'PLAN25' in miolo:
        return 'PLAN26'
    if 'PB25' in miolo:
        return 'PB26'
    return miolo


def fix_plangest(miolo):
    return 'GESTAN' if miolo == 'PLANGEST01' else miolo[:8]

def fix_confinnv(miolo):
    return 'CONFIN25' if miolo == 'CONFINNV' else miolo

def fix_cadage(miolo):
    return 'PTD200' if miolo == 'CADAGE' else miolo

def fix_cadmos(miolo):
    return 'VACMNO' if miolo == 'CADMOS' else miolo

def fix_cadrel(miolo):
    return 'RECTAS' if miolo == 'CADREL' else miolo

def fix_planpr(miolo):
    return 'PNJPRO' if miolo == 'PLANPR' else miolo

def fix_cadfl(miolo):
    return 'PTD200' if miolo == 'CADFL' else miolo

def fix_confin25(miolo):
    return miolo[:6] if miolo != 'CONFIN25' else miolo

def fix_pb25(miolo):
    return 'PB25' if 'PB25' in miolo else miolo

def fix_pb26(miolo):
    return 'PB26' if 'PB26' in miolo else miolo

def fix_combo_vacina(miolo):
    if 'CMB_VACMNA' in miolo:
        return 'CMBMNA'
    if 'CMB_VACMNO' in miolo:
        return 'CMBMNO'
    return miolo

def fix_vacmna(miolo):
    return 'VACMNA' if miolo == 'CADMNA' else miolo

def fix_devnp(miolo):
    return 'DEVNP' if miolo == 'DEVNP_' else miolo

def fix_sku_devocional_amazon(miolo):
    sku_map = {
        'YE-U3Z': 'DEVNP',    # Caderno Planner Devocional 204 Páginas - Colors
        'HN-YPB': 'CARDSEM',  # Planner Para Planejamento Alimentar Com 56 Semanas
        '2B-1Z5': 'AG242D',   # Agenda 2024 Para Organização Pessoal - Capa Dura - 214 Pgs Capa Rosa
        'AGPBNV': 'AG242D',   # Agenda 2024 Para Organização Pessoal - Capa Dura - 214 Pgs Capa Rosa
        '19-MFS': 'CCAIXA',   # Caderno De Controle De Caixa
        'F8-G9Y': 'VACMNO',   # Caderneta De Vacinação MeninO - Capa Dura - Versão Atualizada - Nuvem
        'PLANLF': 'PLAN25',   # Planner 2024 - Life - Visão Mensal E Semanal
        'CADRMR': 'RECTAS',    # Caderno De Receitas - Minhas Receitas - (Cabelinho Preto)
        'CADCON': 'CONFIN',
        'CADAFL': 'PTD200',
        'CADANF': 'PTDVOV',
        'AGDGV_': 'AGDPERM',
        'SCPBLO': 'SCRABK',
        'AGESCI': 'CADMNO',
        'PLANNV': 'PLANNV01',
        'CADREL': 'RECTAS',
        'CADCAL': 'CALIGR',
        'PLANGE': 'PLANGEST',
        'AGMT24': 'MANI25',
        'CADAGE': 'PTD200',
        'AGNEG2': 'PB25',
        'CADVMO': 'VACMNO',
        'PLAN24': 'PLAN25',
        'SCRPK_': 'SCRABK02'
    }
    return sku_map.get(miolo, miolo)


def generate_ids_chunks(ids_pedidos, chunk_size=100):
    # generate array of strings containing [chunk_size] order_ids in sequence split by ; each
    chunks = [ids_pedidos[i:i + chunk_size]
              for i in range(0, len(ids_pedidos), chunk_size)]
    return [';'.join(chunk) for chunk in chunks]


def prepare_ml_file(filepath):
    # Garante que o diretório temp existe
    temp_dir = os.path.dirname(filepath)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    filename, file_extension = os.path.splitext(filepath)
    new_filename = filename + '.xls'
    shutil.copy(filepath, new_filename)
    return new_filename


def apply_date_filter(data, period_filter, date_column):
    """Apply date filtering while maintaining original logic"""
    if period_filter is not None and date_column is not None:
        return data[(data[date_column] >= period_filter['start']) & (data[date_column] <= period_filter['end'])]
    return data


def process_string(item):
    result = ''
    
    if 'CADMOSF' in item['codigo']:
        return 'SAFARI'
    
    if 'VACMNOP NUV BAA' in item['codigo']:
        return 'NUVEM'
    
    if 'VACMNO URS B B' in item['codigo']:
        return 'URSOS'
    
    if '| AGENDA 2025 PERSONALIZADA COM NOME E CAPA DURA' in item['descricao']:
        return 'BARBIE'
    
    """
    Check if all words in any key exist in the input string and return the value.
    Ignores the order of the words and handles case sensitivity.
    """
    # Normalize the input string (lowercase and remove extra spaces)
    normalized_input = re.sub(r'\s+', ' ', item['descricao'].lower()).strip()

    for words, value in constants.CUSTOM_ITEMS_MAP.items():
        # Check if all words in the key are in the input string
        if all(word.lower() in normalized_input for word in words):
            result = value
    return result.upper()

def process_message_content(message):
    """Process message content based on message type"""
    try:
        # Check if content exists and is a string
        if 'content' not in message or not message['content']:
            message['display_content'] = 'Mensagem sem conteúdo'
            return message

        # Try to parse JSON content
        content = message['content']
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError as e:
                message['display_content'] = content if isinstance(
                    content, str) else str(content)
                return message

        # Process based on message type
        message_type = message.get('type')
        if message_type == 'new_faq' and isinstance(content, dict) and 'opening' in content:
            message['display_content'] = content['opening']
        elif message_type == 'notification' and isinstance(content, dict) and 'notification_for_sender' in content:
            message['display_content'] = content['notification_for_sender']
        elif isinstance(content, dict) and 'text' in content:
            message['display_content'] = content['text']
        elif isinstance(content, dict) and 'sticker_id' in content:
            message['display_content'] = '[figurinha]'
        elif isinstance(content, dict):
            message['display_content'] = str(content)
        else:
            message['display_content'] = str(content)

    except Exception as e:
        import traceback
        traceback.print_exc()
        message['display_content'] = f'Erro ao processar mensagem: {str(e)}'

    return message


def br_currency(value, decimals=2):
    """Format value as Brazilian currency (R$ 1.234,56)."""
    if value is None:
        value = 0
    try:
        # Ensure it's a number
        value = float(value)

        # Format with Brazilian locale: comma for decimal, period for thousands
        formatted = f"{value:,.{decimals}f}"

        # Replace American format to Brazilian
        # 1,234.56 -> 1.234,56
        formatted = formatted.replace(',', 'temp').replace('.', ',').replace('temp', '.')

        return f"R$ {formatted}"
    except (ValueError, TypeError):
        return f"R$ {value}"


def br_number(value, decimals=2):
    """Format value as Brazilian number with comma for decimals."""
    if value is None:
        value = 0
    try:
        # Ensure it's a number
        value = float(value)

        # Format with Brazilian locale: comma for decimal, period for thousands
        formatted = f"{value:,.{decimals}f}"

        # Replace American format to Brazilian
        formatted = formatted.replace(',', 'temp').replace('.', ',').replace('temp', '.')

        return formatted
    except (ValueError, TypeError):
        return str(value)





