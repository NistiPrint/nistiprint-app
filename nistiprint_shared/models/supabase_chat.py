from services.database.v2.supabase_db_service import mock_db

class MensagemChatShopee(mock_db.Model):
    __tablename__ = 'mensagem_chat_shopee'

    id = mock_db.Column(mock_db.String(64), primary_key=True)
    shop_id = mock_db.Column(mock_db.Integer)
    request_id = mock_db.Column(mock_db.String(64))
    from_id = mock_db.Column(mock_db.Integer)
    to_id = mock_db.Column(mock_db.Integer)
    from_shop_id = mock_db.Column(mock_db.Integer)
    to_shop_id = mock_db.Column(mock_db.Integer)
    from_user_name = mock_db.Column(mock_db.String(64))
    to_user_name = mock_db.Column(mock_db.String(128))
    type = mock_db.Column(mock_db.String(64))
    conversation_id = mock_db.Column(mock_db.Integer)
    faq_session_id = mock_db.Column(mock_db.Integer)
    source_type = mock_db.Column(mock_db.String(64))
    created_timestamp = mock_db.Column(mock_db.DateTime)
    created_at = mock_db.Column(mock_db.DateTime)
    status = mock_db.Column(mock_db.Text)
    message_option = mock_db.Column(mock_db.Integer)
    source = mock_db.Column(mock_db.String(32))
    content = mock_db.Column(mock_db.Text) 
    faq_info = mock_db.Column(mock_db.Text) 
    source_content = mock_db.Column(mock_db.Text)
    raw_json = mock_db.Column(mock_db.Text)

    def to_dict(self):
        return {
            'id': self.id,
            'from_user_name': self.from_user_name,
            'to_user_name': self.to_user_name,
            'type': self.type,
            'content': self.content,
            'created_at': self.created_at,
            'status': self.status
        }
