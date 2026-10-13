from datetime import datetime
from typing import List, Dict, Any, Optional
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation
from nistiprint_shared.database.supabase_db_service import supabase_db

from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.bom_service import bom_service


class OrdemProducaoService:
    """Serviço para gerenciamento de Ordens de Produção usando Supabase."""

    def __init__(self):
        self.table = supabase_db.table('ordens_producao')
        self.components_table = supabase_db.table('componentes_ordem_producao')

    def create_draft(self, product_id: str, quantity_to_produce: float, notes: str = "") -> Dict[str, Any]:
        """Cria uma OP em rascunho."""
        if float(quantity_to_produce) <= 0:
            raise ValueError("A quantidade a produzir deve ser positiva.")

        product = product_service.get_by_id(product_id)
        if not product:
            raise ValueError(f"Produto '{product_id}' não encontrado.")
        
        # Enriquecer para garantir mapeamento de campos (nome -> name, etc)
        product = product_service.enrich_product_data(product)

        op_data = {
            'ordem_id': str(uuid.uuid4()),
            'produto_id': product_id,
            'sku': product.get('sku', ''),
            'descricao': notes or f"Produção de {product['name']}",
            'quantidade': float(quantity_to_produce),
            'status': 'DRAFT',
            'created_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(op_data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = str(result.get('id'))
            return result
        return None

    def update_draft(self, po_id: str, quantity_to_produce: Optional[float] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        """Atualiza OP em rascunho."""
        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        if op_data['status'] != 'DRAFT':
            raise ValueError("Apenas OPs em DRAFT podem ser editadas.")

        updates = {}
        if quantity_to_produce is not None and float(quantity_to_produce) > 0:
            updates['quantidade'] = float(quantity_to_produce)
        if notes is not None:
            updates['descricao'] = notes

        if updates:
            updates['updated_at'] = datetime.utcnow().isoformat()
            response = self.table.update(updates).eq('id', po_id).execute()
            if response.data:
                op_data.update(dict(response.data[0]))

        op_data['id'] = po_id
        return op_data

    def start_production(self, po_id: str) -> Dict[str, Any]:
        """Inicia a produção, verificando e reservando componentes via EstoqueService."""

        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        if op_data['status'] != 'DRAFT':
            raise ValueError("Apenas OPs em DRAFT podem ser iniciadas.")

        product_id = op_data['produto_id']
        quantity_to_produce = float(op_data['quantidade'])

        # Fixar a composição efetiva herdada antes de iniciar a execução.
        bom_version = bom_service.publish_effective_version(int(product_id))
        graph = bom_version['graph']['nodes'].get(str(int(product_id)), {}).get('componentes', [])
        bom_components = []
        for line in graph:
            component = product_service.get_by_id(str(line['componente_id'])) or {}
            bom_components.append({
                'component_id': int(line['componente_id']),
                'quantity': float(line['quantidade_necessaria']),
                'name': component.get('nome') or component.get('name') or str(line['componente_id']),
                'sku': component.get('sku', ''),
            })

        # Montar as necessidades a partir da versão efetiva fixada acima.
        needs = []

        # Obter o depósito de produção a partir das configurações
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado. Por favor, configure-o na tela de Configurações -> Produção.")
        deposito_id = estoque_service._resolve_deposito(deposito_id)

        for comp in bom_components:
            required = float(comp['quantity']) * quantity_to_produce
            needs.append({
                'componente_id': int(comp['component_id']),
                'sku': comp.get('sku', ''),
                'descricao': comp.get('name', ''),
                'quantidade_necessaria': required,
            })

        # Backorder permanece permitido como no fluxo anterior, mas reserva,
        # componentes e status agora confirmam no mesmo commit.
        command = {
            'ordem_producao_id': int(po_id), 'deposito_id': int(deposito_id),
            'bom_version_id': bom_version['id'], 'quantidade': quantity_to_produce,
            'needs': sorted(needs, key=lambda row: (row['componente_id'], row['quantidade_necessaria'])),
        }
        content_hash = hashlib.sha256(json.dumps(
            command, sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:op-start:{po_id}"))
        result = supabase_db.rpc('iniciar_ordem_producao_transacional', {
            'p_operation_id': operation_id, 'p_content_hash': content_hash,
            'p_ordem_id': int(po_id), 'p_deposito_id': int(deposito_id),
            'p_bom_version_id': bom_version['id'],
            'p_actor_id': op_data.get('responsavel_id'), 'p_needs': needs,
        }).execute().data
        result = result[0] if isinstance(result, list) and result else result
        row = result.get('ordem_producao') if isinstance(result, dict) else None
        if not row:
            raise RuntimeError('O início transacional da OP não retornou o estado confirmado')
        row['id'] = str(row.get('id'))
        return row

    def deliver_production(self, po_id: str, quantity_delivered: float, user_id: Optional[int] = None,
                           operation_id: Optional[str] = None) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Confirma consumo, saldo acabado, alocações e checkpoint em um RPC idempotente."""
        from uuid import UUID
        try:
            quantity_decimal = Decimal(str(quantity_delivered))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Quantidade entregue inválida.") from exc
        if not quantity_decimal.is_finite() or quantity_decimal <= 0:
            raise ValueError("Quantidade entregue deve ser positiva.")
        if quantity_decimal != quantity_decimal.quantize(Decimal('0.0001')):
            raise ValueError("Quantidade entregue aceita no máximo quatro casas decimais.")
        quantity = float(quantity_decimal)
        if not operation_id:
            raise ValueError("A entrega exige uma chave Idempotency-Key estável.")
        try:
            operation_id = str(UUID(str(operation_id)))
        except (TypeError, ValueError) as exc:
            raise ValueError("Idempotency-Key deve ser um UUID válido.") from exc
        deposit_id = estoque_service._resolve_deposito(None)
        content = {'ordem_producao_id': int(po_id), 'quantidade': format(quantity_decimal, '.4f')}
        content_hash = hashlib.sha256(json.dumps(
            content, sort_keys=True, separators=(',', ':')
        ).encode('utf-8')).hexdigest()
        result = supabase_db.rpc('entregar_ordem_producao_transacional', {
            'p_operation_id': operation_id, 'p_content_hash': content_hash,
            'p_ordem_id': int(po_id), 'p_deposito_id': int(deposit_id),
            'p_quantidade': format(quantity_decimal, '.4f'), 'p_actor_id': user_id,
        }).execute().data
        result = result[0] if isinstance(result, list) and result else result
        row = result.get('ordem_producao') if isinstance(result, dict) else None
        if not row:
            raise RuntimeError('A entrega transacional não retornou o estado confirmado')
        row['id'] = str(row.get('id'))
        if not result.get('replayed'):
            try:
                from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
                demanda_producao_service.alocar_producao_automatica(
                    produto_id=row['produto_id'], quantidade=quantity,
                    user_id=str(user_id) if user_id else 'System'
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Produção OP %s confirmada; distribuição automática para demanda ficou pendente', po_id
                )
        return row, result.get('snapshot_componentes') or []

    def pause_production(self, po_id: str) -> Dict[str, Any]:
        """Pausa a produção."""
        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        if op_data['status'] not in ['PENDING', 'IN_PROGRESS', 'PARTIALLY_DELIVERED']:
            raise ValueError("Apenas OPs ativas podem receber entregas.")

        self.table.update({'status': 'PAUSED'}).eq('id', po_id).execute()
        return self.get_by_id(po_id)

    def resume_production(self, po_id: str) -> Dict[str, Any]:
        """Retoma a produção."""
        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        if op_data['status'] != 'PAUSED':
            raise ValueError("Apenas OPs pausadas podem ser retomadas.")

        self.table.update({'status': 'PENDING'}).eq('id', po_id).execute()
        return self.get_by_id(po_id)

    def cancel_production(self, po_id: str) -> Dict[str, Any]:
        """Cancela a produção, estornando reservas via EstoqueService."""
        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:op-cancel:{po_id}"))
        command = {'ordem_producao_id': int(po_id), 'comando': 'CANCELAR'}
        content_hash = hashlib.sha256(json.dumps(
            command, sort_keys=True, separators=(',', ':')
        ).encode('utf-8')).hexdigest()
        result = supabase_db.rpc('cancelar_ordem_producao_transacional', {
            'p_operation_id': operation_id, 'p_content_hash': content_hash,
            'p_ordem_id': int(po_id), 'p_actor_id': op_data.get('responsavel_id'),
        }).execute().data
        result = result[0] if isinstance(result, list) and result else result
        row = result.get('ordem_producao') if isinstance(result, dict) else None
        if not row:
            raise RuntimeError('O cancelamento transacional da OP não retornou o estado confirmado')
        row['id'] = str(row.get('id'))
        return row

    def get_by_id(self, po_id: str) -> Optional[Dict[str, Any]]:
        """Busca OP por ID."""
        response = self.table.select("*").eq('id', po_id).execute()
        if response.data:
            op_data = dict(response.data[0])
            op_data['id'] = str(op_data.get('id'))
            return op_data
        return None

    def get_all(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Lista OPs."""
        query = self.table
        if status:
            query = query.eq('status', status)
        query = query.order('created_at', desc=True).limit(limit)

        response = query.execute()
        ops = []
        for row in response.data:
            op_data = dict(row)
            op_data['id'] = str(op_data.get('id'))
            ops.append(op_data)
        return ops

    def get_components(self, po_id: str) -> List[Dict[str, Any]]:
        """Busca componentes da OP."""
        response = self.components_table.select("*").eq('ordem_producao_id', po_id).execute()
        components = []
        for row in response.data:
            comp = dict(row)
            # comp['componentId'] = str(comp.get('id'))
            components.append(comp)
        return components

    def registrar_producao_imediata(self, produto_id: str, quantidade: float, data_producao: str, user_id: str = 'System', sincrono: bool = False) -> Dict[str, Any]:
        """
        Cria uma OP já finalizada e dá entrada no produto final.
        sincrono=True: Processa BOM imediatamente.
        sincrono=False (Padrão): Processa em background via fila (origem_tipo=3).
        """
        if float(quantidade) <= 0:
            raise ValueError("Quantidade deve ser positiva.")
        
        product = product_service.get_by_id(produto_id)
        if not product:
            raise ValueError(f"Produto {produto_id} não encontrado.")
        
        product = product_service.enrich_product_data(product)
        deposito_id = app_config_service.get_config('default_production_deposit_id')

        correlation_id = str(uuid.uuid4())

        # 1. Registrar a Entrada do Produto Principal
        if sincrono:
            # Modelo 100% Síncrono: Chama o motor de demanda para processar recursivo agora
            from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
            try:
                print(f"DEBUG: Executando Produção Imediata Síncrona para {produto_id}")
                
                # Primeiro, registrar entrada do produto principal
                correlation_id = estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=float(quantidade),
                    observacao=f"Produção Imediata (Síncrona) - {user_id}",
                    usuario_id=None,
                    user_context={'user_id': user_id},
                    origem_tipo=3,
                    correlation_id=correlation_id
                )
                
                # Depois, processar insumos por BOM recursivamente
                success = demanda_producao_service.processar_insumos_por_bom_recursivo(
                    produto_id=int(produto_id),
                    quantidade=float(quantidade),
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='PRODUCAO_AVULSA'  # Item FICA no estoque
                )
                if not success:
                    raise Exception("Falha no processamento recursivo de insumos.")
            except Exception as e:
                print(f"Erro no processamento síncrono: {e}")
                raise e
        else:
            # Modelo Híbrido (Padrão): Entrada síncrona, Insumos assíncronos (origem_tipo=3)
            try:
                correlation_id = estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=float(quantidade),
                    observacao=f"Produção Imediata (Híbrida) - {user_id}",
                    usuario_id=None,
                    user_context={'user_id': user_id},
                    origem_tipo=3
                )
            except Exception as e:
                raise Exception(f"Falha ao registrar entrada de estoque: {str(e)}")

        # 2. Criar a OP para fins de histórico e rastreabilidade
        try:
            op_data = {
                'ordem_id': str(uuid.uuid4()),
                'produto_id': produto_id,
                'sku': product.get('sku', ''),
                'descricao': f"Produção imediata registrada em {data_producao} (Corr: {correlation_id})",
                'quantidade': float(quantidade),
                'status': 'COMPLETED',
                'data_inicio': datetime.utcnow().date().isoformat(),
                'data_fim': datetime.utcnow().date().isoformat(),
                'created_at': datetime.utcnow().isoformat(),
                'responsavel_id': None
            }
            res_op = self.table.insert(op_data).execute()
            po_id = str(res_op.data[0]['id']) if res_op.data else None
        except Exception as e:
            print(f"Aviso: Falha ao criar registro de OP, mas estoque foi processado: {e}")
            po_id = None

        # 3. Log de Produção Diária
        from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
        try:
            log_date = datetime.strptime(data_producao, '%Y-%m-%d').date()
        except:
            log_date = datetime.fromisoformat(data_producao).date()

        daily_production_log_service.create_log(
            log_date=log_date,
            product_id=produto_id,
            product_name=product['name'],
            quantity=float(quantidade),
            production_order_id=po_id,
            component_stock_snapshot=[],
            user_email=str(user_id),
            metadata={'correlation_id': correlation_id, 'sincrono': sincrono}
        )

        return {
            'success': True,
            'message': 'Produção registrada com sucesso (Síncrono)' if sincrono else 'Produção registrada com sucesso (Insumos processando em background).',
            'correlation_id': correlation_id
        }



ordem_producao_service = OrdemProducaoService()

