import json
from datetime import datetime
from services.database.database import db

class ShopeeOrders(db.Model):
    __tablename__ = 'shopee_orders'

    order_sn = db.Column(db.String(18), primary_key=True)
    buyer_info = db.Column(db.Text, nullable=False)
    message = db.Column(db.Text, nullable=False)
    order_id = db.Column(db.BigInteger, unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)
    @property
    def username(self):
        try:
            if self.buyer_info:
                buyer_data = json.loads(self.buyer_info)
                return buyer_data.get('username')
            return 'n/a'
        except (json.JSONDecodeError, AttributeError):
            return 'n/a'
