from nistiprint_shared.database.database import db
from datetime import datetime

class DailyProductionLog(db.Model):
    __tablename__ = 'logs_producao_diaria'  # daily_production_logs → logs_producao_diaria

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    turno = db.Column(db.String(50))  # Morning, evening, etc.
    equipe_id = db.Column(db.Integer, db.ForeignKey('setores.id'), nullable=True)
    resumo_diario = db.Column(db.JSON)  # Daily summary data
    producao_detalhes = db.Column(db.JSON)  # Detailed production information
    problemas = db.Column(db.JSON)  # Issues encountered
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
            'date': self.date.isoformat() if self.date else None,  # Date might be different from datetime
            'turno': self.turno,
            'equipe_id': self.equipe_id,
            'equipe_nome': self.equipe.nome if self.equipe else None,
            'resumo_diario': self.resumo_diario,
            'producao_detalhes': self.producao_detalhes,
            'problemas': self.problemas,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
DailyProductionLog.equipe = db.relationship('Setor', backref='logs_producao_diaria')
