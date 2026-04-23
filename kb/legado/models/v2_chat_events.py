from datetime import datetime
from services.database.database import db

class V2ChatEvents(db.Model):
    __tablename__ = 'v2_chat_events'

    id = db.Column(db.String(64), primary_key=True)
    shop_id = db.Column(db.BigInteger, nullable=False)
    request_id = db.Column(db.String(64))
    from_id = db.Column(db.BigInteger)
    to_id = db.Column(db.BigInteger)
    from_shop_id = db.Column(db.BigInteger)
    to_shop_id = db.Column(db.BigInteger)
    from_user_name = db.Column(db.String(64))
    to_user_name = db.Column(db.String(128))
    type = db.Column(db.String(64))
    conversation_id = db.Column(db.BigInteger)
    faq_session_id = db.Column(db.BigInteger)
    source_type = db.Column(db.String(64))
    created_timestamp = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime)
    status = db.Column(db.Text)
    message_option = db.Column(db.Integer)
    source = db.Column(db.String(32))
    content = db.Column(db.Text)  # Storing as Text since it's JSON
    faq_info = db.Column(db.Text)  # Storing as Text since it's JSON
    source_content = db.Column(db.Text)  # Storing as Text since it's JSON
    raw_json = db.Column(db.Text)  # Storing as Text since it's JSON

    def to_dict(self):
        return {
            'id': self.id,
            'from_user_name': self.from_user_name,
            'to_user_name': self.to_user_name,
            'type': self.type,
            'content': self.content,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'status': self.status,
            'shop_id': self.shop_id,
            'conversation_id': self.conversation_id
        }
