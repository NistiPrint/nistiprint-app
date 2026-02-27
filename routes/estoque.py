from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, json
from datetime import datetime, timedelta

from services.estoque_service import estoque_service
from services.product_service import product_service
from services.deposito_service import deposito_service
from routes.auth import login_required, get_current_user

estoque_bp = Blueprint('estoque', __name__, url_prefix='/estoque')
estoque_api_bp = Blueprint('estoque_api', __name__, url_prefix='/api/v2/estoque')


# API Estoque routes
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

            # SEGURANÇA: Obter usuário da sessão, ignorar o JSON
            usuario = get_current_user()
            user_context = {
                'id': usuario['id'],
                'setor_id': usuario['setor_id'],
                'setor_nome': usuario['setor_nome'],
                'is_admin': usuario['is_admin']
            }

            # Se o depósito não for especificado, usar o padrão do sistema
            if not deposito_id:
                from services.app_config_service import app_config_service
                deposito_id = app_config_service.get_config('default_production_deposit_id')

            if not all([tipo_movimento, produto_id, quantidade]):
                return jsonify({'error': 'Dados incompletos.'}), 400

            if deposito_id and not deposito_service.get_by_id(deposito_id):
                return jsonify({'error': 'Depósito inválido.'}), 400

            if tipo_movimento == 'ENTRADA':
                unit_name = data.get('unit_name')
                estoque_service.registrar_entrada(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade=quantidade,
                    observacao=observacao, usuario_id=usuario['id'], unit_name=unit_name,
                    user_context=user_context  # Para validação
                )
            elif tipo_movimento == 'SAIDA':
                estoque_service.registrar_saida(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade=quantidade,
                    observacao=observacao, usuario_id=usuario['id'],
                    user_context=user_context  # Para validação
                )
            elif tipo_movimento == 'BALANCO':
                unit_name = data.get('unit_name')
                estoque_service.registrar_balanco(
                    produto_id=produto_id, deposito_id=deposito_id, quantidade_ajuste=quantidade,
                    observacao=observacao, usuario_id=usuario['id'], unit_name=unit_name,
                    user_context=user_context  # Para validação
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
                    user_context=user_context  # Para validação
                )
            else:
                return jsonify({'error': 'Tipo de movimento inválido.'}), 400

            saldo_atualizado = estoque_service.get_saldo_atual(produto_id, deposito_id)
            return jsonify({'success': True, 'message': 'Movimentação registrada com sucesso!', 'novo_saldo': saldo_atualizado.get('quantidade', 0)})
        else: # GET request
            depositos = deposito_service.get_all()
            return jsonify({'depositos': depositos})

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
            
            # Se houver detalhamento (futuro), usamos. 
            # Caso contrário, criamos uma entrada sintética para a UI não ficar vazia
            detalhes = saldo.get('reservas')
            if detalhes and isinstance(detalhes, list):
                for reserva in detalhes:
                    reserva_info = reserva.copy()
                    reserva_info['produto_id'] = pid
                    reserva_info['deposito_id'] = did
                    lista_reservas.append(reserva_info)
            else:
                # Entrada sintética baseada no total reservado
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

            # SEGURANÇA: Obter usuário da sessão, ignorar o JSON
            usuario = get_current_user()
            user_context = {
                'id': usuario['id'],
                'setor_id': usuario['setor_id'],
                'setor_nome': usuario['setor_nome'],
                'is_admin': usuario['is_admin']
            }

            # Se o depósito não for especificado, usar o padrão do sistema
            if not deposito_id:
                from services.app_config_service import app_config_service
                deposito_id = app_config_service.get_config('default_production_deposit_id')

            if not deposito_id or not adjustments:
                return jsonify({'error': 'Dados de ajuste inválidos.'}), 400

            success_count = 0
            error_count = 0

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
                            user_context=user_context  # Para validação
                        )
                        success_count += 1
                    except Exception as e:
                        print(f"Erro ao ajustar produto {adj['id']}: {str(e)}")
                        error_count += 1

            response_message = []
            if success_count > 0:
                response_message.append(f'{success_count} ajustes aplicados com sucesso.')
            if error_count > 0:
                response_message.append(f'{error_count} ajustes falharam ao serem aplicados.')

            return jsonify({'success': True, 'message': ' '.join(response_message)})
        except Exception as e:
            print(f'Erro na API ao processar os ajustes: {str(e)}')
            return jsonify({'error': str(e)}), 500
    else: # GET request
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

        # Se o depósito não for especificado, usar o padrão do sistema
        if not deposito_id:
            from services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        produtos = product_service.search_produtos(q, limit=50, only_marketable=only_marketable)

        resultados = []
        if produtos and deposito_id:
            produto_ids = [p['id'] for p in produtos]
            saldos_map = estoque_service.get_saldos_for_products_in_deposit(produto_ids, deposito_id)

            for produto in produtos:
                item = {
                    'id': produto['id'],
                    'text': f"{produto.get('sku', '')} - {produto.get('nome', '')}",
                    'saldo': saldos_map.get(produto['id'], 0)
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
def api_liberar_reserva():
    """API para liberar (cancelar) uma reserva de estoque."""
    try:
        data = request.get_json()
        produto_id = data.get('produto_id')
        deposito_id = data.get('deposito_id')
        ordem_id = data.get('ordem_id')

        # Se o depósito não for especificado, usar o padrão do sistema
        if not deposito_id:
            from services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        if not all([produto_id, deposito_id, ordem_id]):
            return jsonify({'success': False, 'error': 'Dados incompletos fornecidos.'}), 400

        result = estoque_service.liberar_reserva(
            produto_id=produto_id,
            deposito_id=deposito_id,
            ordem_id=ordem_id
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
        data = request.get_json()
        product_ids = data.get('product_ids')
        deposito_id = data.get('deposito_id')

        # Se o depósito não for especificado, usar o padrão do sistema
        if not deposito_id:
            from services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        if not all([product_ids, deposito_id]):
            return jsonify({'error': 'IDs de produto e depósito são obrigatórios.'}), 400

        saldos = estoque_service.get_saldos_for_products_in_deposit(product_ids, deposito_id)
        return jsonify(saldos)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@estoque_api_bp.route('/reverter-movimentacao', methods=['POST'])
def api_reverter_movimentacao():
    """API para reverter uma movimentação de estoque."""
    try:
        data = request.get_json()
        lancamento_id = data.get('lancamento_id')

        if not lancamento_id:
            return jsonify({'success': False, 'error': 'ID do lançamento é obrigatório.'}), 400

        reversao_id = estoque_service.reverter_movimentacao(lancamento_id=lancamento_id, usuario_id=None)

        return jsonify({'success': True, 'message': f'Lançamento {lancamento_id} revertido com sucesso pelo novo lançamento {reversao_id}.'})

    except ValueError as ve:
        return jsonify({'success': False, 'error': str(ve)}), 400
    except Exception as e:
        print(f"Erro na API ao reverter lançamento: {str(e)}")
        return jsonify({'success': False, 'error': 'Ocorreu um erro interno ao tentar reverter o lançamento.'}), 500


@estoque_api_bp.route('/movimentar-lote', methods=['POST'])
@login_required
def api_movimentar_lote():
    """API para registrar múltiplas movimentações de estoque em lote."""
    try:
        data = request.get_json()
        movimentacoes = data.get('movimentacoes', [])

        if not movimentacoes:
            return jsonify({'error': 'Nenhuma movimentação fornecida.'}), 400

        # SEGURANÇA: Obter usuário da sessão
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
            user_context=user_context
        )

        return jsonify(resultado)

    except Exception as e:
        print(f"Erro na API ao registrar movimentação em lote: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Regular Estoque routes
@estoque_bp.route('/', methods=['GET'])
def dashboard():
    """Dashboard de controle de estoque - Exibe últimas movimentações e resumos."""
    try:
        # Alertas de estoque baixo
        alertas = estoque_service.get_alertas_estoque()

        # Últimas movimentações (filtrar ENTRADA, SAIDA e TRANSFERENCIA)
        todas_movimentacoes = estoque_service.get_recent_movimentacoes(limit=100)  # Buscar mais para compensar filtro
        movimentacoes = [m for m in todas_movimentacoes if m.get('tipo_movimento') in ['ENTRADA', 'SAIDA', 'TRANSFERENCIA_ENTRADA', 'TRANSFERENCIA_SAIDA', 'BALANCO']][:20]
        
        # Pré-carregar produtos e depósitos para evitar N+1 queries no template
        produto_ids = list(set(mov.get('produto_id') for mov in movimentacoes if mov.get('produto_id')))
        deposito_ids = list(set(mov.get('deposito_id') for mov in movimentacoes if mov.get('deposito_id')))
        deposito_origem_ids = list(set(mov.get('deposito_origem_id') for mov in movimentacoes if mov.get('deposito_origem_id')))
        deposito_destino_ids = list(set(mov.get('deposito_destino_id') for mov in movimentacoes if mov.get('deposito_destino_id')))


        all_relevant_deposito_ids = list(set(deposito_ids + deposito_origem_ids + deposito_destino_ids))

        # Pré-carregar com tratamento de erro
        prefetched_products = {}
        prefetched_depositos = {}
        try:
            if produto_ids:
                prefetched_products = product_service.get_by_ids(produto_ids)
            if all_relevant_deposito_ids:
                prefetched_depositos = deposito_service.get_by_ids(all_relevant_deposito_ids)
        except Exception as e:
            print(f"Erro ao pré-carregar dados: {str(e)}")
            # Continuar sem pré-carregamento se falhar

        # Resumo por depósito (para o dashboard)
        depositos = deposito_service.get_all()
        posicao_estoque = estoque_service.get_posicao_estoque() # Posição geral para calcular valor total

        # Pré-carregar custos dos produtos para evitar N+1 queries
        all_products_for_costs = product_service.get_all(per_page=9999) # Ajustar per_page conforme necessário
        product_costs = {p['id']: p.get('cost_price', 0) for p in all_products_for_costs}


        deposito_summary = []
        for deposito in depositos:
            produtos_deposito = [p for p in posicao_estoque if p['deposito_id'] == deposito['id']]
            total_produtos = len(set(p['produto_id'] for p in produtos_deposito)) # Contar produtos únicos
            valor_total = sum(
                p.get('quantidade', 0) * product_costs.get(p['produto_id'], 0)
                for p in produtos_deposito
            )

            deposito_summary.append({
                'deposito': deposito,
                'total_produtos': total_produtos,
                'valor_total': valor_total
            })

        return render_template('estoque/dashboard.html',
                                   alertas=alertas,
                                   movimentacoes=movimentacoes,
                                   deposito_summary=deposito_summary,
                                   depositos=depositos,
                                   prefetched_products=prefetched_products,
                                   prefetched_depositos=prefetched_depositos)

    except Exception as e:
        flash(f'Erro ao carregar dashboard: {str(e)}', 'error')
        return render_template('estoque/dashboard.html')


@estoque_bp.route('/historico', methods=['GET'])
def historico():
    """Página de histórico de movimentações com filtros."""
    try:
        produto_id = request.args.get('produto_id')
        deposito_id = request.args.get('deposito_id')
        tipo_movimento = request.args.get('tipo_movimento')
        data_inicio_str = request.args.get('data_inicio')
        data_fim_str = request.args.get('data_fim')
        limit = int(request.args.get('limit', 100)) # Aumentar limite para histórico detalhado

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

        # Pré-carregar produtos e depósitos para evitar N+1 queries no template
        produto_ids = list(set(mov.get('produto_id') for mov in movimentacoes if mov.get('produto_id')))
        deposito_ids = list(set(mov.get('deposito_id') for mov in movimentacoes if mov.get('deposito_id')))
        deposito_origem_ids = list(set(mov.get('deposito_origem_id') for mov in movimentacoes if mov.get('deposito_origem_id')))
        deposito_destino_ids = list(set(mov.get('deposito_destino_id') for mov in movimentacoes if mov.get('deposito_destino_id')))

        all_relevant_deposito_ids = list(set(deposito_ids + deposito_origem_ids + deposito_destino_ids))

        # Pré-carregar com tratamento de erro
        prefetched_products = {}
        prefetched_depositos = {}
        try:
            if produto_ids:
                prefetched_products = product_service.get_by_ids(produto_ids)
            if all_relevant_deposito_ids:
                prefetched_depositos = deposito_service.get_by_ids(all_relevant_deposito_ids)
        except Exception as e:
            print(f"Erro ao pré-carregar dados para histórico: {str(e)}")
            # Continuar sem pré-carregamento se falhar

        depositos = deposito_service.get_all()

        produto_selecionado = None
        if produto_id:
            produto_selecionado = product_service.get_by_id(produto_id)

        return render_template('estoque/historico.html',
                                   movimentacoes=movimentacoes,
                                   depositos=depositos,
                                   filtro_produto=produto_id,
                                   produto_selecionado=produto_selecionado,
                                   filtro_deposito=deposito_id,
                                   filtro_tipo=tipo_movimento,
                                   filtro_data_inicio=data_inicio_str or '',
                                   filtro_data_fim=data_fim_str or '',
                                   prefetched_products=prefetched_products,
                                   prefetched_depositos=prefetched_depositos)

    except Exception as e:
        flash(f'Erro ao carregar histórico de movimentações: {str(e)}', 'error')
        return render_template('estoque/historico.html')


@estoque_bp.route('/movimentar', methods=['GET', 'POST'])
def movimentar():
    """Página para registrar novas movimentações de estoque."""
    try:
        if request.method == 'POST':
            flash('Este endpoint agora é apenas para renderização HTML. Use a API para movimentações.', 'error')
            return redirect(url_for('estoque.movimentar'))

        # GET request - mostra o formulário
        depositos = deposito_service.get_all()
        return render_template('estoque/movimentar.html', depositos=depositos)

    except Exception as e:
        print(f"Erro ao registrar movimentação: {str(e)}")
        flash(f'Erro ao registrar movimentação: {str(e)}', 'error')
        return render_template('estoque/movimentar.html')


@estoque_bp.route('/posicao', methods=['GET'])
def posicao():
    """Página de posição de estoque detalhada."""
    try:
        produto_id = request.args.get('produto_id')
        deposito_id = request.args.get('deposito_id')

        posicao_estoque = estoque_service.get_posicao_estoque(filtro_produtos=[produto_id] if produto_id else None)
        
        # Filtrar por deposito_id se especificado
        if deposito_id:
            posicao_estoque = [p for p in posicao_estoque if p.get('deposito_id') == deposito_id]

        depositos = deposito_service.get_all()
        produtos = product_service.get_all(per_page=1000) # Para filtros

        return render_template('estoque/posicao.html',
                                   posicao_estoque=posicao_estoque,
                                   depositos=depositos,
                                   produtos=produtos,
                                   filtro_produto=produto_id,
                                   filtro_deposito=deposito_id)
    except Exception as e:
        flash(f'Erro ao carregar posição de estoque: {str(e)}', 'error')
        return render_template('estoque/posicao.html')


@estoque_bp.route('/reservas', methods=['GET'])
def reservas():
    """Página para listar todas as reservas de estoque ativas."""
    try:
        # 1. Buscar todos os documentos de saldo que têm reservas
        saldos_com_reservas = estoque_service.get_all_with_reservations()

        # 2. Aplainar a lista: criar uma lista simples de reservas individuais
        lista_reservas = []
        produto_ids = set()
        deposito_ids = set()

        for saldo in saldos_com_reservas:
            produto_ids.add(saldo['produto_id'])
            deposito_ids.add(saldo['deposito_id'])
            for reserva in saldo.get('reservas', []):
                # Adicionar informações do produto/depósito a cada reserva
                reserva_info = reserva.copy()
                reserva_info['produto_id'] = saldo['produto_id']
                reserva_info['deposito_id'] = saldo['deposito_id']
                lista_reservas.append(reserva_info)
        
        # 3. Pré-carregar nomes de produtos e depósitos
        prefetched_products = product_service.get_by_ids(list(produto_ids)) if produto_ids else {}
        prefetched_depositos = deposito_service.get_by_ids(list(deposito_ids)) if deposito_ids else {}

        # Ordenar por data da reserva, da mais nova para a mais antiga
        lista_reservas.sort(key=lambda r: r.get('data_reserva', datetime.min), reverse=True)

        return render_template('estoque/reservas.html',
                                   reservas=lista_reservas,
                                   prefetched_products=prefetched_products,
                                   prefetched_depositos=prefetched_depositos)

    except Exception as e:
        flash(f'Erro ao carregar a página de reservas: {str(e)}', 'error')
        return render_template('estoque/reservas.html', reservas=[])


@estoque_bp.route('/ajuste', methods=['GET', 'POST'])
def ajuste():
    """Página para realizar ajuste de inventário com contagem cega."""
    if request.method == 'POST':
        try:
            flash('Este endpoint agora é apenas para renderização HTML. Use a API para ajustes.', 'error')
            return redirect(url_for('estoque.ajuste'))

        except Exception as e:
            flash(f'Ocorreu um erro ao processar os ajustes: {str(e)}', 'error')
            return redirect(url_for('estoque.ajuste'))

    # GET request
    depositos = deposito_service.get_all()
    return render_template('estoque/ajuste.html', depositos=depositos)
