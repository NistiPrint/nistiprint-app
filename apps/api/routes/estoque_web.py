from flask import request, jsonify, render_template, flash, redirect, url_for
from datetime import datetime
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.deposito_service import deposito_service
from .estoque_base import estoque_bp

@estoque_bp.route('/', methods=['GET'])
def dashboard():
    """Dashboard de controle de estoque - Exibe últimas movimentações e resumos."""
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
        
        if deposito_id:
            posicao_estoque = [p for p in posicao_estoque if p.get('deposito_id') == deposito_id]

        depositos = deposito_service.get_all()
        produtos = product_service.get_all(per_page=1000)

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
        saldos_com_reservas = estoque_service.get_all_with_reservations()

        lista_reservas = []
        produto_ids = set()
        deposito_ids = set()

        for saldo in saldos_com_reservas:
            produto_ids.add(saldo['produto_id'])
            deposito_ids.add(saldo['deposito_id'])
            for reserva in saldo.get('reservas', []):
                reserva_info = reserva.copy()
                reserva_info['produto_id'] = saldo['produto_id']
                reserva_info['deposito_id'] = saldo['deposito_id']
                lista_reservas.append(reserva_info)
        
        prefetched_products = product_service.get_by_ids(list(produto_ids)) if produto_ids else {}
        prefetched_depositos = deposito_service.get_by_ids(list(deposito_ids)) if deposito_ids else {}

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

    depositos = deposito_service.get_all()
    return render_template('estoque/ajuste.html', depositos=depositos)
