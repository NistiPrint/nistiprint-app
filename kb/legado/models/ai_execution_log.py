from services.database.database import db
from datetime import datetime

class AiExecutionLog(db.Model):
    __tablename__ = 'ai_execution_log'

    id = db.Column(db.Integer, primary_key=True)
    order_sn = db.Column(db.String(50), nullable=False)
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)
    input_data = db.Column(db.Text)  # JSON stored as text
    chat_context = db.Column(db.Text)  # JSON stored as text
    extracted_personalization = db.Column(db.Text)  # JSON stored as text
    model_result = db.Column(db.Text)  # JSON stored as text
    status = db.Column(db.String(50), nullable=False)
    error_message = db.Column(db.Text)
    user_feedback_id = db.Column(db.Integer)

    def __repr__(self):
        return f'<AiExecutionLog {self.order_sn} - {self.status}>'
