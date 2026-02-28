from nistiprint_shared.database.supabase_db_service import mock_db

class PersonalizacaoPedido(mock_db.Model):
    __tablename__ = 'personalizacoes_pedido'

    id = mock_db.Column(mock_db.Integer, primary_key=True)
    shopee_order_sn = mock_db.Column(mock_db.String(100))
    codigo_pedido = mock_db.Column(mock_db.String(100)) # Required by DB schema
    bling_id = mock_db.Column(mock_db.String(50))
    item_id = mock_db.Column(mock_db.String(50))
    item_description = mock_db.Column(mock_db.Text)
    customization_name = mock_db.Column(mock_db.String(255))
    customization_initial = mock_db.Column(mock_db.String(10))
    status = mock_db.Column(mock_db.String(50))
    reasoning = mock_db.Column(mock_db.Text)
    name_source_message_id = mock_db.Column(mock_db.String(100))
    metadata = mock_db.Column(mock_db.Text) # JSONB
    updated_at = mock_db.Column(mock_db.DateTime)

    # Campos legados (opcionais, mas bons de ter mapeado)
    dados_cliente = mock_db.Column(mock_db.Text)
    detalhes_personalizacao = mock_db.Column(mock_db.Text)

    def __repr__(self):
        return f'<PersonalizacaoPedido {self.customization_name} - {self.status}>'
