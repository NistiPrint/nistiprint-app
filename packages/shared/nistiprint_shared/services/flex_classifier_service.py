"""
Aplica regras parametrizáveis em flex_classification_rules.
Ordem de resolução (prioridade crescente):
  1) regras por integracao_instancia_id (match exato)
  2) regras por canal_venda_id
  3) fallback (primeira regra com padrão '%')

Operadores:
  - EQUALS               : campo == padrao
  - ILIKE                : campo ILIKE padrao
  - ILIKE_NORMALIZED     : normalize(campo) ILIKE normalize(padrao)
                           onde normalize = lower + strip_accents
"""
from dataclasses import dataclass
from typing import Optional
import unicodedata

def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    # Remove acentos e converte para lowercase
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

@dataclass
class FlexResult:
    is_flex: bool
    modalidade: str
    matched_rule_id: Optional[int]

def classify(
    db,  # SupabaseDBService
    fields: dict,                 # {'servico_logistico': ..., 'shipping_carrier': ..., 'fulfillment_flag': ...}
    integracao_instancia_id: Optional[int] = None,
    canal_venda_id: Optional[int] = None,
) -> FlexResult:
    # Busca todas as regras ativas ordenadas por prioridade
    rules = db.table('flex_classification_rules') \
        .select('*') \
        .eq('ativo', True) \
        .order('prioridade', desc=False) \
        .execute().data

    def matches(rule, value):
        op, pat = rule['operador'], rule['padrao']
        if value is None:
            # Se o valor for None, só dá match se o padrão for '%' (fallback)
            return pat == '%'
        
        if op == 'EQUALS':
            return value == pat
        if op == 'ILIKE':
            # Implementação simples de ILIKE: case insensitive e suporte a '%'
            if pat == '%':
                return True
            clean_pat = pat.replace('%', '').lower()
            return clean_pat in value.lower()
        if op == 'ILIKE_NORMALIZED':
            return _normalize(pat) in _normalize(value)
        return False

    # Ordem de preferência: instância > canal > global
    # Primeiro tentamos match com integracao_instancia_id
    if integracao_instancia_id:
        for r in rules:
            if r.get('integracao_instancia_id') == integracao_instancia_id:
                val = fields.get(r['campo'])
                if matches(r, val):
                    return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'])

    # Depois tentamos match com canal_venda_id
    if canal_venda_id:
        for r in rules:
            if r.get('canal_venda_id') == canal_venda_id:
                val = fields.get(r['campo'])
                if matches(r, val):
                    return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'])

    # Por fim, fallback global (regras sem escopo de instância ou canal)
    for r in rules:
        if r.get('integracao_instancia_id') is None and r.get('canal_venda_id') is None:
            val = fields.get(r['campo'])
            if matches(r, val):
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'])

    return FlexResult(False, 'STANDARD', None)
