from ..database.database import db
from datetime import datetime

class AiExecutionLog(db.Model):
    __tablename__ = 'log_execucao_ia'  # ai_execution_log → log_execucao_ia

    id = db.Column(db.Integer, primary_key=True)
    nome_funcionalidade = db.Column(db.String(255))  # Novo campo
    data_execucao = db.Column(db.DateTime, default=datetime.utcnow)  # executed_at → data_execucao
    parametros_entrada = db.Column(db.JSON)  # input_data → parametros_entrada (JSON)
    resultado_modelo = db.Column(db.JSON)  # model_result → resultado_modelo (JSON)
    duracao_execucao_ms = db.Column(db.Integer)  # Novo campo
    sucesso = db.Column(db.Boolean, default=True)  # status → sucesso (boolean)
    mensagem_erro = db.Column(db.Text)  # error_message → mensagem_erro
    codigo_pedido = db.Column(db.String(50))  # order_sn → codigo_pedido (compatibilidade)
    chat_context = db.Column(db.JSON)  # Mantido como JSON
    extracted_personalization = db.Column(db.JSON)  # Mantido como JSON
    user_feedback_id = db.Column(db.Integer)  # Mantido

    def __repr__(self):
        return f'<AiExecutionLog {self.codigo_pedido} - {self.sucesso}>'  # order_sn → codigo_pedido, status → sucesso
