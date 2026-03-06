from nistiprint_shared.database.database import db
from datetime import datetime

class RegraLogistica(db.Model):
    __tablename__ = 'regras_logisticas_canal'

    id = db.Column(db.Integer, primary_key=True)
    canal_venda_id = db.Column(db.Integer, db.ForeignKey('canais_venda.id'), nullable=False)
    modalidade = db.Column(db.String(50), nullable=False) # STANDARD, EXPRESS, FULFILLMENT, RETIRADA
    tipo_envio = db.Column(db.String(50), nullable=False) # COLETA_LOCAL, PONTO_COLETA
    horario_limite = db.Column(db.Time, nullable=False)
    ponto_coleta_id = db.Column(db.Integer, db.ForeignKey('pontos_coleta.id'), nullable=True)
    prioridade_uso = db.Column(db.Integer, default=1)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'canal_venda_id': self.canal_venda_id,
            'modalidade': self.modalidade,
            'tipo_envio': self.tipo_envio,
            'horario_limite': self.horario_limite.isoformat() if self.horario_limite else None,
            'ponto_coleta_id': self.ponto_coleta_id,
            'ponto_coleta_nome': self.ponto_coleta.nome if self.ponto_coleta else None,
            'prioridade_uso': self.prioridade_uso
        }

# --- Relationships definitions at the bottom ---
RegraLogistica.canal_venda = db.relationship('CanalVenda', backref=db.backref('regras_logisticas_list', cascade="all, delete-orphan"))
RegraLogistica.ponto_coleta = db.relationship('PontoColeta', backref='regras_vinculadas')

