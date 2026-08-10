import logging
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from routes.auth import login_required
from nistiprint_shared.services.ai_personalization_service import process_orders
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.bling_order_processing_service import import_single_order_by_shop_id
from nistiprint_shared.database.supabase_db_service import supabase_db

ferramentas_bp = Blueprint('ferramentas', __name__)
ferramentas_api_bp = Blueprint('ferramentas_api', __name__, url_prefix='/api/v2/ferramentas')

# API Ferramentas routes
@ferramentas_api_bp.route('/associacao-massa', methods=['POST'])
@login_required
def api_associacao_massa():
    try:
        data = request.get_json()
        component_id = data.get('component_id')
        quantity = data.get('quantity')
        target_ids = data.get('target_ids')

        if not component_id or not quantity or not target_ids:
            return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400

        result = product_service.add_bom_component_to_multiple_products(component_id, float(quantity), target_ids)
        
        return jsonify({
            'success': True,
            'message': f"Processado. Sucessos: {len(result['success'])}, Erros: {len(result['errors'])}",
            'details': result
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@ferramentas_api_bp.route('/ressincronizar/contas', methods=['GET'])
@login_required
def api_ressincronizar_contas():
    """Contas de marketplace ressincronizáveis, com a rota de origem de cada uma."""
    try:
        from nistiprint_shared.services.ressincronizacao_service import listar_contas_marketplace
        return jsonify({'success': True, 'data': listar_contas_marketplace()})
    except Exception as e:
        logging.getLogger(__name__).error('Erro ao listar contas: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@ferramentas_api_bp.route('/ressincronizar', methods=['POST'])
@login_required
def api_ressincronizar():
    """Relê os pedidos pendentes de uma conta na origem e reprocessa pela pipeline.

    Body: {"integration_id": int, "dias": int, "limite": int|null}

    Não escreve em `pedidos` diretamente: devolve cada pedido para a mesma
    pipeline do webhook (Shopee/ML) ou para o fetch do Bling por loja. É o que
    garante que a ferramenta de corrigir incoerência não vire fonte de outra.
    """
    try:
        from nistiprint_shared.services.ressincronizacao_service import ressincronizar_conta

        data = request.get_json() or {}
        integration_id = data.get('integration_id')
        if not integration_id:
            return jsonify({'success': False, 'message': 'integration_id é obrigatório.'}), 400

        resultado = ressincronizar_conta(
            int(integration_id),
            dias=int(data.get('dias') or 7),
            limite=int(data['limite']) if data.get('limite') else None,
        )
        if resultado.get('status') == 'ERRO':
            return jsonify({'success': False, 'message': resultado.get('message')}), 404

        return jsonify({
            'success': True,
            'message': (f"{resultado.get('processados', 0)} de "
                        f"{resultado.get('listados', 0)} pedidos ressincronizados."),
            'data': resultado,
        })
    except Exception as e:
        logging.getLogger(__name__).error('Erro na ressincronização: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@ferramentas_api_bp.route('/ressincronizar-pendentes', methods=['POST'])
@login_required
def api_ressincronizar_pendentes():
    """Relê na origem todo pedido que ainda está numa situação não-final.

    Body: {"origens": [str]|null, "situacoes": [int]|null,
           "limite": int, "dry_run": bool}

    Complementa `/ressincronizar`, que parte da origem e filtra por data de
    criação — e por isso não alcança o pedido que ficou defasado fora da
    janela de dias. Aqui a varredura parte da nossa base, então a idade do
    pedido não importa.
    """
    try:
        from nistiprint_shared.services.ressincronizacao_service import (
            ressincronizar_pendentes,
        )

        data = request.get_json() or {}
        resultado = ressincronizar_pendentes(
            origens=data.get('origens') or None,
            situacoes=data.get('situacoes') or None,
            limite=int(data.get('limite') or 200),
            dry_run=bool(data.get('dry_run')),
        )

        if resultado.get('dry_run'):
            mensagem = f"{resultado.get('listados', 0)} pedidos seriam ressincronizados."
        else:
            mensagem = (f"{resultado.get('processados', 0)} de "
                        f"{resultado.get('listados', 0)} pedidos ressincronizados.")

        return jsonify({'success': True, 'message': mensagem, 'data': resultado})
    except Exception as e:
        logging.getLogger(__name__).error(
            'Erro na ressincronização de pendentes: %s', e, exc_info=True
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@ferramentas_api_bp.route('/marcar-entregues-ate', methods=['POST'])
@login_required
def api_marcar_entregues_ate():
    """Corte historico: marca pedidos ainda pendentes (Em Aberto, Em Andamento,
    Produzido, Pronto para Envio, Enviado) como Entregue e os tira da torre de
    despacho. Cancelado, Entregue e Devolvido sao situacoes finais e nunca sao
    alterados por esta rota.

    Contexto: `pedidos.despachado_em` e coluna nova e so foi backfillada para
    pedidos ligados a demandas publicadas. Todo pedido que nunca passou por
    demanda ficou aparecendo na torre como backlog aberto. Para os que ainda
    estao em situacao pendente com data de venda antiga, a causa mais provavel
    e falta de atualizacao de status — nao trabalho pendente de verdade.

    Body: {"data": "YYYY-MM-DD", "dry_run": true|false}

    `dry_run=true` (default) devolve a previa por situacao atual, sem alterar
    nada. So com `dry_run=false` a operacao e aplicada — e o estado anterior vai
    para `manutencao_status_log`, permitindo desfazer pelo lote retornado.
    """
    try:
        data = request.get_json() or {}
        data_corte = data.get('data')
        dry_run = data.get('dry_run', True)

        if not data_corte:
            return jsonify({'success': False, 'message': 'Data de corte é obrigatória.'}), 400

        result = supabase_db.rpc('manutencao_marcar_entregues_ate', {
            'p_data': data_corte,
            'p_dry_run': bool(dry_run),
            'p_executado_por': 'Ferramentas',
        }).execute()

        linhas = result.data or []
        detalhes = [
            {'situacao_anterior': r.get('out_situacao_anterior'), 'quantidade': r.get('out_qtd')}
            for r in linhas
        ]
        total = sum(d['quantidade'] or 0 for d in detalhes)
        lote = linhas[0].get('out_lote') if linhas else None

        if dry_run:
            mensagem = (f'Prévia: {total} pedidos seriam marcados como Entregue.'
                        if total else 'Nenhum pedido pendente travado encontrado até essa data.')
        else:
            mensagem = f'{total} pedidos marcados como Entregue e removidos da torre.'

        return jsonify({
            'success': True,
            'dry_run': bool(dry_run),
            'message': mensagem,
            'total': total,
            'lote': lote if not dry_run else None,
            'detalhes': detalhes,
        })
    except Exception as e:
        logging.getLogger(__name__).error('Erro em marcar-entregues-ate: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@ferramentas_api_bp.route('/desfazer-lote-manutencao', methods=['POST'])
@login_required
def api_desfazer_lote_manutencao():
    """Restaura situacao_pedido_id e despachado_em ao estado anterior ao lote."""
    try:
        data = request.get_json() or {}
        lote = data.get('lote')
        if not lote:
            return jsonify({'success': False, 'message': 'Lote é obrigatório.'}), 400

        result = supabase_db.rpc('manutencao_desfazer_lote', {'p_lote': lote}).execute()
        total = result.data if isinstance(result.data, int) else (result.data or 0)

        return jsonify({
            'success': True,
            'message': f'{total} pedidos restaurados ao estado anterior.',
            'total': total,
        })
    except Exception as e:
        logging.getLogger(__name__).error('Erro em desfazer-lote-manutencao: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@ferramentas_api_bp.route('/importar_pedido_bling', methods=['POST'])
@login_required
def api_importar_pedido_bling():
    data = request.get_json()
    numero_loja = data.get('numero_loja')

    if not numero_loja:
        return jsonify({'success': False, 'message': 'Número do pedido é obrigatório.'}), 400

    try:
        success, message = import_single_order_by_shop_id(numero_loja)
        return jsonify({'success': success, 'message': message}), 200 if success else 400
    except Exception as e:
        error_msg = f'Ocorreu um erro inesperado: {str(e)}'
        return jsonify({'success': False, 'message': error_msg}), 500

@ferramentas_api_bp.route('/processar_nomes_ia', methods=['POST'])
@login_required
def api_processar_nomes_ia():
    try:
        data = request.get_json() or {}
        logger = logging.getLogger(__name__)
        logger.info("=== INÍCIO: Processamento IA === Payload: %s", data)

        limit = data.get('limit')
        shopee_order_sn = data.get('shopee_order_sn')

        # Limit handling
        if limit and str(limit).isdigit():
            limit = int(limit)
        else:
            limit = None

        # Robust handling of order_sn
        if shopee_order_sn == "":
            shopee_order_sn = None

        logger.info("Parâmetros: limit=%s, order_sn=%s", limit, shopee_order_sn)

        success, message = process_orders(limit=limit, order_sn=shopee_order_sn)

        logger.info("=== FIM: Processamento IA === success=%s, message=%s", success, message)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        logging.getLogger(__name__).error("ERRO: Processamento IA falhou: %s", e, exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Erro ao processar: {str(e)}'
        }), 500

@ferramentas_api_bp.route('/update_product_status', methods=['POST'])
@login_required
def api_update_product_status():
    try:
        products, _ = product_service.get_products(per_page=10000)
        updated_count = 0
        for product in products:
            product_service.update(product['id'], {'status': 'ativo'})
            updated_count += 1
        return jsonify({
            'success': True,
            'message': f'{updated_count} products updated to status \'ativo\'.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating products: {str(e)}'
        }), 500

# Regular Ferramentas routes
@ferramentas_bp.route('/ferramentas')
@login_required
def ferramentas():
    return render_template('ferramentas.html')

@ferramentas_bp.route('/ferramentas/importar_pedido_bling', methods=['POST'])
@login_required
def importar_pedido_bling():
    numero_loja = request.form.get('numero_loja')

    if not numero_loja:
        flash('Número do pedido é obrigatório.', 'warning')
        return redirect(url_for('ferramentas.ferramentas'))

    try:
        success, message = import_single_order_by_shop_id(numero_loja)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    except Exception as e:
        error_msg = f'Ocorreu um erro inesperado: {str(e)}'
        flash(error_msg, 'danger')

    return redirect(url_for('ferramentas.ferramentas'))

@ferramentas_bp.route('/ferramentas/converter_pedidos')
@login_required
def converter_pedidos():
    return render_template('ferramentas/converter_pedidos.html')


@ferramentas_bp.route('/ferramentas/identificar_nomes_ia')
@login_required
def identificar_nomes_ia():
    return render_template('ferramentas/identificar_nomes_ia.html')


@ferramentas_bp.route('/ferramentas/associacao-massa')
@login_required
def associacao_massa():
    categories = category_service.get_all_categories()
    tags = tag_service.get_all_tags()
    return render_template('ferramentas/associacao_massa.html', categories=categories, tags=tags)







