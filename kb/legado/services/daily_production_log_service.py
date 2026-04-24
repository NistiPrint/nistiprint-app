from services.firebase.firestore_client import firestore_client
from datetime import datetime, time
from services.ordem_producao_service import ordem_producao_service
from services.estoque_service import estoque_service
from services.app_config_service import app_config_service

class DailyProductionLogService:
    """Service for managing daily production logs in Firestore."""

    def __init__(self):
        self.collection = firestore_client.collection('daily_production_logs')

    def get_log(self, log_date: datetime.date, product_id: str):
        """Get a specific production log for a given date and product."""
        start_of_day = datetime.combine(log_date, time.min)
        end_of_day = datetime.combine(log_date, time.max)

        docs = self.collection \
            .where('date', '>=', start_of_day) \
            .where('date', '<=', end_of_day) \
            .where('productId', '==', product_id) \
            .limit(1) \
            .stream()
        
        for doc in docs:
            log = doc.to_dict()
            log['id'] = doc.id
            return log
        return None

    def get_logs_for_date(self, log_date: datetime.date):
        """Get all production logs for a given date, separating produced and removed quantities."""
        start_of_day = datetime.combine(log_date, time.min)
        end_of_day = datetime.combine(log_date, time.max)

        docs = self.collection \
            .where('date', '>=', start_of_day) \
            .where('date', '<=', end_of_day) \
            .where('deleted', '!=', True) \
            .stream()
        
        logs = {}
        for doc in docs:
            log = doc.to_dict()
            product_id = log['productId']
            if product_id not in logs:
                logs[product_id] = {'quantityProduced': 0, 'quantityRemoved': 0}
            
            quantity = log.get('quantityProduced', 0)
            if quantity > 0:
                logs[product_id]['quantityProduced'] += quantity
            else:
                logs[product_id]['quantityRemoved'] += abs(quantity)
        return logs

    def create_log(self, log_date: datetime.date, product_id: str, product_name: str, quantity: float, production_order_id: str, component_stock_snapshot: list, user_email: str = None):
        """Create a new production log entry with a component stock snapshot."""
        log_datetime = datetime.combine(log_date, datetime.now().time())
        
        doc_ref = self.collection.document()
        new_data = {
            'id': doc_ref.id,
            'date': log_datetime,
            'productId': product_id,
            'productName': product_name,
            'quantityProduced': quantity,
            'productionOrderId': production_order_id,
            'componentStockSnapshot': component_stock_snapshot,
            'createdAt': datetime.utcnow(),
            'userEmail': user_email,
            'deleted': False
        }
        doc_ref.set(new_data)
        return new_data

    def registrar_producao_e_criar_op(self, log_date: datetime.date, product_id: str, product_name: str, quantity: float, user_email: str = None):
        """Orchestrates the creation of a production order and logs the daily production."""
        if quantity <= 0:
            return # Do nothing if quantity is zero or negative

        # 1. Create Draft Production Order
        op_note = f"OP gerada automaticamente pela tela de controle de produção em {log_date.strftime('%d/%m/%Y')}."
        op_draft = ordem_producao_service.create_draft(product_id, quantity, notes=op_note)
        po_id = op_draft['id']

        try:
            # 2. Start Production (Reserves stock)
            ordem_producao_service.start_production(po_id)

            # 3. Deliver/Finalize Production (Consumes components, adds final product to stock)
            _, component_snapshot = ordem_producao_service.deliver_production(po_id, quantity)

            # 4. Create the log for this specific production event
            self.create_log(
                log_date=log_date,
                product_id=product_id,
                product_name=product_name,
                quantity=quantity,
                production_order_id=po_id,
                component_stock_snapshot=component_snapshot,
                user_email=user_email
            )
        except Exception as e:
            # If anything fails after creating the draft, try to cancel the OP
            ordem_producao_service.cancel_production(po_id)
            raise Exception(f"Falha ao processar OP {po_id} para o produto {product_name}. A OP foi cancelada. Erro: {str(e)}")

    def registrar_saida_simples(self, log_date: datetime.date, product_id: str, product_name: str, quantity: float, user_email: str = None):
        """Registers a simple stock removal without creating a production order."""
        if quantity <= 0:
            raise ValueError("A quantidade para saída deve ser positiva.")

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        try:
            # 1. Register the stock removal
            estoque_service.registrar_saida(
                produto_id=product_id,
                deposito_id=deposito_id,
                quantidade=quantity,
                observacao=f"Saída manual pela tela de Controle de Produção em {log_date.strftime('%d/%m/%Y')}."
            )

            # 2. Create a log entry with a negative quantity
            self.create_log(
                log_date=log_date,
                product_id=product_id,
                product_name=product_name,
                quantity=-abs(quantity), # Log as a negative value
                production_order_id=None, # No OP for simple removal
                component_stock_snapshot=[], # No components consumed
                user_email=user_email
            )
        except Exception as e:
            # Here you might want to add compensating logic if the stock removal succeeded but the log failed
            raise Exception(f"Falha ao registrar saída para o produto {product_name}. Erro: {str(e)}")

    def get_detailed_logs_for_product(self, product_id: str, log_date: datetime.date):
        start_of_day = datetime.combine(log_date, time.min)
        end_of_day = datetime.combine(log_date, time.max)

        docs = self.collection \
            .where('date', '>=', start_of_day) \
            .where('date', '<=', end_of_day) \
            .where('productId', '==', product_id) \
            .where('deleted', '!=', True) \
            .order_by('date', direction='DESCENDING') \
            .stream()

        logs = []
        for doc in docs:
            log_data = doc.to_dict()
            quantity = log_data.get('quantityProduced', 0)
            logs.append({
                'id': doc.id,
                'type': 'ENTRADA' if quantity > 0 else 'SAIDA',
                'quantity': abs(quantity),
                'timestamp': log_data['date'].strftime('%H:%M:%S'),
                'user_email': log_data.get('userEmail', 'N/A') # Assumes user email is stored
            })
        return logs

    def delete_log_entry(self, log_id: str, deleted_by_user_id: any):
        log_ref = self.collection.document(log_id)
        log_doc = log_ref.get()

        if not log_doc.exists:
            raise ValueError(f"Registro de log com ID {log_id} não encontrado.")

        log_data = log_doc.to_dict()
        product_id = log_data['productId']
        quantity = log_data['quantityProduced']
        log_date = log_data['date'].date()

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        # Determine the type of reversal needed
        if quantity > 0: # This was a production (ENTRADA)
            # 1. Remove the stock of the final product
            estoque_service.registrar_saida(
                produto_id=product_id,
                deposito_id=deposito_id,
                quantidade=quantity,
                observacao=f"Estorno de produção referente ao log ID: {log_id}."
            )
            # 2. Return the components to stock
            for component in log_data.get('componentStockSnapshot', []):
                estoque_service.registrar_entrada(
                    produto_id=component['component_id'],
                    deposito_id=deposito_id, # Assuming components are from the same deposit
                    quantidade=component['quantity_used'],
                    observacao=f"Estorno de componentes referente ao log ID: {log_id}."
                )
        else: # This was a removal (SAIDA)
            # Add the stock back
            estoque_service.registrar_entrada(
                produto_id=product_id,
                deposito_id=deposito_id,
                quantidade=abs(quantity),
                observacao=f"Estorno de saída manual referente ao log ID: {log_id}."
            )

        # 3. Mark the log as deleted instead of physically deleting it
        log_ref.update({
            'deleted': True,
            'deletedAt': datetime.utcnow(),
            'deletedBy': deleted_by_user_id
        })
        
        # Optionally, you could also cancel the associated Production Order if applicable
        production_order_id = log_data.get('productionOrderId')
        if production_order_id:
            try:
                # This is a placeholder - the actual method might be different
                ordem_producao_service.cancel_production(production_order_id, notes=f"Cancelado devido à exclusão do log de produção {log_id}.")
            except Exception as e:
                # Log this failure but don't let it block the main deletion
                print(f"Warning: Failed to cancel production order {production_order_id}. Error: {e}")


        return product_id

# Global instance
daily_production_log_service = DailyProductionLogService()
