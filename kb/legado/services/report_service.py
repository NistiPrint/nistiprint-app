from datetime import datetime, timedelta
from services.firebase.firestore_client import firestore_client
from services.app_config_service import app_config_service

class ReportService:
    def __init__(self):
        self.db = firestore_client

    def get_sulfite_consumption_report(self, days_to_analyze=90):
        """
        Calculates a report on sulfite sheet consumption based on production logs.
        """
        sulfite_sheet_product_id = app_config_service.get_config('sulfite_sheet_product_id')

        # If no sulfite product is configured, return an empty/zeroed report
        if not sulfite_sheet_product_id:
            return {
                "avg_daily_consumption": 0,
                "total_consumption_period": 0,
                "current_stock": 0,
                "days_of_coverage": 0,
                "reorder_date": "N/A",
                "safety_days_configured": app_config_service.get_config('material_safety_days') or 15,
                "analysis_period_days": days_to_analyze,
                "error": "Produto para relatório de consumo não configurado."
            }

        # 1. Get production logs for the specified period
        start_date = datetime.now() - timedelta(days=days_to_analyze)
        production_logs_ref = self.db.collection('daily_production_logs').where('date', '>=', start_date)
        production_logs = production_logs_ref.stream()

        total_sulfite_consumed = 0
        product_cache = {}
        
        # 2. Calculate total consumption
        for log in production_logs:
            log_data = log.to_dict()
            product_id = log_data.get('productId')
            quantity_produced = log_data.get('quantityProduced', 0)

            if not product_id:
                continue

            # Cache products to avoid multiple DB lookups for the same product
            if product_id not in product_cache:
                product_ref = self.db.collection('products').document(product_id)
                product_doc = product_ref.get()
                if product_doc.exists:
                    product_cache[product_id] = product_doc.to_dict()
                else:
                    product_cache[product_id] = None
            
            product_data = product_cache[product_id]

            if not product_data or not product_data.get('is_composite'):
                continue

            # 3. Find sulfite in BOM and calculate consumption for the log entry
            for component in product_data.get('bom_components', []):
                if component.get('product_id') == sulfite_sheet_product_id:
                    sulfite_per_unit = component.get('quantity', 0)
                    total_sulfite_consumed += sulfite_per_unit * quantity_produced
                    break
        
        # 4. Calculate average daily consumption
        avg_daily_consumption = total_sulfite_consumed / days_to_analyze if days_to_analyze > 0 else 0

        # 5. Get current stock
        current_stock = 0
        stock_ref = self.db.collection('estoque_atual').where('produto_id', '==', sulfite_sheet_product_id)
        stock_docs = stock_ref.stream()
        for doc in stock_docs:
            current_stock += doc.to_dict().get('quantidade', 0)

        # 6. Calculate coverage and reorder date
        days_of_coverage = current_stock / avg_daily_consumption if avg_daily_consumption > 0 else 0
        
        # 7. Get safety days from config
        safety_days = app_config_service.get_config('material_safety_days') or 15

        reorder_date = datetime.now() + timedelta(days=days_of_coverage - safety_days)

        return {
            "avg_daily_consumption": round(avg_daily_consumption, 2),
            "total_consumption_period": round(total_sulfite_consumed, 2),
            "current_stock": round(current_stock, 2),
            "days_of_coverage": int(days_of_coverage),
            "reorder_date": reorder_date.strftime('%Y-%m-%d'),
            "safety_days_configured": safety_days,
            "analysis_period_days": days_to_analyze
        }

    def get_production_log_history(self, page=1, per_page=50):
        """Fetches a paginated history of production logs."""
        query = self.db.collection('daily_production_logs').order_by('date', direction='DESCENDING')
        
        # Manual pagination logic
        offset = (page - 1) * per_page
        
        docs = query.offset(offset).limit(per_page).stream()
        logs = [doc.to_dict() for doc in docs]

        # For total count, we need to run a separate query without pagination limits
        # This can be expensive. For this use case, we can just check if there are more items
        # to avoid a full count.
        total_logs_query = query.limit(1).offset(page * per_page).stream()
        has_next = any(True for _ in total_logs_query)

        return logs, has_next

report_service = ReportService()
