from services.database.database import db
from datetime import datetime

class OrderPersonalizations(db.Model):
    __tablename__ = 'order_personalizations'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    order_id = db.Column(db.String(50), nullable=False)  # Shopee Order ID
    shopee_order_sn = db.Column(db.String(100), nullable=False)  # Shopee Order Serial Number
    bling_id = db.Column(db.String(50), nullable=True)  # Bling Order ID
    bling_number = db.Column(db.String(50), nullable=True)  # Bling Order Number
    status = db.Column(db.Enum('SUCCESS', 'NEEDS_REVIEW', 'NO_PERSONALIZATION_FOUND'), nullable=False)
    reasoning = db.Column(db.Text, nullable=True)  # Explanation of the extraction decision
    item_id = db.Column(db.String(50), nullable=False)  # Shopee Item ID
    item_description = db.Column(db.Text, nullable=False)  # Item description
    quantity_to_personalize = db.Column(db.Integer, nullable=False, default=1)
    customization_name = db.Column(db.String(255), nullable=True)  # Extracted name for personalization
    name_source_message_id = db.Column(db.String(100), nullable=True)  # Message ID where name was found
    customization_initial = db.Column(db.String(1), nullable=True)  # Extracted initial for personalization
    initial_source_message_id = db.Column(db.String(100), nullable=True)  # Message ID where initial was found
    extracted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)  # When the personalization was processed
    extraction_metadata = db.Column('metadata', db.JSON, nullable=True)  # Additional metadata in JSON format (maps to real column 'metadata')

    # Note: Removed foreign key constraints as they reference Bling tables but our data may come from different sources

    def __repr__(self):
        return f'<OrderPersonalizations {self.customization_name} - {self.status}>'
