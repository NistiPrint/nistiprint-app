from flask import request, jsonify
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.deposito_service import deposito_service
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.estoque_command_service import (
    EstoqueCommandConflict,
    EstoqueCommandOutcomeUnknown,
    estoque_command_service,
)
from routes.auth import check_permission, login_required, get_current_user
from .estoque_base import estoque_api_bp


@estoque_api_bp.get('/divergencias-ledger')
@check_permission('estoque', 'ler')
def api_listar_divergencias_ledger():
    """List current balances that differ from their latest recorded movement."""
    limit = max(1, min(100, request.args.get('limit', 50, type=int)))
    offset = max(0, min(1_000_000, request.args.get('offset', 0, type=int)))
    try:
        response = (
            supabase_db.table('v_estoque_saldo_ledger_divergencias')
            .select('produto_id,produto_sku,produto_nome,deposito_id,deposito_nome,saldo_atual,saldo_ultimo_movimento,diferenca,movimento_id,movimento_registrado_em', count='exact')
            .order('movimento_registrado_em', desc=True, nullsfirst=False)
            .order('produto_id')
            .order('deposito_id')
            .range(offset, offset + limit - 1)
            .execute()
        )
        return jsonify({
            'success': True,
            'data': response.data or [],
            'limit': limit,
            'offset': offset,
            'count': int(getattr(response, 'count', 0) or 0),
        }), 200
    except Exception:
        return jsonify({
            'success': False,
            'error': 'Não foi possível consultar divergências de saldo.',
        }), 503


@estoque_api_bp.route('/comandos', methods=['POST'])
@login_required
def api_executar_comando_estoque():
    data = request.get_json(silent=True) or {}
    usuario = get_current_user()
    actor_context = {
        'id': usuario['id'],
        'is_admin': usuario.get('is_admin', False),
        'setor_id': usuario.get('setor_id'),
    }
    try:
        if not estoque_command_service.is_enabled():
            return jsonify({
                'error': 'Comandos de estoque v2 ainda não estão habilitados para este ambiente.',
                'code': 'feature_disabled',
            }), 503
        movements = data.get('movimentos') or []
        if not isinstance(movements, list):
            return jsonify({'error': 'movimentos deve ser uma lista.'}), 400
        for movement in movements:
            if not isinstance(movement, dict):
                return jsonify({'error': 'Cada movimento deve ser um objeto.'}), 400
            try:
                product_id = int(movement.get('produto_id'))
                deposit_id = int(movement.get('deposito_id'))
            except (TypeError, ValueError):
                return jsonify({'error': 'produto_id e deposito_id devem ser inteiros.'}), 400
            try:
                estoque_service._validate_stock_eligibility(product_id)
            except ValueError as exc:
                return jsonify({'error': str(exc), 'code': 'stock_ineligible'}), 422
            try:
                estoque_service._validate_sector_permission(product_id, actor_context)
            except PermissionError as exc:
                return jsonify({'error': str(exc)}), 403
            if not deposito_service.get_by_id(deposit_id):
                return jsonify({'error': f"Depósito inválido: {deposit_id}", 'code': 'invalid_deposit'}), 422
        result = estoque_command_service.execute_command(data, actor_context)
        return jsonify(result), 200
    except EstoqueCommandConflict as exc:
        return jsonify({'error': str(exc), 'code': 'operation_conflict'}), 409
    except EstoqueCommandOutcomeUnknown as exc:
        return jsonify({
            'error': 'Resultado ainda não confirmado; consulte ou repita usando o mesmo operation_id.',
            'code': 'outcome_unknown',
            'operation_id': exc.operation_id,
        }), 503
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 503


@estoque_api_bp.route('/operacoes/<operation_id>', methods=['GET'])
@login_required
def api_obter_operacao_estoque(operation_id):
    usuario = get_current_user()
    actor_context = {
        'id': usuario['id'],
        'is_admin': usuario.get('is_admin', False),
    }
    try:
        operation = estoque_command_service.get_operation(operation_id, actor_context)
        if operation is None:
            return jsonify({'error': 'Operação não encontrada.'}), 404
        return jsonify(operation), 200
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 503

@estoque_api_bp.route('/', methods=['GET'])
def api_dashboard():
    """Dashboard de controle de estoque - Exibe últimas movimentações e resumos (API)."""
    try:
        alertas = estoque_service.get_alertas_estoque()
        todas_movimentacoes = estoque_service.get_recent_movimentacoes(limit=100)
        movimentacoes = [m for m in todas_movimentacoes if m.get('tipo_movimento') in ['ENTRADA', 'SAIDA', 'TRANSFERENCIA_ENTRADA', 'TRANSFERENCIA_SAIDA', 'BALANCO']][:20]
        
        produto_ids = list(set(mov.get('produto_id') for mov in movimentacoes if mov.get('produto_id')))
        deposito_ids = list(set(mov.get('deposito_id') for mov in movimentacoes if mov.get('deposito_id')))
        deposito_origem_ids = list(set(mov.get('deposito_origem_id') for mov in movimentacoes if mov.get('deposito_origem_id')))
        deposito_destino_ids = list(set(mov.get('deposito_destino_id') for mov in movimentacoes if mov.get('deposito_destino_id')))

        all_relevant_deposito_ids = list(set(deposito_ids + deposito_origem_ids + deposito_destino_ids))

        prefetched_products = {}
        prefetched_depositos = {}
        try:
            if produto_ids:
                prefetched_products = product_service.get_by_ids(produto_ids)
            if all_relevant_deposito_ids:
                prefetched_depositos = deposito_service.get_by_ids(all_relevant_deposito_ids)
        except Exception as e:
            print(f"Erro ao pré-carregar dados: {str(e)}")

        depositos = deposito_service.get_all()
        posicao_estoque = estoque_service.get_posicao_estoque()
        all_products_for_costs = product_service.get_all(per_page=9999)
        product_costs = {p['id']: p.get('cost_price', 0) for p in all_products_for_costs}

        deposito_summary = []
        for deposito in depositos:
            produtos_deposito = [p for p in posicao_estoque if p['deposito_id'] == deposito['id']]
            total_produtos = len(set(p['produto_id'] for p in produtos_deposito))
            valor_total = sum(
                p.get('quantidade', 0) * product_costs.get(p['produto_id'], 0)
                for p in produtos_deposito
            )

            deposito_summary.append({
                'deposito': deposito,
                'total_produtos': total_produtos,
                'valor_total': valor_total
            })

        return jsonify({
            'alertas': alertas,
            'movimentacoes': movimentacoes,
            'deposito_summary': deposito_summary,
            'posicao_estoque': posicao_estoque,
            'depositos': depositos,
            'prefetched_products': prefetched_products,
            'prefetched_depositos': prefetched_depositos
        })

    except Exception as e:
        print(f'Erro na API do dashboard de estoque: {str(e)}')
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/historico', methods=['GET'])
def api_historico():
    """Página de histórico de movimentações com filtros (API)."""
    try:
        produto_id = request.args.get('produto_id')
        deposito_id = request.args.get('deposito_id')
        tipo_movimento = request.args.get('tipo_movimento')
        data_inicio_str = request.args.get('data_inicio')
        data_fim_str = request.args.get('data_fim')
        limit = int(request.args.get('limit', 100))

        from datetime import datetime
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d') if data_inicio_str else None
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d') if data_fim_str else None

        movimentacoes = []
        if produto_id:
            movimentacoes = estoque_service.get_movimentacoes_produto(
                produto_id=produto_id,
                deposito_id=deposito_id,
                tipo_movimento=tipo_movimento,
                data_inicio=data_inicio,
                data_fim=data_fim,
                limit=limit
            )
        else:
            movimentacoes = estoque_service.get_recent_movimentacoes(
                limit=limit,
                tipo_movimento=tipo_movimento
            )

        produto_ids = list(set(mov.get('produto_id') for mov in movimentacoes if mov.get('produto_id')))
        deposito_ids = list(set(mov.get('deposito_id') for mov in movimentacoes if mov.get('deposito_id')))
        deposito_origem_ids = list(set(mov.get('deposito_origem_id') for mov in movimentacoes if mov.get('deposito_origem_id')))
        deposito_destino_ids = list(set(mov.get('deposito_destino_id') for mov in movimentacoes if mov.get('deposito_destino_id')))

        all_relevant_deposito_ids = list(set(deposito_ids + deposito_origem_ids + deposito_destino_ids))

        prefetched_products = {}
        prefetched_depositos = {}
        try:
            if produto_ids:
                prefetched_products = product_service.get_by_ids(produto_ids)
            if all_relevant_deposito_ids:
                prefetched_depositos = deposito_service.get_by_ids(all_relevant_deposito_ids)
        except Exception as e:
            print(f"Erro ao pré-carregar dados para histórico: {str(e)}")

        depositos = deposito_service.get_all()

        produto_selecionado = None
        if produto_id:
            produto_selecionado = product_service.get_by_id(produto_id)

        return jsonify({
            'movimentacoes': movimentacoes,
            'depositos': depositos,
            'filtro_produto': produto_id,
            'produto_selecionado': produto_selecionado,
            'filtro_deposito': deposito_id,
            'filtro_tipo': tipo_movimento,
            'filtro_data_inicio': data_inicio_str or '',
            'filtro_data_fim': data_fim_str or '',
            'prefetched_products': prefetched_products,
            'prefetched_depositos': prefetched_depositos
        })

    except Exception as e:
        print(f'Erro na API do histórico de movimentações: {str(e)}')
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/historico-consolidado', methods=['GET'])
def api_historico_consolidado():
    """
    Histórico de movimentações agrupadas por (correlation_id, estagio).
    Cada bloco representa um evento de negócio: FINALIZACAO, JIT ou CONSUMO.

    Query params:
        produto_id, deposito_id, demanda_id, item_demanda_id, tipo_bloco
        data_inicio, data_fim (YYYY-MM-DD), limit (default 200)
    """
    try:
        from datetime import datetime
        produto_id = request.args.get('produto_id') or None
        deposito_id = request.args.get('deposito_id') or None
        demanda_id = request.args.get('demanda_id') or None
        item_demanda_id = request.args.get('item_demanda_id') or None
        tipo_bloco = request.args.get('tipo_bloco') or None
        data_inicio_str = request.args.get('data_inicio')
        data_fim_str = request.args.get('data_fim')
        limit = int(request.args.get('limit', 200))

        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d') if data_inicio_str else None
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d') if data_fim_str else None

        # Trata "all"/vazio como não filtrar
        if produto_id == 'all':
            produto_id = None
        if deposito_id == 'all':
            deposito_id = None
        if tipo_bloco == 'all':
            tipo_bloco = None

        blocos = estoque_service.get_movimentacoes_consolidadas(
            produto_id=produto_id,
            deposito_id=deposito_id,
            demanda_id=demanda_id,
            item_demanda_id=item_demanda_id,
            tipo_bloco=tipo_bloco,
            data_inicio=data_inicio,
            data_fim=data_fim,
            limit=limit,
        )

        depositos = deposito_service.get_all()

        return jsonify({
            'blocos': blocos,
            'depositos': depositos,
            'filtros': {
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'demanda_id': demanda_id,
                'item_demanda_id': item_demanda_id,
                'tipo_bloco': tipo_bloco,
                'data_inicio': data_inicio_str or '',
                'data_fim': data_fim_str or '',
            },
        })
    except Exception as e:
        print(f'Erro na API do histórico consolidado: {str(e)}')
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/movimentar', methods=['GET', 'POST'])
@login_required
def api_movimentar():
    """API para registrar novas movimentações de estoque."""
    try:
        if request.method == 'POST':
            data = request.get_json()
            tipo_movimento = data.get('tipo_movimento')
            produto_id = data.get('produto_id')
            deposito_id = data.get('deposito_id')
            quantidade = float(data.get('quantidade'))
            observacao = data.get('observacao', '')

            usuario = get_current_user()
            user_context = {
                'id': usuario['id'],
                'setor_id': usuario['setor_id'],
                'setor_nome': usuario['setor_nome'],
                'is_admin': usuario['is_admin']
            }

            if not deposito_id:
                from nistiprint_shared.services.app_config_service import app_config_service
                deposito_id = app_config_service.get_config('default_production_deposit_id')

            if not tipo_movimento or not produto_id or quantidade is None or (quantidade == 0 and tipo_movimento != 'BALANCO'):
                return jsonify({'error': 'Dados incompletos.'}), 400

            if deposito_id and not deposito_service.get_by_id(deposito_id):
                return jsonify({'error': 'Depósito inválido.'}), 400

            if tipo_movimento == 'ENTRADA':
                unit_name = data.get('unit_name')
                estoque_service.registrar_entrada(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade=quantidade,
                    observacao=observacao, usuario_id=usuario['id'], unit_name=unit_name,
                    user_context=user_context, operation_id=data.get('operation_id'),
                    idempotency_key=data.get('idempotency_key')
                )
            elif tipo_movimento == 'SAIDA':
                estoque_service.registrar_saida(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade=quantidade,
                    motivo=observacao, usuario_id=usuario['id'],
                    user_context=user_context, operation_id=data.get('operation_id'),
                    idempotency_key=data.get('idempotency_key')
                )
            elif tipo_movimento == 'BALANCO':
                unit_name = data.get('unit_name')
                estoque_service.registrar_balanco(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade_ajuste=quantidade,
                    observacao=observacao, usuario_id=usuario['id'], unit_name=unit_name,
                    user_context=user_context, operation_id=data.get('operation_id'),
                    idempotency_key=data.get('idempotency_key')
                )
            elif tipo_movimento == 'TRANSFERENCIA':
                deposito_destino_id = data.get('deposito_destino_id')
                if not deposito_destino_id:
                    return jsonify({'error': 'Depósito de destino é obrigatório para transferência.'}), 400
                if not deposito_service.get_by_id(deposito_destino_id):
                    return jsonify({'error': 'Depósito de destino inválido.'}), 400

                estoque_service.registrar_transferencia(
                    produto_id=produto_id,
                    deposito_origem_id=deposito_id,
                    deposito_destino_id=deposito_destino_id,
                    quantidade=quantidade,
                    observacao=observacao,
                    usuario_id=usuario['id'],
                    user_context=user_context,
                    operation_id=data.get('operation_id'),
                    idempotency_key=data.get('idempotency_key')
                )
            else:
                return jsonify({'error': 'Tipo de movimento inválido.'}), 400

            saldo_atualizado = estoque_service.get_saldo_atual(produto_id, deposito_id)
            return jsonify({'success': True, 'message': 'Movimentação registrada com sucesso!', 'novo_saldo': saldo_atualizado.get('quantidade', 0)})
        else:
            depositos = deposito_service.get_all()
            return jsonify({'depositos': depositos})

    except EstoqueCommandConflict as e:
        return jsonify({'error': str(e), 'code': 'operation_conflict'}), 409
    except EstoqueCommandOutcomeUnknown as e:
        return jsonify({
            'error': 'Resultado ainda não confirmado; repita com o mesmo identificador de operação.',
            'operation_id': e.operation_id,
        }), 503
    except Exception as e:
        print(f"Erro na API ao registrar movimentação: {str(e)}")
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/posicao', methods=['GET'])
def api_posicao():
    """Página de posição de estoque detalhada (API)."""
    try:
        produto_id = request.args.get('produto_id')
        deposito_id = request.args.get('deposito_id')

        posicao_estoque = estoque_service.get_posicao_estoque(filtro_produtos=[produto_id] if produto_id else None)
        
        if deposito_id:
            posicao_estoque = [p for p in posicao_estoque if p.get('deposito_id') == deposito_id]

        depositos = deposito_service.get_all()
        produtos = product_service.get_all(per_page=1000)

        return jsonify({
            'posicao_estoque': posicao_estoque,
            'depositos': depositos,
            'produtos': produtos,
            'filtro_produto': produto_id,
            'filtro_deposito': deposito_id
        })
    except Exception as e:
        print(f'Erro na API de posição de estoque: {str(e)}')
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/reservas', methods=['GET'])
@login_required
def api_reservas():
    """API para listar todas as reservas de estoque ativas."""
    try:
        saldos_com_reservas = estoque_service.get_all_with_reservations()

        lista_reservas = []
        produto_ids = set()
        deposito_ids = set()

        for saldo in saldos_com_reservas:
            pid = saldo['produto_id']
            did = saldo['deposito_id']
            produto_ids.add(pid)
            deposito_ids.add(did)
            
            detalhes = saldo.get('reservas')
            if detalhes and isinstance(detalhes, list):
                for reserva in detalhes:
                    reserva_info = reserva.copy()
                    reserva_info['produto_id'] = pid
                    reserva_info['deposito_id'] = did
                    lista_reservas.append(reserva_info)
            else:
                lista_reservas.append({
                    'produto_id': pid,
                    'deposito_id': did,
                    'quantidade': saldo['reservado'],
                    'quantidade_original': saldo['reservado'],
                    'quantidade_disponivel': saldo['reservado'],
                    'tipo_ordem': 'reserva_geral',
                    'ordem_id': f"SALDO_{saldo['id']}",
                    'data_reserva': saldo.get('updated_at') or saldo.get('ultima_atualizacao')
                })
        
        prefetched_products = product_service.get_by_ids(list(produto_ids)) if produto_ids else {}
        prefetched_depositos = deposito_service.get_by_ids(list(deposito_ids)) if deposito_ids else {}

        return jsonify({
            'reservas': lista_reservas,
            'prefetched_products': prefetched_products,
            'prefetched_depositos': prefetched_depositos
        })

    except Exception as e:
        print(f'Erro na API de reservas: {str(e)}', 'error')
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/ajuste', methods=['GET', 'POST'])
@login_required
def api_ajuste():
    """API para realizar ajuste de inventário com contagem cega."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            deposito_id = data.get('deposito_id')
            adjustments = data.get('adjustments')

            usuario = get_current_user()
            user_context = {
                'id': usuario['id'],
                'setor_id': usuario['setor_id'],
                'setor_nome': usuario['setor_nome'],
                'is_admin': usuario['is_admin']
            }

            if not deposito_id:
                from nistiprint_shared.services.app_config_service import app_config_service
                deposito_id = app_config_service.get_config('default_production_deposit_id')

            if not deposito_id or not adjustments:
                return jsonify({'error': 'Dados de ajuste inválidos.'}), 400

            success_count = 0
            error_count = 0
            failed_adjustments = []

            for adj in adjustments:
                variance = adj.get('variance')
                if variance != 0:
                    try:
                        estoque_service.registrar_balanco(
                            produto_id=adj['id'],
                            deposito_id=deposito_id,
                            quantidade_ajuste=adj['counted'],
                            observacao=f"Ajuste de inventário via contagem. Contado: {adj['counted']}, Sistema: {adj['system']}",
                            usuario_id=usuario['id'],
                            user_context=user_context,
                            expected_saldo=adj.get('system'),
                            operation_id=adj.get('operation_id'),
                        )
                        success_count += 1
                    except Exception as e:
                        print(f"Erro ao ajustar produto {adj['id']}: {str(e)}")
                        error_count += 1
                        failed_adjustments.append({
                            'produto_id': adj.get('id'),
                            'error': str(e),
                        })

            response_message = []
            if success_count > 0:
                response_message.append(f'{success_count} ajustes aplicados com sucesso.')
            if error_count > 0:
                response_message.append(f'{error_count} ajustes falharam ao serem aplicados.')

            return jsonify({
                'success': error_count == 0,
                'message': ' '.join(response_message),
                'failed_adjustments': failed_adjustments,
            }), (409 if error_count else 200)
        except Exception as e:
            print(f'Erro na API ao processar os ajustes: {str(e)}')
            return jsonify({'error': str(e)}), 500
    else:
        depositos = deposito_service.get_all()
        return jsonify({'depositos': depositos})

@estoque_api_bp.route('/saldo/<produto_id>/<deposito_id>', methods=['GET'])
def api_saldo(produto_id, deposito_id):
    """API para consultar saldo específico"""
    try:
        saldo = estoque_service.get_saldo_atual(produto_id, deposito_id)
        return jsonify(saldo)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/alertas', methods=['GET'])
def api_alertas():
    """API para consultar alertas de estoque"""
    try:
        alertas = estoque_service.get_alertas_estoque()
        return jsonify(alertas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/produtos-busca', methods=['GET'])
def api_produtos_busca():
    """API para busca de produtos com saldos"""
    try:
        q = request.args.get('q', '')
        deposito_id = request.args.get('deposito_id')
        only_marketable = request.args.get('only_marketable', 'false').lower() == 'true'

        if not deposito_id:
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        produtos = product_service.search_produtos(q, limit=50, only_marketable=only_marketable)

        resultados = []
        if produtos and deposito_id:
            produto_ids = [p['id'] for p in produtos]
            saldos_map = estoque_service.get_saldos_em_lote(produto_ids, deposito_id)

            for produto in produtos:
                item = {
                    'id': produto['id'],
                    'text': f"{produto.get('sku', '')} - {produto.get('nome', '')}",
                    'saldo': (saldos_map.get(str(produto['id'])) or {}).get('quantidade', 0)
                }
                resultados.append(item)
        elif produtos:
            for produto in produtos:
                item = {
                    'id': produto['id'],
                    'text': f"{produto.get('sku', '')} - {produto.get('nome', '')}",
                    'saldo': 0
                }
                resultados.append(item)

        return jsonify({'results': resultados})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/liberar-reserva', methods=['POST'])
@login_required
def api_liberar_reserva():
    """API para liberar (cancelar) uma reserva de estoque."""
    try:
        data = request.get_json()
        produto_id = data.get('produto_id')
        deposito_id = data.get('deposito_id')
        ordem_id = data.get('ordem_id')
        operation_id = data.get('operation_id')
        idempotency_key = data.get('idempotency_key')

        if not deposito_id:
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        if not all([produto_id, deposito_id, ordem_id]):
            return jsonify({'success': False, 'error': 'Dados incompletos fornecidos.'}), 400

        usuario = get_current_user()
        user_context = {
            'id': usuario['id'],
            'setor_id': usuario.get('setor_id'),
            'setor_nome': usuario.get('setor_nome'),
            'is_admin': usuario.get('is_admin', False),
        }

        result = estoque_service.liberar_reserva(
            produto_id=produto_id,
            deposito_id=deposito_id,
            ordem_id=ordem_id,
            tipo_ordem=data.get('tipo_ordem') or 'ORDEM',
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            usuario_id=usuario['id'],
            user_context=user_context,
        )
        
        if result:
            return jsonify({'success': True, 'message': 'Reserva liberada com sucesso.'})
        else:
            return jsonify({'success': True, 'message': 'Reserva não encontrada, pode já ter sido liberada.'})

    except ValueError as ve:
        return jsonify({'success': False, 'error': str(ve)}), 400
    except Exception as e:
        print(f"Erro na API ao liberar reserva: {str(e)}")
        return jsonify({'success': False, 'error': 'Ocorreu um erro interno.'}), 500

@estoque_api_bp.route('/saldos-batch', methods=['POST'])
def api_saldos_batch():
    """API para buscar saldos de múltiplos produtos em um depósito."""
    try:
        data = request.get_json(silent=True) or {}
        product_ids = data.get('product_ids')
        deposito_id = data.get('deposito_id')

        if not deposito_id:
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        if not isinstance(product_ids, list) or not product_ids or not deposito_id:
            return jsonify({'error': 'IDs de produto e depósito são obrigatórios.'}), 400

        saldos = estoque_service.get_saldos_em_lote(product_ids, deposito_id)
        return jsonify(saldos)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/reverter-movimentacao', methods=['POST'])
@login_required
def api_reverter_movimentacao():
    """Block reversals until a traceable compensating command is available."""
    try:
        data = request.get_json(silent=True) or {}
        lancamento_id = data.get('lancamento_id')

        if not lancamento_id:
            return jsonify({'success': False, 'error': 'ID do lançamento é obrigatório.'}), 400

        return jsonify({
            'success': False,
            'code': 'compensation_unavailable',
            'error': 'Reversão bloqueada até existir um comando de compensação física rastreável.',
        }), 422
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível avaliar a solicitação de reversão.'}), 503

@estoque_api_bp.route('/movimentar-lote', methods=['POST'])
@login_required
def api_movimentar_lote():
    """API para registrar múltiplas movimentações de estoque em lote."""
    try:
        data = request.get_json(silent=True) or {}
        movimentacoes = data.get('movimentacoes')
        operation_id = data.get('operation_id')

        if not movimentacoes:
            return jsonify({'error': 'Nenhuma movimentação fornecida.'}), 400
        if not operation_id:
            return jsonify({'error': 'operation_id é obrigatório para repetir o lote com segurança.'}), 400

        usuario = get_current_user()
        user_context = {
            'id': usuario['id'],
            'setor_id': usuario['setor_id'],
            'setor_nome': usuario['setor_nome'],
            'is_admin': usuario['is_admin']
        }

        resultado = estoque_service.registrar_movimentacao_lote(
            movimentacoes=movimentacoes,
            usuario_id=usuario['id'],
            user_context=user_context,
            operation_id=operation_id,
            source={'source_type': 'MOVIMENTACAO_LOTE_MANUAL', 'source_id': operation_id},
        )

        movimentos_confirmados = resultado.get('movimentos') or []
        return jsonify({
            'success': True,
            'operation_id': resultado.get('operation_id', operation_id),
            'status': resultado.get('status', 'CONFIRMADO'),
            'sucesso': len(movimentos_confirmados),
            'falhas': 0,
            'detalhes_sucesso': movimentos_confirmados,
            'detalhes_falhas': [],
            'resultado': resultado,
        }), 200
    except EstoqueCommandConflict:
        return jsonify({'error': 'operation_id já foi usado com conteúdo diferente.', 'code': 'idempotency_conflict'}), 409
    except EstoqueCommandOutcomeUnknown as e:
        return jsonify({
            'error': 'O resultado do lote ainda não foi confirmado; repita com o mesmo operation_id.',
            'code': 'outcome_unknown',
            'operation_id': e.operation_id,
        }), 503
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        print(f"Erro na API ao registrar movimentação em lote: {str(e)}")
        return jsonify({'error': 'Não foi possível confirmar o lote de movimentações.'}), 503
