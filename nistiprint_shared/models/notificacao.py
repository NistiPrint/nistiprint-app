from ..database.database import db
from datetime import datetime

class Notificacao(db.Model):
    __tablename__ = 'notificacoes'

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(50))  # alerta, informativo, erro
    nivel_critica = db.Column(db.String(20), default='MEDIA')  # baixa, media, alta
    destinatarios = db.Column(db.JSON)  # Who should receive the notification
    lida = db.Column(db.Boolean, default=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)
    data_visualizacao = db.Column(db.DateTime)
    dados_adicionais = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def format_datetime(dt):
            if dt is None:
                return None
            elif isinstance(dt, str):
                return dt  # Already a string from Supabase
            else:
                return dt.isoformat()  # Convert datetime object to string

        return {
            'id': self.id,
            'titulo': self.titulo,
            'mensagem': self.mensagem,
            'tipo': self.tipo,
            'nivel_critica': self.nivel_critica,
            'destinatarios': self.destinatarios,
            'lida': self.lida,
            'data_envio': format_datetime(self.data_envio),
            'data_visualizacao': format_datetime(self.data_visualizacao),
            'dados_adicionais': self.dados_adicionais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }