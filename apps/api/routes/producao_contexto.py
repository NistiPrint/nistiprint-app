"""
Rotas API para Contexto de Produção e Priorização.

Estas rotas fornecem endpoints para:
- Listar demandas ordenadas por prioridade
- Gerenciar regras de priorização
- Gerenciar sinalizações de demanda
- Gerenciar preferências de usuário
- Obter dados para autopreenchimento
"""

from flask import request, jsonify
from routes.auth import get_current_user
from nistiprint_shared.services.contexto_producao_service import contexto_producao_service
from nistiprint_shared.services.priorizacao_service import priorizacao_service
from nistiprint_shared.services.sinalizacao_service import sinalizacao_service
from nistiprint_shared.services.demanda_autofill_service import demanda_autofill_service
from nistiprint_shared.services.user_preference_service import user_preference_service
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from datetime import datetime
import logging

logger = logging.getLogger("ProducaoContextoAPI")


# ============================================================================
# BLUEPRINT FLASK
# ============================================================================

from flask import Blueprint

producao_contexto_bp = Blueprint('producao_contexto', __name__)


# ============================================================================
# ROTAS - CONTEXTO DE PRODUÇÃO
# ============================================================================

@producao_contexto_bp.route('/producao/contexto/ordenacao', methods=['GET'])
def get_producao_ordenada():
    """
    Retorna lista de demandas ordenadas por prioridade para produção.
    
    Query params:
    - canal_venda_id: Filtrar por canal
    - status: Filtrar por status (pode ser múltiplo)
    - modalidade_logistica: Filtrar por modalidade
    - is_flex: Filtrar por FLEX (true/false)
    - limit: Limite de resultados (default: 100)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        # Extrair filtros
        filters = {}
        if request.args.get('canal_venda_id'):
            filters['canal_venda_id'] = int(request.args.get('canal_venda_id'))
        
        if request.args.get('status'):
            filters['status'] = request.args.getlist('status')
        
        if request.args.get('modalidade_logistica'):
            filters['modalidade_logistica'] = request.args.get('modalidade_logistica')
        
        if request.args.get('is_flex') is not None:
            filters['is_flex'] = request.args.get('is_flex').lower() == 'true'

        limit = int(request.args.get('limit', 100))

        # Obter demandas ordenadas
        contextos = contexto_producao_service.get_production_order(filters=filters, limit=limit)

        return jsonify({
            'success': True,
            'data': contextos,
            'total': len(contextos)
        })

    except Exception as e:
        logger.error(f"Erro ao obter produção ordenada: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/contexto/demanda/<demanda_id>', methods=['GET'])
def get_contexto_demanda(demanda_id):
    """
    Retorna contexto completo de uma demanda.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        contexto = contexto_producao_service.build_context_for_demanda(demanda_id)

        if not contexto:
            return jsonify({'success': False, 'error': 'Demanda não encontrada'}), 404

        return jsonify({
            'success': True,
            'data': contexto
        })

    except Exception as e:
        logger.error(f"Erro ao obter contexto da demanda: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/contexto/pedido/<int:pedido_id>', methods=['GET'])
def get_contexto_pedido(pedido_id):
    """
    Retorna contexto completo de um pedido.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        contexto = contexto_producao_service.build_context_for_pedido(pedido_id)

        if not contexto:
            return jsonify({'success': False, 'error': 'Pedido não encontrado'}), 404

        return jsonify({
            'success': True,
            'data': contexto
        })

    except Exception as e:
        logger.error(f"Erro ao obter contexto do pedido: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROTAS - REGRAS DE PRIORIZAÇÃO
# ============================================================================

@producao_contexto_bp.route('/producao/regras-priorizacao', methods=['GET'])
def get_regras_priorizacao():
    """
    Retorna todas as regras de priorização ativas.
    
    Query params:
    - include_inactive: Incluir regras inativas (true/false)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        regras = priorizacao_service.get_all_regras(include_inactive=include_inactive)

        return jsonify({
            'success': True,
            'data': regras,
            'total': len(regras)
        })

    except Exception as e:
        logger.error(f"Erro ao obter regras de priorização: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/regras-priorizacao', methods=['POST'])
def create_regra_priorizacao():
    """
    Cria nova regra de priorização.
    
    Body:
    - nome: string (obrigatório)
    - descricao: string
    - condicoes: object (obrigatório)
    - acao: object (obrigatório)
    - ativa: boolean (default: true)
    - prioridade_regra: integer (default: 0)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()

        # Validações básicas
        if not data.get('nome'):
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        if not data.get('condicoes'):
            return jsonify({'success': False, 'error': 'Condições são obrigatórias'}), 400
        
        if not data.get('acao'):
            return jsonify({'success': False, 'error': 'Ação é obrigatória'}), 400

        regra = priorizacao_service.create_regra(data)

        if not regra:
            return jsonify({'success': False, 'error': 'Erro ao criar regra'}), 500

        return jsonify({
            'success': True,
            'data': regra,
            'message': 'Regra de priorização criada com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao criar regra de priorização: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/regras-priorizacao/<int:regra_id>', methods=['PUT'])
def update_regra_priorizacao(regra_id):
    """
    Atualiza regra de priorização.
    
    Body: Campos para atualizar (nome, descricao, condicoes, acao, ativa, prioridade_regra)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        regra = priorizacao_service.update_regra(regra_id, data)

        if not regra:
            return jsonify({'success': False, 'error': 'Regra não encontrada'}), 404

        return jsonify({
            'success': True,
            'data': regra,
            'message': 'Regra atualizada com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao atualizar regra de priorização: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/regras-priorizacao/<int:regra_id>', methods=['DELETE'])
def delete_regra_priorizacao(regra_id):
    """
    Exclui regra de priorização.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        success = priorizacao_service.delete_regra(regra_id)

        if not success:
            return jsonify({'success': False, 'error': 'Regra não encontrada'}), 404

        return jsonify({
            'success': True,
            'message': 'Regra excluída com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao excluir regra de priorização: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/regras-priorizacao/<int:regra_id>/toggle', methods=['POST'])
def toggle_regra_priorizacao(regra_id):
    """
    Alterna status ativo/inativo de uma regra.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        regra = priorizacao_service.toggle_regra(regra_id)

        if not regra:
            return jsonify({'success': False, 'error': 'Regra não encontrada'}), 404

        return jsonify({
            'success': True,
            'data': regra,
            'message': f'Regra {"ativada" if regra.get("ativa") else "desativada"} com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao alternar regra de priorização: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROTAS - SINALIZAÇÕES DE DEMANDA
# ============================================================================

@producao_contexto_bp.route('/producao/sinalizacoes/demanda/<demanda_id>', methods=['GET'])
def get_sinalizacoes_demanda(demanda_id):
    """
    Retorna sinalizações de uma demanda.
    
    Query params:
    - include_lidas: Incluir sinalizações lidas (true/false)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        include_lidas = request.args.get('include_lidas', 'false').lower() == 'true'
        sinalizacoes = sinalizacao_service.get_sinalizacoes_by_demanda(
            demanda_id,
            include_lidas=include_lidas
        )

        return jsonify({
            'success': True,
            'data': sinalizacoes,
            'total': len(sinalizacoes)
        })

    except Exception as e:
        logger.error(f"Erro ao obter sinalizações: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/sinalizacoes/demanda/<demanda_id>/generate', methods=['POST'])
def generate_sinalizacoes_demanda(demanda_id):
    """
    Gera/atualiza sinalizações de uma demanda.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        sinalizacoes = sinalizacao_service.generate_signals(demanda_id)

        return jsonify({
            'success': True,
            'data': sinalizacoes,
            'total': len(sinalizacoes),
            'message': 'Sinalizações geradas com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao gerar sinalizações: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/sinalizacoes/<int:sinalizacao_id>/read', methods=['POST'])
def mark_sinalizacao_as_read(sinalizacao_id):
    """
    Marca sinalização como lida.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        sinalizacao = sinalizacao_service.mark_as_read(sinalizacao_id)

        if not sinalizacao:
            return jsonify({'success': False, 'error': 'Sinalização não encontrada'}), 404

        return jsonify({
            'success': True,
            'data': sinalizacao,
            'message': 'Sinalização marcada como lida'
        })

    except Exception as e:
        logger.error(f"Erro ao marcar sinalização como lida: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/sinalizacoes/demanda/<demanda_id>/read-all', methods=['POST'])
def mark_all_sinalizacoes_as_read(demanda_id):
    """
    Marca todas as sinalizações de uma demanda como lidas.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        count = sinalizacao_service.mark_all_as_read(demanda_id)

        return jsonify({
            'success': True,
            'data': {'count': count},
            'message': f'{count} sinalizações marcadas como lidas'
        })

    except Exception as e:
        logger.error(f"Erro ao marcar todas como lidas: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROTAS - AUTOPREENCHIMENTO (UX)
# ============================================================================

@producao_contexto_bp.route('/producao/autofill/canal/<int:canal_venda_id>', methods=['GET'])
def get_autofill_canal(canal_venda_id):
    """
    Retorna dados para autopreenchimento baseado em um canal de venda.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        defaults = demanda_autofill_service.get_defaults_for_canal(canal_venda_id)

        return jsonify({
            'success': True,
            'data': defaults
        })

    except Exception as e:
        logger.error(f"Erro ao obter autofill para canal: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/modalidade', methods=['POST'])
def get_autofill_modalidade():
    """
    Retorna dados para autopreenchimento baseado em canal + modalidade.
    
    Body:
    - canal_venda_id: integer (obrigatório)
    - modalidade: string (obrigatório)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        
        canal_venda_id = data.get('canal_venda_id')
        modalidade = data.get('modalidade')

        if not canal_venda_id or not modalidade:
            return jsonify({
                'success': False,
                'error': 'canal_venda_id e modalidade são obrigatórios'
            }), 400

        defaults = demanda_autofill_service.get_defaults_for_modalidade(
            canal_venda_id,
            modalidade
        )

        return jsonify({
            'success': True,
            'data': defaults
        })

    except Exception as e:
        logger.error(f"Erro ao obter autofill para modalidade: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/data-limite', methods=['POST'])
def get_suggested_deadline():
    """
    Calcula data limite de execução sugerida.
    
    Body:
    - produtos: array (obrigatório)
    - data_entrega: string YYYY-MM-DD (obrigatório)
    - horario_coleta: string HH:MM (opcional)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        
        produtos = data.get('produtos', [])
        data_entrega = data.get('data_entrega')
        horario_coleta = data.get('horario_coleta')

        if not data_entrega:
            return jsonify({
                'success': False,
                'error': 'data_entrega é obrigatória'
            }), 400

        result = demanda_autofill_service.get_suggested_deadline(
            produtos,
            data_entrega,
            horario_coleta
        )

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        logger.error(f"Erro ao calcular data limite: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/setores', methods=['POST'])
def get_setores_envolvidos():
    """
    Retorna setores envolvidos baseados nos produtos.
    
    Body:
    - produtos: array (obrigatório)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        produtos = data.get('produtos', [])

        setores = demanda_autofill_service.get_setores_envolvidos(produtos)

        return jsonify({
            'success': True,
            'data': setores
        })

    except Exception as e:
        logger.error(f"Erro ao obter setores: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/validar-horario', methods=['POST'])
def validate_horario_coleta():
    """
    Valida horário de coleta.
    
    Body:
    - horario_coleta: string HH:MM (obrigatório)
    - ponto_coleta_id: integer (opcional)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        
        horario_coleta = data.get('horario_coleta')
        ponto_coleta_id = data.get('ponto_coleta_id')

        if not horario_coleta:
            return jsonify({
                'success': False,
                'error': 'horario_coleta é obrigatório'
            }), 400

        result = demanda_autofill_service.validate_horario_coleta(
            horario_coleta,
            ponto_coleta_id
        )

        status_code = 200 if result['valido'] else 400
        return jsonify({
            'success': result['valido'],
            'data': result
        }), status_code

    except Exception as e:
        logger.error(f"Erro ao validar horário: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/validar-data', methods=['POST'])
def validate_data_entrega():
    """
    Valida data de entrega.
    
    Body:
    - data_entrega: string YYYY-MM-DD (obrigatório)
    - produtos: array (obrigatório)
    - horario_coleta: string HH:MM (opcional)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        
        data_entrega = data.get('data_entrega')
        produtos = data.get('produtos', [])
        horario_coleta = data.get('horario_coleta')

        if not data_entrega:
            return jsonify({
                'success': False,
                'error': 'data_entrega é obrigatória'
            }), 400

        result = demanda_autofill_service.validate_data_entrega(
            data_entrega,
            produtos,
            horario_coleta
        )

        status_code = 200 if result['valido'] else 400
        return jsonify({
            'success': result['valido'],
            'data': result
        }), status_code

    except Exception as e:
        logger.error(f"Erro ao validar data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/autofill/template-obs/<int:canal_venda_id>', methods=['GET'])
def get_template_obs(canal_venda_id):
    """
    Retorna template de observações para um canal.
    
    Query params:
    - variaveis: JSON string com variáveis para substituição
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        variaveis = {}
        if request.args.get('variaveis'):
            import json
            variaveis = json.loads(request.args.get('variaveis'))

        template = demanda_autofill_service.get_template_obs(canal_venda_id, variaveis)

        return jsonify({
            'success': True,
            'data': {'template': template}
        })

    except Exception as e:
        logger.error(f"Erro ao obter template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROTAS - PREFERÊNCIAS DE USUÁRIO
# ============================================================================

@producao_contexto_bp.route('/producao/preferencias', methods=['GET'])
def get_user_preferences():
    """
    Retorna preferências do usuário atual.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        user_id = user.get('id') or user.get('email')
        preferences = user_preference_service.get_preferences(user_id)

        return jsonify({
            'success': True,
            'data': preferences
        })

    except Exception as e:
        logger.error(f"Erro ao obter preferências: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/preferencias', methods=['POST'])
def save_user_preferences():
    """
    Salva preferências do usuário atual.
    
    Body:
    - vista_padrao: string (KANBAN, LISTA, CALENDARIO)
    - ordenacao_padrao: string (PRIORIDADE, HORARIO_CORTE, DATA_ENTREGA)
    - agrupamento_padrao: string (CANAL, MODALIDADE, SETOR, STATUS)
    - auto_fill_enabled: boolean
    - show_suggestions: boolean
    - validate_on_blur: boolean
    - filtros_salvos: array
    - atalhos_personalizados: object
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        user_id = user.get('id') or user.get('email')

        success = user_preference_service.save_preferences(user_id, data)

        if not success:
            return jsonify({
                'success': False,
                'error': 'Erro ao salvar preferências'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Preferências salvas com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao salvar preferências: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/preferencias/filtros', methods=['GET'])
def get_saved_filters():
    """
    Retorna filtros salvos do usuário.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        user_id = user.get('id') or user.get('email')
        filtros = user_preference_service.get_saved_filters(user_id)

        return jsonify({
            'success': True,
            'data': filtros
        })

    except Exception as e:
        logger.error(f"Erro ao obter filtros salvos: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/preferencias/filtros', methods=['POST'])
def save_filter():
    """
    Salva filtro como preset.
    
    Body:
    - nome: string (obrigatório)
    - filtros: object (obrigatório)
    - is_default: boolean (opcional)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        data = request.get_json()
        user_id = user.get('id') or user.get('email')

        if not data.get('nome') or not data.get('filtros'):
            return jsonify({
                'success': False,
                'error': 'nome e filtros são obrigatórios'
            }), 400

        success = user_preference_service.save_filter(user_id, data)

        if not success:
            return jsonify({
                'success': False,
                'error': 'Erro ao salvar filtro'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Filtro salvo com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao salvar filtro: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/preferencias/filtros/<filter_id>', methods=['DELETE'])
def delete_filter(filter_id):
    """
    Exclui filtro salvo.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        user_id = user.get('id') or user.get('email')
        success = user_preference_service.delete_filter(user_id, filter_id)

        if not success:
            return jsonify({
                'success': False,
                'error': 'Erro ao excluir filtro'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Filtro excluído com sucesso'
        })

    except Exception as e:
        logger.error(f"Erro ao excluir filtro: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@producao_contexto_bp.route('/producao/preferencias/auto-fill/toggle', methods=['POST'])
def toggle_auto_fill():
    """
    Alterna estado do autopreenchimento.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Não autorizado'}), 401

        user_id = user.get('id') or user.get('email')
        new_state = user_preference_service.toggle_auto_fill(user_id)

        return jsonify({
            'success': True,
            'data': {'auto_fill_enabled': new_state},
            'message': f'Autopreenchimento {"ativado" if new_state else "desativado"}'
        })

    except Exception as e:
        logger.error(f"Erro ao alternar autopreenchimento: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
