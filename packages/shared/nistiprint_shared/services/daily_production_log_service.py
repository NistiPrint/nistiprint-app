from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime, time, date
from nistiprint_shared.services.ordem_producao_service import ordem_producao_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

class DailyProductionLogService:
    """Service for managing daily production logs in Supabase."""

    def __init__(self):
        self.table = supabase_db.table('logs_producao_diaria')

    def get_log(self, log_date: date, product_id: str):
        """Get a specific production log for a given date and product."""
        # Busca tanto no formato novo (coluna) quanto no antigo (JSONB detalhes_producao)
        response = self.table.select("*").eq('data', log_date.isoformat()).execute()

        for row in response.data:
            # Caso 1: Formato Novo (Independente)
            if str(row.get('produto_id')) == str(product_id):
                return row
            
            # Caso 2: Formato Antigo (Agregado)
            detalhes = row.get('detalhes_producao') or []
            if isinstance(detalhes, list):
                for item in detalhes:
                    if str(item.get('produto_id')) == str(product_id):
                        return {**row, **item}
        return None

    def get_logs_for_date(self, log_date: date):
        """Get all production logs for a given date."""
        # Busca todos os logs daquela data (seja via coluna 'data' ou 'data_registro')
        # Para simplificar, buscamos por 'data' e também filtramos por intervalo em 'data_registro'
        start_of_day = datetime.combine(log_date, time.min).isoformat()
        end_of_day = datetime.combine(log_date, time.max).isoformat()
        
        # Query que pega registros pela data OU pelo timestamp do dia
        response = self.table.select("*")\
            .or_(f"data.eq.{log_date.isoformat()},and(data_registro.gte.{start_of_day},data_registro.lte.{end_of_day})")\
            .neq('deleted', True)\
            .execute()

        logs = {}
        for row in response.data:
            # Processar Formato Novo
            p_id = row.get('produto_id')
            if p_id:
                if p_id not in logs: logs[p_id] = {'quantityProduced': 0, 'quantityRemoved': 0}
                qty = float(row.get('quantidade_produzida', 0))
                if qty > 0: logs[p_id]['quantityProduced'] += qty
                else: logs[p_id]['quantityRemoved'] += abs(qty)
            
            # Processar Formato Antigo (detalhes_producao JSONB)
            detalhes = row.get('detalhes_producao') or []
            if isinstance(detalhes, list):
                for item in detalhes:
                    product_id = item.get('produto_id')
                    if not product_id: continue
                    if product_id not in logs: logs[product_id] = {'quantityProduced': 0, 'quantityRemoved': 0}
                    quantity = float(item.get('quantidade', 0))
                    if quantity > 0: logs[product_id]['quantityProduced'] += quantity
                    else: logs[product_id]['quantityRemoved'] += abs(quantity)
        return logs

    def create_log(self, log_date: date, product_id: str, product_name: str, quantity: float, production_order_id: str, component_stock_snapshot: list, user_email: str = None, metadata: dict = None, item_demanda_id: str = None, demanda_nome: str = None):
        """
        Create a new production log entry with a component stock snapshot.

        Args:
            item_demanda_id: ID do item de demanda (opcional - NULL para produção avulsa)
            demanda_nome: Nome da demanda (opcional - NULL para produção avulsa)
        """
        now_local = get_now()
        log_datetime = datetime.combine(log_date, now_local.time())

        new_data = {
            'data': log_date.isoformat(), # Mantém compatibilidade com coluna antiga
            'data_registro': log_datetime.isoformat(), # Formato novo (timestamp)
            'produto_id': int(product_id) if str(product_id).isdigit() else None,
            'produto_nome': product_name,
            'quantidade_produzida': float(quantity),
            'ordem_producao_id': int(production_order_id) if str(production_order_id).isdigit() else None,
            'snapshot_estoque_componentes': component_stock_snapshot,
            'detalhes_producao': metadata, # Usando este campo para metadados/referências
            'created_at': get_now_iso(),
            'user_email': user_email,
            'deleted': False,
            'item_demanda_id': item_demanda_id,  # Opcional (NULL para produção avulsa)
            'demanda_nome': demanda_nome  # Opcional (NULL para produção avulsa)
        }

        # Criar registro independente
        response = self.table.insert(new_data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            return result

        return None

    def registrar_producao(self, log_date: date, product_id: str, product_name: str, quantity: float, user_email: str = None):
        """Orchestrates the creation of an immediate production order and logs the daily production."""
        if float(quantity) <= 0:
            return

        try:
            # Usar registrar_producao_imediata que já faz todo o fluxo de BOM, Estoque e OP finalizada
            result = ordem_producao_service.registrar_producao_imediata(
                produto_id=product_id,
                quantidade=quantity,
                data_producao=log_date.isoformat(),
                user_id=user_email # Usando e-mail como ID conforme contexto
            )
            return result
        except Exception as e:
            raise Exception(f"Falha ao registrar produção imediata para {product_name}: {str(e)}")

    def registrar_saida_simples(self, log_date: date, product_id: str, product_name: str, quantity: float, user_email: str = None):
        """Registers a simple stock removal without creating a production order."""
        if float(quantity) <= 0:
            raise ValueError("A quantidade para saída deve ser positiva.")

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        try:
            correlation_id = estoque_service.registrar_saida(
                produto_id=product_id,
                deposito_id=deposito_id,
                quantidade=float(quantity),
                motivo=f"Saída manual pela tela de Controle de Produção em {log_date.strftime('%d/%m/%Y')}.",
                user_context={'user_id': user_email},
                origem_tipo=2 # 2: DASHBOARD_PRODUCAO_ESTORNO / SAIDA MANUAL
            )

            self.create_log(
                log_date=log_date,
                product_id=product_id,
                product_name=product_name,
                quantity=-abs(float(quantity)),
                production_order_id=None,
                component_stock_snapshot=[],
                user_email=user_email,
                metadata={'correlation_id': correlation_id}
            )
        except Exception as e:
            raise Exception(f"Falha ao registrar saída para o produto {product_name}. Erro: {str(e)}")

    def get_detailed_logs_for_product(self, product_id: str, log_date: date):
        start_of_day = datetime.combine(log_date, time.min).isoformat()
        end_of_day = datetime.combine(log_date, time.max).isoformat()

        # Busca logs detalhados (formato novo)
        response = self.table.select("*")\
            .eq('produto_id', product_id)\
            .gte('data_registro', start_of_day)\
            .lte('data_registro', end_of_day)\
            .neq('deleted', True)\
            .order('data_registro', desc=True)\
            .execute()

        logs = []
        for row in response.data:
            quantity = float(row.get('quantidade_produzida', 0))
            metadata = row.get('detalhes_producao') or {}
            
            logs.append({
                'id': row.get('id'),
                'type': 'ENTRADA' if quantity > 0 else 'SAIDA',
                'quantity': quantity, # CORREÇÃO: Enviar quantidade com sinal
                'timestamp': datetime.fromisoformat(row['data_registro']).strftime('%H:%M') if row.get('data_registro') else '-',
                'created_at': row.get('data_registro'),
                'user_email': row.get('user_email', 'N/A'),
                'demanda_id': metadata.get('demanda_id') # Inclui ID da demanda no retorno
            })
        return logs

    def get_total_removed_for_product_on_date(self, product_id: str, log_date: date) -> float:
        """Retorna o total removido de um produto em uma data."""
        logs = self.get_logs_for_date(log_date)
        # Tenta buscar tanto por int quanto por string para evitar erros de tipo no dict
        p_id_int = int(product_id) if str(product_id).isdigit() else None
        product_log = logs.get(p_id_int) or logs.get(str(product_id)) or {}
        return product_log.get('quantityRemoved', 0.0)

    def reverter_lancamento(self, log_id: str, user_id: str, reverter_estoque: bool = True):
        """Reverte um lançamento de produção, executando as operações de forma atômica."""
        from nistiprint_shared.services.unit_of_work import UnitOfWork

        response = self.table.select("*").eq('id', log_id).execute()
        if not response.data:
            raise ValueError(f"Registro de log com ID {log_id} não encontrado.")

        log_data = dict(response.data[0])
        if log_data.get('deleted'):
            raise ValueError(f"Lançamento {log_id} já foi revertido anteriormente.")

        product_id = log_data['produto_id']
        quantity = float(log_data['quantidade_produzida'])
        production_order_id = log_data.get('ordem_producao_id')

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id and reverter_estoque:
            raise ValueError("O depósito de produção padrão não está configurado.")

        with UnitOfWork(user_id=user_id) as uow:
            uow.log_audit_event('REVERSAO_LANCAMENTO', {
                'log_id': log_id,
                'product_id': product_id,
                'tipo_original': 'ENTRADA' if quantity > 0 else 'SAIDA',
                'quantidade_original': abs(quantity),
                'reverter_estoque': reverter_estoque
            })

            if reverter_estoque:
                if quantity > 0: # ENTRADA
                    uow.execute_in_transaction(
                        estoque_service.registrar_saida,
                        product_id,
                        deposito_id,
                        quantity,
                        motivo=f"Estorno de produção referente ao log ID: {log_id}.",
                        usuario_id=user_id
                    )
                    for component in log_data.get('snapshot_estoque_componentes', []):
                        uow.execute_in_transaction(
                            estoque_service.registrar_entrada,
                            component['component_id'],
                            deposito_id,
                            float(component['quantity_used']),
                            observacao=f"Estorno de componentes referente ao log ID: {log_id}.",
                            ordem_compra_id=None,
                            usuario_id=user_id,
                            unit_name=None
                        )
                else: # SAIDA
                    uow.execute_in_transaction(
                        estoque_service.registrar_entrada,
                        product_id,
                        deposito_id,
                        abs(quantity),
                        observacao=f"Estorno de saída manual referente ao log ID: {log_id}.",
                        ordem_compra_id=None,
                        usuario_id=user_id,
                        unit_name=None
                    )

            self.table.update({
                'deleted': True,
                'deleted_at': get_now_iso(),
                'deleted_by': user_id
            }).eq('id', log_id).execute()

            if production_order_id and reverter_estoque:
                try:
                    ordem_producao_service.cancel_production(str(production_order_id))
                except Exception as e:
                    print(f"Warning: Failed to cancel production order {production_order_id}. Error: {e}")

        return product_id

daily_production_log_service = DailyProductionLogService()

