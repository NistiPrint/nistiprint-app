from datetime import datetime
from flask import Blueprint, render_template
from services.firebase.firestore_client import firestore_client

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Página principal que testa a conexão com o Firestore."""

    try:
        # Teste de conexão: tenta criar e ler um documento de teste
        test_doc = firestore_client.collection('test').document('connection_test')

        # Salva um documento de teste
        test_data = {
            'message': 'Teste de conexão com Firestore',
            'timestamp': datetime.utcnow(),
            'status': 'OK'
        }
        test_doc.set(test_data)

        # Tenta ler o documento de volta
        doc_snapshot = test_doc.get()
        if doc_snapshot.exists:
            firestore_status = 'Conectado com sucesso!'
            connection_status = 'OK'
        else:
            firestore_status = 'Documento de teste não encontrado'
            connection_status = 'Erro'

    except Exception as e:
        firestore_status = f'Erro na conexão: {str(e)}'
        connection_status = 'Erro'

    return render_template(
        'index.html',
        firestore_status=firestore_status,
        connection_status=connection_status,
        timestamp=datetime.now()
    )
