from nistiprint_shared.database.database import db
from datetime import datetime

class ConfiguracaoAplicacao(db.Model):
    __tablename__ = 'configuracoes_aplicacao'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)  # Configuration key name
    valor = db.Column(db.JSON, nullable=False)  # Configuration value (flexible data type)
    descricao = db.Column(db.Text)  # Description of the configuration
    categoria = db.Column(db.String(100))  # Grouping for settings
    protegido = db.Column(db.Boolean, default=False)  # If true, requires elevated permissions to change
    entidade_tipo = db.Column(db.String(50))  # Type of entity this config belongs to ('plataforma', 'canal_venda', etc.)
    entidade_id = db.Column(db.Integer)  # ID of the entity this config belongs to
    migrada_de_json = db.Column(db.Boolean, default=False)  # Flag to track if config was migrated from JSON field
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Add a constraint to ensure consistency between entity type and ID
    __table_args__ = (
        db.CheckConstraint(
            '((entidade_tipo IS NULL) AND (entidade_id IS NULL)) OR ((entidade_tipo IS NOT NULL) AND (entidade_id IS NOT NULL))',
            name='chk_entidade_consistency'
        ),
        db.UniqueConstraint('nome', 'entidade_tipo', 'entidade_id', name='unique_config_per_entity')
    )

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
            'nome': self.nome,
            'valor': self.valor,
            'descricao': self.descricao,
            'categoria': self.categoria,
            'protegido': self.protegido,
            'entidade_tipo': self.entidade_tipo,
            'entidade_id': self.entidade_id,
            'migrada_de_json': self.migrada_de_json,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
