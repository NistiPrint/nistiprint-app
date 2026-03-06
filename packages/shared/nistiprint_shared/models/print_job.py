from nistiprint_shared.database.database import db
from datetime import datetime

class PrintJob(db.Model):
    __tablename__ = 'print_jobs'

    id = db.Column(db.Integer, primary_key=True)
    demanda_item_id = db.Column(db.Integer, db.ForeignKey('itens_demanda.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)
    artwork_id = db.Column(db.Integer, db.ForeignKey('product_artworks.id'), nullable=True)
    tipo_arquivo = db.Column(db.String(50))
    status = db.Column(db.String(50), default='pendente')
    impressora_alvo = db.Column(db.String(255), nullable=True)
    quantidade = db.Column(db.Integer, default=1)  # Added quantity column
    tentativas = db.Column(db.Integer, default=0)
    logs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    demanda_item = db.relationship('DemandaProducaoItem', backref=db.backref('print_jobs', lazy=True))
    produto = db.relationship('Product')
    artwork = db.relationship('ProductArtwork')

    def to_dict(self):
        def format_datetime(dt):
            if dt is None: return None
            if isinstance(dt, str): return dt
            return dt.isoformat()

        return {
            'id': self.id,
            'demanda_item_id': self.demanda_item_id,
            'product_id': self.product_id,
            'artwork_id': self.artwork_id,
            'tipo_arquivo': self.tipo_arquivo,
            'status': self.status,
            'impressora_alvo': self.impressora_alvo,
            'quantidade': self.quantidade,
            'tentativas': self.tentativas,
            'logs': self.logs,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
