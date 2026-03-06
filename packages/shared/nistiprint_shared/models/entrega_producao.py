from nistiprint_shared.database.database import db
from datetime import datetime

class EntregaProducao(db.Model):
    __tablename__ = 'entrega_producao'

    id = db.Column(db.String(36), primary_key=True)
    item_demanda_id = db.Column(db.Integer, db.ForeignKey('itens_demanda.id'), nullable=True)  # Pode ser nulo para coletas consolidadas
    data_entrega = db.Column(db.Date, nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    demanda_id = db.Column(db.Integer, db.ForeignKey('demandas_producao.id'), nullable=False)
    user_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<EntregaProducao {self.id}>'

# --- Relationships definitions at the bottom ---
EntregaProducao.demanda = db.relationship('DemandaProducao', backref='coletas')
EntregaProducao.item_relacionado = db.relationship('DemandaProducaoItem', back_populates='entregas')
