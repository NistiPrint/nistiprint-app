"""Normalize delivery geography supplied by marketplace order details."""

import re


def location(value):
    if isinstance(value, dict):
        value = value.get('name') or value.get('id')
    if value is None:
        return None
    text = ' '.join(str(value).split())
    if not text or text.casefold() in {'null', 'none', 'não informado', 'nao informado'}:
        return None
    if re.fullmatch(r'[*xX•#-]+', text):
        return None
    return text
