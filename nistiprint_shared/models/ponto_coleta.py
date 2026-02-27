from ..database.database import db
from datetime import datetime

class PontoColeta(db.Model):
    __tablename__ = 'pontos_coleta'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    horario_corte_padrao = db.Column(db.Time, nullable=False)
    endereco = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def format_datetime(dt):
            if dt is None:
                return None
            elif isinstance(dt, str):
                return dt
            else:
                return dt.isoformat()

        return {
            'id': self.id,
            'nome': self.nome,
            'horario_corte_padrao': self.horario_corte_padrao.isoformat() if self.horario_corte_padrao else None,
            'endereco': self.endereco,
            'ativo': self.ativo,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
