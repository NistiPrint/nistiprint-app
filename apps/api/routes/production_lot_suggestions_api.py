# ============================================================================
# APOSENTADO - sugestoes automaticas de lote / rascunho automatico (27/08/2026)
# ============================================================================
#
# Estas rotas alimentavam a aba "Sugestoes e rascunhos" da tela de Demandas.
# O servico por tras (ProductionLotSuggestionsService) agrupava pedidos por
# conta propria e oferecia um lote pronto para confirmar — um segundo lugar,
# alem da Torre de Despacho, onde uma demanda podia nascer.
#
# Dois lugares para o mesmo ato e o problema, nao a duplicacao de codigo: o
# total sugerido aqui nunca foi conferido contra o painel de nenhum
# marketplace, e nada impedia que o mesmo pedido entrasse num lote sugerido e
# num lote da torre. A demanda agora nasce em um lugar so:
#
#   despacho_lancar_lote      -> monta/soma a consolidacao do no
#   despacho_publicar_demanda -> publica e carimba despachado_em
#
# As rotas continuam respondendo 410 em vez de sumir: um frontend em cache ou
# uma aba aberta desde ontem precisa receber a explicacao, nao um 404 que
# parece indisponibilidade temporaria e convida a repetir a chamada.

from flask import jsonify

from routes.auth import login_required

from .demanda_producao_base import demanda_producao_api_bp

_APOSENTADO = {
    "success": False,
    "error": "endpoint_aposentado",
    "message": (
        "As sugestoes automaticas de lote foram encerradas em 27/08/2026. "
        "Monte o lote na Torre de Despacho: escolha o no (marketplace + "
        "modalidade), confira o total contra o painel do marketplace, emita as "
        "notas, imprima os papeis e publique a demanda."
    ),
    "substituto": {
        "tela": "/despacho",
        "rpc_montar": "despacho_lancar_lote",
        "rpc_publicar": "despacho_publicar_demanda",
    },
}


@demanda_producao_api_bp.route("/lote-suggestions", methods=["GET"])
@login_required
def list_lote_suggestions():
    """Aposentado. A consolidacao nasce na Torre de Despacho."""
    return jsonify(dict(_APOSENTADO)), 410


@demanda_producao_api_bp.route("/lote-suggestions/<path:suggestion_key>", methods=["GET"])
@login_required
def get_lote_suggestion_detail(suggestion_key):
    """Aposentado. A consolidacao nasce na Torre de Despacho."""
    return jsonify(dict(_APOSENTADO, suggestion_key=suggestion_key)), 410


@demanda_producao_api_bp.route("/lote-suggestions/confirm", methods=["POST"])
@login_required
def confirm_lote_suggestion():
    """Aposentado. A consolidacao nasce na Torre de Despacho."""
    return jsonify(dict(_APOSENTADO)), 410
