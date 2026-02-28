from nistiprint_shared.database.database import db
from datetime import datetime

class OrderFeedback(db.Model):
    __tablename__ = 'order_feedback'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), nullable=False)
    feedback = db.Column(db.Integer, nullable=False)  # 1 para positivo, 0 para negativo
    feedback_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer)  # Se houver sistema de usuários

    def __repr__(self):
        return f'<OrderFeedback {self.order_id} - {self.feedback}>'
