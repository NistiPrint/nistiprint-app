from flask import Blueprint, request, jsonify
from nistiprint_shared.services.report_service import (
    get_dados_gerenciais_diarios, 
    get_dados_gerenciais_demanda,
    get_sulfite_usage_report,
    get_producao_history
)
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.consumption_service import consumption_service
from nistiprint_shared.services.purchasing_advisor_service import purchasing_advisor_service
from datetime import datetime, timedelta

relatorios_api_bp = Blueprint('relatorios_api', __name__, url_prefix='/api/v2/relatorios')

@relatorios_api_bp.route('/', methods=['GET'])
def relatorios_index():
    """
    Retorna informações gerais sobre relatórios, incluindo o sulfite_report real.
    """
    try:
        sulfite_report = get_sulfite_usage_report()
        return jsonify({
            'success': True,
            'sulfite_report': sulfite_report
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@relatorios_api_bp.route('/gerenciais/diario', methods=['GET'])
def dados_gerenciais_diarios():
    """Retorna os dados gerenciais agregados por dia."""
    data = request.args.get('data')
    try:
        dados = get_dados_gerenciais_diarios(data)
        return jsonify({
            'success': True,
            'data': dados
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/gerenciais/demanda', methods=['GET'])
def dados_gerenciais_demanda():
    """Retorna os dados gerenciais detalhados por demanda."""
    demanda_id = request.args.get('demanda_id')
    if demanda_id:
        try:
            demanda_id = int(demanda_id)
        except ValueError:
            return jsonify({'success': False, 'error': 'demanda_id deve ser inteiro'}), 400

    try:
        dados = get_dados_gerenciais_demanda(demanda_id)
        return jsonify({
            'success': True,
            'data': dados
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/historico-producao', methods=['GET'])
def historico_producao():
    """Retorna o histórico detalhado de logs de produção (paginado)."""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        result = get_producao_history(page, per_page)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/abc', methods=['GET'])
def api_relatorio_abc():
    """Relatório Curva ABC."""
    try:
        days = int(request.args.get('days', 30))
        abc_data = estoque_service.get_abc_analysis(days=days)
        return jsonify(abc_data), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/valorizacao', methods=['GET'])
def api_relatorio_valorizacao():
    """Relatório de Valorização de Estoque."""
    try:
        valuation = estoque_service.get_inventory_valuation()
        total_geral = sum(item['valor_total'] for item in valuation)
        return jsonify({
            'success': True,
            'items': valuation,
            'total_geral': total_geral,
            'data_referencia': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/stock-forecast', methods=['GET'])
def stock_forecast_report():
    """
    Retorna uma previsão de esgotamento de estoque para insumos.
    """
    try:
        days = int(request.args.get('days', 30))
        daily_consumptions = consumption_service.get_daily_consumption(days=days)
        
        forecast_data = []
        for product_id, consumption_info in daily_consumptions.items():
            # Fetch current stock for the product
            # This would ideally come from estoque_service or a direct query
            # For now, a simplified approach
            estoque_response = supabase_db.client.table('estoque_atual').select("saldo_atual")\
                .eq('produto_id', product_id).limit(1).single().execute()
            saldo_atual = estoque_response.data['saldo_atual'] if estoque_response.data else 0

            if consumption_info['media_diaria'] > 0:
                dias_restantes = saldo_atual / consumption_info['media_diaria']
                data_esgotamento = (datetime.utcnow() + timedelta(days=dias_restantes)).strftime('%Y-%m-%d')
            else:
                dias_restantes = "N/A"
                data_esgotamento = "Consumo Zero"

            # Fetch product name (simplified)
            product_name_res = supabase_db.client.table('produtos').select("nome").eq('id', product_id).single().execute()
            produto_nome = product_name_res.data['nome'] if product_name_res.data else f"Produto ID: {product_id}"

            forecast_data.append({
                'produto_id': product_id,
                'produto_nome': produto_nome,
                'saldo_atual': saldo_atual,
                'media_diaria_consumo': round(consumption_info['media_diaria'], 2),
                'dias_restantes_estoque': round(dias_restantes, 2) if isinstance(dias_restantes, (int, float)) else dias_restantes,
                'data_esgotamento_estimada': data_esgotamento
            })

        return jsonify({
            'success': True,
            'forecast': forecast_data
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@relatorios_api_bp.route('/purchase-suggestions', methods=['GET'])
def purchase_suggestions_report():
    """
    Retorna sugestões de compra de insumos com base no ROP.
    """
    try:
        days = int(request.args.get('days', 30))
        recommendations = purchasing_advisor_service.generate_purchase_recommendations(days_of_consumption_history=days)
        return jsonify({
            'success': True,
            'suggestions': recommendations
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500





