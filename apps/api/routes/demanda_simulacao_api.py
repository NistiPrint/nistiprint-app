"""API isolada para percorrer o ciclo de demanda sem efeitos operacionais."""

import hashlib
import json
import logging
from uuid import UUID

from flask import Blueprint, jsonify, request
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.permissao_service import permissao_service
from routes.auth import _active_session_user, user_has_permission, user_has_demand_permission
from routes.demanda_simulacao_state import create_state, display_state, transition


logger = logging.getLogger(__name__)
simulacao_bp = Blueprint('demanda_simulacao', __name__, url_prefix='/api/v2/demanda-simulacoes')


def _permission(action):
    user = _active_session_user()
    if not user:
        return None, (jsonify({'success': False, 'message': 'Autenticação requerida'}), 401)
    if not user_has_permission(user, 'demanda_producao', action):
        return None, (jsonify({'success': False, 'message': 'Permissão de demanda necessária'}), 403)
    return user, None


def _row(simulation_id):
    rows = (supabase_db.table('demanda_simulacoes').select('*')
            .eq('id', simulation_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def _single(value):
    return value[0] if isinstance(value, list) and value else value


def _version(body):
    try:
        value = int(body.get('version'))
        if value <= 0 or isinstance(body.get('version'), bool):
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise ValueError('Informe a versão atual da simulação') from None


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError('ID da operação inválido') from None


def _database_error(exc):
    message = str(exc)
    if 'SIMULACAO_VERSAO_CONFLITANTE' in message or 'SIMULACAO_ORIGEM_ALTERADA' in message:
        return jsonify({'success': False, 'message': 'Os dados mudaram. Recarregue e revise antes de continuar.'}), 409
    if 'SIMULACAO_NAO_ENCONTRADA' in message:
        return jsonify({'success': False, 'message': 'Simulação não encontrada'}), 404
    if 'SIMULACAO_OPERACAO_REUTILIZADA' in message:
        return jsonify({'success': False, 'message': 'ID da operação reutilizado com outros dados'}), 409
    logger.exception('Falha na simulação de demanda')
    return jsonify({'success': False, 'message': 'Falha ao salvar a simulação'}), 500


@simulacao_bp.route('', methods=['GET', 'POST'])
def simulations():
    user, error = _permission('ler' if request.method == 'GET' else 'criar')
    if error:
        return error
    try:
        if request.method == 'GET':
            rows = (supabase_db.table('demanda_simulacoes')
                    .select('id,pedido_ids,state,version,created_by,created_at,updated_at')
                    .order('created_at', desc=True).limit(100).execute().data or [])
            return jsonify({'success': True, 'data': [
                {'id': row['id'], 'nome': row['state'].get('nome'),
                 'status': row['state'].get('status'), 'pedido_ids': row['pedido_ids'],
                 'version': row['version'], 'created_at': row['created_at']}
                for row in rows
            ]})

        from routes.despacho import _pedido_ids_do_lote, _previsao_do_lote

        body = request.get_json(silent=True) or {}
        operation_id = _uuid(body.get('operation_id'))
        request_hash = hashlib.sha256(json.dumps(
            {key: value for key, value in body.items() if key != 'operation_id'},
            sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()
        previous = (supabase_db.table('demanda_simulacao_eventos')
                    .select('simulacao_id,request_hash').eq('operation_id', operation_id)
                    .limit(1).execute().data or [])
        if previous:
            if previous[0]['request_hash'] != request_hash:
                return jsonify({'success': False, 'message': 'ID da operação reutilizado'}), 409
            existing = _row(previous[0]['simulacao_id'])
            if existing:
                return jsonify({'success': True, 'demanda': display_state(existing)}), 200
            return jsonify({'success': False, 'message': 'Simulação já excluída'}), 409
        ids, source = _pedido_ids_do_lote(body)
        if not ids or len(ids) > 1000 or len(ids) != len(set(ids)):
            raise ValueError('Selecione entre 1 e 1000 pedidos distintos na Torre')
        fingerprint_before = supabase_db.rpc('demanda_simulacao_fingerprint', {'p_pedido_ids': ids}).execute().data
        preview = _previsao_do_lote(ids, source)
        if preview['previsao_versao'] != body.get('previsao_versao'):
            return jsonify({'success': False, 'message': 'A consolidação mudou. Recarregue a Torre.'}), 409
        lines = body.get('linhas')
        if not isinstance(lines, list):
            raise ValueError('Informe as linhas da consolidação')
        original_keys = {line['linha_chave'] for line in preview['itens']}
        provided_keys = [line.get('linha_chave') for line in lines if isinstance(line, dict) and line.get('linha_chave')]
        if len(provided_keys) != len(set(provided_keys)) or set(provided_keys) - original_keys:
            raise ValueError('A consolidação contém linhas originais desconhecidas ou repetidas')
        orders = []
        for index in range(0, len(ids), 200):
            orders.extend((supabase_db.table('pedidos')
                           .select('id,numero_pedido,codigo_pedido_externo,cliente_nome,marketplace_order_id,data_limite_envio,is_flex')
                           .in_('id', ids[index:index + 200]).execute().data or []))
        by_id = {order['id']: order for order in orders}
        if len(by_id) != len(ids):
            return jsonify({'success': False, 'message': 'O conjunto de pedidos mudou'}), 409
        orders = [{**by_id[order_id], 'pedido_id': order_id} for order_id in ids]
        scope = {key: body.get(key) for key in ('marketplace_nome', 'modalidade_nome')}
        state = create_state(lines, orders, scope)
        fingerprint = supabase_db.rpc('demanda_simulacao_fingerprint', {'p_pedido_ids': ids}).execute().data
        if fingerprint != fingerprint_before:
            return jsonify({'success': False, 'message': 'Os pedidos mudaram durante a cópia. Recarregue a Torre.'}), 409
        snapshot = {'pedido_ids': ids, 'pedidos': orders, 'linhas_originais': preview['itens'],
                    'previsao_versao': preview['previsao_versao'], 'origem': source, 'escopo': scope,
                    'operation_id': operation_id, 'request_hash': request_hash}
        result = supabase_db.rpc('demanda_simulacao_criar', {
            'p_pedido_ids': ids, 'p_fingerprint': fingerprint, 'p_snapshot': snapshot,
            'p_state': state, 'p_actor': str(user['id']),
        }).execute().data
        return jsonify({'success': True, 'demanda': display_state(_single(result))}), 201
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        return _database_error(exc)


@simulacao_bp.route('/<uuid:simulation_id>', methods=['GET', 'DELETE'])
def simulation(simulation_id):
    user, error = _permission('ler' if request.method == 'GET' else 'excluir')
    if error:
        return error
    if request.method == 'DELETE' and not user_has_demand_permission(user, 'delete_demand'):
        return jsonify({'success': False, 'message': 'Ação de exclusão não autorizada'}), 403
    try:
        row = _row(str(simulation_id))
        if not row:
            return jsonify({'success': False, 'message': 'Simulação não encontrada'}), 404
        if request.method == 'GET':
            return jsonify({'success': True, 'demanda': display_state(row)})
        version = _version(request.get_json(silent=True) or {})
        supabase_db.rpc('demanda_simulacao_excluir', {
            'p_id': str(simulation_id), 'p_expected_version': version,
        }).execute()
        return jsonify({'success': True})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        return _database_error(exc)


@simulacao_bp.route('/<uuid:simulation_id>/coletas', methods=['GET'])
def collections(simulation_id):
    _, error = _permission('ler')
    if error:
        return error
    row = _row(str(simulation_id))
    if not row:
        return jsonify({'success': False, 'message': 'Simulação não encontrada'}), 404
    return jsonify({'success': True, 'coletas': row['state'].get('coletas', [])})


@simulacao_bp.route('/<uuid:simulation_id>/eventos', methods=['GET'])
def events(simulation_id):
    _, error = _permission('ler')
    if error:
        return error
    if not _row(str(simulation_id)):
        return jsonify({'success': False, 'message': 'Simulação não encontrada'}), 404
    rows = (supabase_db.table('demanda_simulacao_eventos')
            .select('action,actor,details,created_at')
            .eq('simulacao_id', str(simulation_id)).order('id', desc=True)
            .limit(100).execute().data or [])
    return jsonify({'success': True, 'eventos': rows})


@simulacao_bp.route('/<uuid:simulation_id>/acoes', methods=['POST'])
def action(simulation_id):
    user, error = _permission('editar')
    if error:
        return error
    try:
        body = request.get_json(silent=True) or {}
        version = _version(body)
        operation_id = _uuid(body.get('operation_id'))
        name = body.get('action')
        payload = body.get('payload') or {}
        if not isinstance(payload, dict) or not isinstance(name, str):
            raise ValueError('Ação inválida')
        demand_action = {
            'finalizar_item': 'finalize_item', 'finalizar_demanda': 'finalize_item',
            'reverter_item': 'revert_finalize_item', 'coletar': 'collect_demand',
        }.get(name)
        if demand_action and not user_has_demand_permission(user, demand_action):
            return jsonify({'success': False, 'message': 'Ação de demanda não autorizada'}), 403
        if name == 'producao' and not user.get('is_admin'):
            allowed = set(permissao_service.get_demand_permissions(user.get('setor_id')).get('fields') or [])
            updates = payload.get('updates') or []
            if not isinstance(updates, list) or any(not isinstance(update, dict) for update in updates):
                raise ValueError('Itens de produção inválidos')
            if any(not isinstance(update.get('producao_incremental'), dict) for update in updates):
                raise ValueError('Etapas de produção inválidas')
            fields = {field for update in updates for field in (update.get('producao_incremental') or {})}
            if fields - allowed:
                return jsonify({'success': False, 'message': 'Etapa de produção não autorizada'}), 403
        digest = hashlib.sha256(json.dumps([name, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        row = _row(str(simulation_id))
        if not row:
            return jsonify({'success': False, 'message': 'Simulação não encontrada'}), 404
        previous = (supabase_db.table('demanda_simulacao_eventos')
                    .select('simulacao_id,request_hash').eq('operation_id', operation_id).limit(1).execute().data or [])
        if previous:
            if previous[0]['request_hash'] != digest or previous[0]['simulacao_id'] != str(simulation_id):
                return jsonify({'success': False, 'message': 'ID da operação reutilizado'}), 409
            return jsonify({'success': True, 'demanda': display_state(row)})
        if version != row['version']:
            return jsonify({'success': False, 'message': 'A simulação mudou. Recarregue a tela.'}), 409
        state = transition(row['state'], name, payload)
        result = supabase_db.rpc('demanda_simulacao_alterar', {
            'p_id': str(simulation_id), 'p_expected_version': version, 'p_state': state,
            'p_action': name, 'p_details': payload, 'p_operation_id': operation_id,
            'p_request_hash': digest, 'p_actor': str(user['id']),
        }).execute().data
        return jsonify({'success': True, 'demanda': display_state(_single(result))})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        return _database_error(exc)
