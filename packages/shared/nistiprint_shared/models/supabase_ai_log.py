from nistiprint_shared.database.supabase_db_service import mock_db

class LogsExecucaoIA(mock_db.Model):
    __tablename__ = 'logs_execucao_ia'

    id = mock_db.Column(mock_db.Integer, primary_key=True)
    order_sn = mock_db.Column(mock_db.String(50))
    executed_at = mock_db.Column(mock_db.DateTime)
    input_data = mock_db.Column(mock_db.Text) # JSONB no banco
    chat_context = mock_db.Column(mock_db.Text) # JSONB
    extracted_personalization = mock_db.Column(mock_db.Text) # JSONB
    model_result = mock_db.Column(mock_db.Text) # JSONB
    status = mock_db.Column(mock_db.String(50))
    error_message = mock_db.Column(mock_db.Text)
    user_feedback_id = mock_db.Column(mock_db.Integer)
    metadata = mock_db.Column(mock_db.Text) # JSONB

    def __repr__(self):
        return f'<LogsExecucaoIA {self.order_sn} - {self.status}>'
