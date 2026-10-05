"""Manutencao logistica e leitura da agenda; transacoes vivem nas RPCs."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from nistiprint_shared.database.supabase_db_service import supabase_db


def rpc_data(name: str, params: dict | None = None):
    data = supabase_db.rpc(name, params or {}).execute().data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) and name in data[0]:
        return data[0][name]
    return data


MODALIDADE_FIELDS = {'module_id', 'codigo', 'nome', 'tipo_prazo', 'politica_lote',
    'nivel_interrupcao', 'entra_na_torre', 'entrega_rapida', 'ativo', 'cor',
    'ordem_exibicao', 'offset_etiqueta_min', 'offset_coleta_min'}
REGRA_FIELDS = {'marketplace_integration_id', 'modalidade_id', 'tipo_envio',
    'horario_corte', 'horario_coleta', 'ponto_coleta_id', 'dias_semana', 'prioridade_uso',
    'ativo', 'descricao', 'offset_etiqueta_min', 'offset_coleta_min', 'modalidade_ids',
    'fonte_agenda', 'modo_corte', 'antecedencia_corte_min', 'antecedencia_alerta_min',
    'logistic_type', 'coleta_rapida'}


def _payload(data, fields):
    if not isinstance(data, dict):
        raise ValueError('Informe um objeto JSON')
    result = {k: v for k, v in data.items() if k in fields}
    for field in ('ativo', 'entra_na_torre', 'entrega_rapida', 'coleta_rapida'):
        if field in result and result[field] is not None and not isinstance(result[field], bool):
            raise ValueError(f'{field} deve ser booleano')
    for field in ('offset_etiqueta_min', 'offset_coleta_min', 'antecedencia_corte_min',
                  'antecedencia_alerta_min', 'nivel_interrupcao', 'prioridade_uso', 'ordem_exibicao',
                  'modalidade_id', 'marketplace_integration_id', 'ponto_coleta_id'):
        if field in result and result[field] is not None:
            if isinstance(result[field], bool) or not re.fullmatch(r'-?\d+', str(result[field])):
                raise ValueError(f'{field} deve ser um numero inteiro')
            result[field] = int(result[field])
    for field in ('nome', 'codigo', 'module_id'):
        if field in result:
            if not isinstance(result[field], str) or not result[field].strip():
                raise ValueError(f'{field} e obrigatorio')
            result[field] = result[field].strip()
    if 'cor' in result and result['cor'] and not re.fullmatch(r'#[0-9a-fA-F]{6}', result['cor']):
        raise ValueError('Cor deve usar #RRGGBB')
    if 'modalidade_ids' in result and (not isinstance(result['modalidade_ids'], list)
        or any(isinstance(v, bool) or not isinstance(v, int) for v in result['modalidade_ids'])):
        raise ValueError('modalidade_ids deve ser uma lista de inteiros')
    return result


def salvar_modalidade(data, modalidade_id=None, ator=None):
    payload = _payload(data, MODALIDADE_FIELDS)
    if modalidade_id is None and not all(payload.get(k) for k in ('module_id', 'codigo', 'nome')):
        raise ValueError('Marketplace, codigo e nome sao obrigatorios')
    return rpc_data('logistica_salvar_modalidade', {'p_id': modalidade_id, 'p_dados': payload, 'p_ator': ator})


def salvar_regra(data, regra_id=None, ator=None):
    payload = _payload(data, REGRA_FIELDS)
    if regra_id is None and not all(payload.get(k) for k in ('marketplace_integration_id', 'modalidade_id', 'tipo_envio')):
        raise ValueError('Integracao, modalidade e tipo de envio sao obrigatorios')
    return rpc_data('logistica_salvar_regra', {'p_id': regra_id, 'p_dados': payload, 'p_ator': ator})


def associar(data, ator=None):
    if not isinstance(data, dict) or not data.get('module_id') or not str(data.get('chave') or '').strip():
        raise ValueError('Marketplace e identificador sao obrigatorios')
    condicoes = data.get('condicoes') or {}
    if not isinstance(condicoes, dict) or set(condicoes) - {'service', 'tags'}:
        raise ValueError('Condicoes aceitam servico e tags')
    if 'service' in condicoes and not isinstance(condicoes['service'], str):
        raise ValueError('Servico deve ser texto')
    if 'tags' in condicoes:
        if not isinstance(condicoes['tags'], list) or any(not isinstance(t, str) or not t.strip() for t in condicoes['tags']):
            raise ValueError('Informe uma lista de tags')
        condicoes = {**condicoes, 'tags': sorted(set(t.strip() for t in condicoes['tags']))}
    return rpc_data('logistica_associar', {
        'p_module_id': str(data['module_id']), 'p_chave': str(data['chave']).strip(),
        'p_modalidade_id': int(data['modalidade_id']) if data.get('modalidade_id') is not None else None,
        'p_condicoes': condicoes, 'p_id': data.get('associacao_id'), 'p_ator': ator,
    })


def validar_periodo(inicio, fim):
    inicio, fim = date.fromisoformat(inicio), date.fromisoformat(fim)
    if fim < inicio or (fim-inicio).days > 31:
        raise ValueError('Consulte no maximo 31 dias')
    return inicio.isoformat(), fim.isoformat()


def normalize_schedule(payload: dict) -> dict:
    """Falha fechada: payload invalido nunca substitui o ultimo cache valido."""
    schedule = payload.get('schedule')
    if not isinstance(schedule, dict) or not schedule:
        raise ValueError('Marketplace nao retornou uma agenda valida')
    valid = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
    out = {}
    for day, info in schedule.items():
        if day not in valid or not isinstance(info, dict) or not isinstance(info.get('work'), bool):
            raise ValueError('Dia de atendimento invalido')
        details = info.get('detail') or []
        if not isinstance(details, list):
            raise ValueError('Faixas de coleta invalidas')
        normalized = []
        for window in details:
            if not isinstance(window, dict) or not window.get('from'):
                raise ValueError('Faixa sem horario inicial')
            row = {}
            for field in ('from', 'to', 'cutoff'):
                value = window.get(field)
                if value:
                    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', value):
                        raise ValueError('Horario invalido na agenda')
                    datetime.strptime(value[:5], '%H:%M')
                    row[field] = value[:5]
            if 'milkrun_same_day' in window:
                if not isinstance(window['milkrun_same_day'], bool):
                    raise ValueError('Indicador de coleta rapida invalido')
                row['milkrun_same_day'] = window['milkrun_same_day']
            normalized.append(row)
        out[day] = {'work': info['work'], 'detail': normalized}
    return out


def retry_at(result, now=None):
    now = now or datetime.now(timezone.utc)
    seconds = max(60, float(result.get('retry_after') or 900))
    return (now+timedelta(seconds=seconds)).isoformat()
