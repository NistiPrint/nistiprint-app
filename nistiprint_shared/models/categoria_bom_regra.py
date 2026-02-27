from ..database.database import db
from datetime import datetime

class CategoriaBOMRegra(db.Model):
    __tablename__ = 'categoria_bom_regras'

    id = db.Column(db.Integer, primary_key=True)
    categoria_pai_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=False)
    nome_grupo = db.Column(db.String(255), nullable=False)
    categoria_componente_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=False)
    min_quantidade = db.Column(db.Numeric(10, 2), default=1.0)
    max_quantidade = db.Column(db.Numeric(10, 2), default=1.0)
    ordem = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'categoria_pai_id': self.categoria_pai_id,
            'nome_grupo': self.nome_grupo,
            'categoria_componente_id': self.categoria_componente_id,
            'categoria_componente_nome': self.categoria_componente.nome if self.categoria_componente else None,
            'min_quantidade': float(self.min_quantidade),
            'max_quantidade': float(self.max_quantidade),
            'ordem': self.ordem,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

# --- Relationships definitions at the bottom ---
CategoriaBOMRegra.categoria_pai = db.relationship('Categoria', foreign_keys=[CategoriaBOMRegra.categoria_pai_id], backref='bom_regras')
CategoriaBOMRegra.categoria_componente = db.relationship('Categoria', foreign_keys=[CategoriaBOMRegra.categoria_componente_id])

