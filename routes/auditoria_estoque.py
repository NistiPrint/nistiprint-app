from flask import Blueprint, request, jsonify
from datetime import datetime
from services.auditoria_estoque_service import auditoria_estoque_service
from routes.auth import login_required, get_current_user

auditoria_estoque_bp = Blueprint('auditoria_estoque', __name__, url_prefix='/api/v2/auditoria')

@auditoria_estoque_bp.route('/contar', methods=['POST'])
@login_required
def registrar_contagem():
    """Registra uma nova contagem física de estoque."""
    try:
        data = request.get_json()
        produto_id = data.get('produto_id')
        deposito_id = data.get('deposito_id')
        quantidade_contada = data.get('quantidade_contada')
        observacao = data.get('observacao')
        sessao_id = data.get('sessao_id')
        
        # Validações básicas
        if produto_id is None or deposito_id is None or quantidade_contada is None:
            return jsonify({'error': 'Dados incompletos (produto_id, deposito_id, quantidade_contada obrigatórios).'}), 400
            
        usuario = get_current_user()
        usuario_id = usuario['id']
        
        resultado = auditoria_estoque_service.registrar_contagem(
            produto_id=int(produto_id),
            deposito_id=int(deposito_id),
            quantidade_contada=float(quantidade_contada),
            usuario_id=usuario_id,
            observacao=observacao,
            sessao_id=sessao_id
        )
        
        return jsonify({'success': True, 'data': resultado})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auditoria_estoque_bp.route('/pendencias', methods=['GET'])
@login_required
def listar_pendencias():
    """Lista contagens pendentes de aprovação."""
    try:
        deposito_id = request.args.get('deposito_id')
        if deposito_id:
            deposito_id = int(deposito_id)
            
        pendencias = auditoria_estoque_service.listar_contagens(
            status='PENDENTE',
            deposito_id=deposito_id
        )
        return jsonify(pendencias)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auditoria_estoque_bp.route('/historico', methods=['GET'])
@login_required
def listar_historico():
    """Lista histórico de auditorias."""
    try:
        produto_id = request.args.get('produto_id')
        deposito_id = request.args.get('deposito_id')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        status = request.args.get('status')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
        
        if produto_id: produto_id = int(produto_id)
        if deposito_id: deposito_id = int(deposito_id)
        
        historico = auditoria_estoque_service.listar_contagens(
            status=status,
            produto_id=produto_id,
            deposito_id=deposito_id,
            start_date=start_date,
            end_date=end_date
        )
        return jsonify(historico)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auditoria_estoque_bp.route('/<int:contagem_id>/aprovar', methods=['POST'])
@login_required
def aprovar_contagem(contagem_id):
    """Aprova uma contagem pendente e ajusta o estoque."""
    try:
        usuario = get_current_user()
        # Idealmente verificar permissão de gerente/admin aqui
        
        resultado = auditoria_estoque_service.aprovar_contagem(
            contagem_id=contagem_id,
            usuario_aprovador_id=usuario['id']
        )
        return jsonify({'success': True, 'data': resultado})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auditoria_estoque_bp.route('/<int:contagem_id>/rejeitar', methods=['POST'])
@login_required
def rejeitar_contagem(contagem_id):
    """Rejeita uma contagem pendente."""
    try:
        usuario = get_current_user()
        
        resultado = auditoria_estoque_service.rejeitar_contagem(
            contagem_id=contagem_id,
            usuario_aprovador_id=usuario['id']
        )
        return jsonify({'success': True, 'data': resultado})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
