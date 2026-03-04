from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid
from nistiprint_shared.database.supabase_db_service import supabase_db

from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service


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

        # 1. Buscar BOM do produto com dados de estoque já enriquecidos e em tempo real
        bom_components = product_service.get_bom_components(product_id)

        # 2. Calcular necessidades e verificar estoque disponível
        needs = []
        insufficient = []

        # Obter o depósito de produção a partir das configurações
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado. Por favor, configure-o na tela de Configurações -> Produção.")

        for comp in bom_components:
            required = float(comp['quantity']) * quantity_to_produce
            # A verificação de 'available_stock' já foi feita na camada da rota,
            # mas refazemos aqui para garantir a integridade da transação.
            saldo_componente = estoque_service.get_saldo_atual(comp['component_id'], deposito_id)
            available = float(saldo_componente.get('quantidade_disponivel', 0))

            if required > available:
                insufficient.append(f"{comp['name']}: necessita {required}, disponível {available} no depósito configurado")
            else:
                needs.append({
                    'componente_id': comp['component_id'],
                    'sku': comp.get('sku', ''),
                    'descricao': comp.get('name', ''),
                    'quantidade_necessaria': required,
                    'quantidade_utilizada': 0.0
                })

        # if insufficient:
        #     raise ValueError(f"Estoque insuficiente para: {', '.join(insufficient)}")
        
        if insufficient:
            print(f"AVISO: Iniciando OP {po_id} com estoque insuficiente para os componentes: {', '.join(insufficient)}")

        # 3. Reservar componentes usando o EstoqueService EM LOTE
        try:
            estoque_service.reservar_estoque_em_lote(
                itens_reserva=[{'produto_id': n['componente_id'], 'quantidade': n['quantidade_necessaria']} for n in needs],
                deposito_id=deposito_id
            )
        except Exception as e:
            # Rollback das reservas em caso de erro
            estoque_service.liberar_reserva_em_lote(
                itens_liberacao=[{'produto_id': n['componente_id'], 'quantidade': n['quantidade_necessaria']} for n in needs],
                deposito_id=deposito_id
            )
            raise 

        # 4. Atualizar OP e criar registros de componentes EM LOTE
        updates = {
            'status': 'PENDING',
            'data_inicio': datetime.utcnow().date().isoformat()
        }
        supabase_db.execute_with_retry(self.table.update(updates).eq('id', po_id))

        # Criar registros dos componentes necessários em uma única chamada
        if needs:
            components_to_insert = [{
                'ordem_producao_id': po_id,
                'componente_id': need['componente_id'],
                'sku': need['sku'],
                'descricao': need['descricao'],
                'quantidade_necessaria': need['quantidade_necessaria'],
                'quantidade_utilizada': need['quantidade_utilizada'],
                'status': 'PENDENTE'
            } for need in needs]
            supabase_db.execute_with_retry(self.components_table.insert(components_to_insert))

        op_data.update(updates)
        op_data['id'] = po_id
        return op_data

    def deliver_production(self, po_id: str, quantity_delivered: float, user_id: Optional[int] = None) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Entrega produção, consumindo reservas, registrando entrada do produto final e retornando um snapshot do estoque dos componentes."""
        if float(quantity_delivered) <= 0:
            raise ValueError("Quantidade entregue deve ser positiva.")

        op_data = self.get_by_id(po_id)
        if not op_data:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        if op_data['status'] not in ['PENDING', 'IN_PROGRESS', 'PARTIALLY_DELIVERED']:
            raise ValueError("Apenas OPs ativas podem receber entregas.")

        total_to_produce = float(op_data['quantidade'])
        # Usamos dados_adicionais para rastrear progresso se a coluna não existir
        dados_adicionais = op_data.get('dados_adicionais') or {}
        qty_already_produced = float(dados_adicionais.get('quantidade_produzida', 0))
        
        total_produced = qty_already_produced + float(quantity_delivered)

        if total_produced > total_to_produce + 0.001: # Tolerância para float
            raise ValueError(f"Quantidade total produzida ultrapassaria o planejado: {total_produced} > {total_to_produce}")

        # Lista para armazenar o snapshot do estoque dos componentes
        component_stock_snapshot = []

        # Consumir componentes proporcionalmente
        components = self.get_components(po_id)
        consumption_proportion = float(quantity_delivered) / total_to_produce

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        try:
            for comp_data in components:
                qty_to_consume = float(comp_data['quantidade_necessaria']) * consumption_proportion

                if qty_to_consume > 0:
                    # --- Início da Lógica de Snapshot ---
                    saldo_componente_antes = estoque_service.get_saldo_atual(comp_data['componente_id'], deposito_id)
                    stock_before = float(saldo_componente_antes.get('quantidade', 0))

                    estoque_service.consumir_reserva(
                        produto_id=comp_data['componente_id'],
                        deposito_id=deposito_id,
                        ordem_id=po_id,
                        quantidade=qty_to_consume,
                        observacao=f"Consumo para OP {po_id}",
                        usuario_id=user_id
                    )

                    stock_after = stock_before - qty_to_consume

                    snapshot_item = {
                        "component_id": comp_data['componente_id'],
                        "component_name": comp_data.get('descricao', ''),
                        "quantity_used": qty_to_consume,
                        "stock_before_production": stock_before,
                        "stock_after_production": stock_after
                    }
                    component_stock_snapshot.append(snapshot_item)
                    # --- Fim da Lógica de Snapshot ---

                    # Atualizar o consumo na tabela de componentes da OP
                    new_used = float(comp_data.get('quantidade_utilizada', 0)) + qty_to_consume
                    self.components_table.update({'quantidade_utilizada': new_used}).eq('id', comp_data['id']).execute()

            # Registrar entrada do produto acabado
            estoque_service.registrar_entrada(
                produto_id=op_data['produto_id'],
                deposito_id=deposito_id,
                quantidade=float(quantity_delivered),
                observacao=f"Entrada de produção da OP {po_id}",
                usuario_id=user_id,
                user_context=None  # Não temos contexto de usuário aqui
            )

            # Atualizar status da OP
            new_status = 'COMPLETED' if total_produced >= total_to_produce else 'PARTIALLY_DELIVERED'
            
            dados_adicionais['quantidade_produzida'] = total_produced
            
            updates = {
                'status': new_status,
                'dados_adicionais': dados_adicionais,
                'updated_at': datetime.utcnow().isoformat()
            }
            if new_status == 'COMPLETED':
                updates['data_fim'] = datetime.utcnow().date().isoformat()

            self.table.update(updates).eq('id', po_id).execute()

            # --- INTEGRAÇÃO COM DASHBOARD DE DEMANDA ---
            # Ao entregar uma produção, tentamos alocar essa quantidade para as demandas abertas
            try:
                from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
                demanda_producao_service.alocar_producao_automatica(
                    produto_id=op_data['produto_id'],
                    quantidade=float(quantity_delivered),
                    user_id=str(user_id) if user_id else 'System'
                )
            except Exception as e:
                print(f"Erro ao alocar produção da OP {po_id} para demandas: {e}")
            # --------------------------------------------

            return self.get_by_id(po_id), component_stock_snapshot

        except Exception as e:
            # Idealmente, aqui deveria haver uma lógica de compensação para reverter as ações bem-sucedidas
            raise ValueError(f"Erro ao entregar produção: {str(e)}. O estado do estoque pode estar inconsistente.")

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

        if op_data['status'] in ['COMPLETED', 'CANCELED']:
            raise ValueError("OP já finalizada ou cancelada não pode ser cancelada novamente.")

        # Obter componentes da OP
        components = self.get_components(po_id)

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        # Apenas libera reservas se a OP chegou a ser iniciada (tendo componentes)
        if op_data['status'] != 'DRAFT':
            try:
                for comp_data in components:
                    # A função liberar_reserva do service já é inteligente para lidar
                    # com o que já foi consumido ou não.
                    estoque_service.liberar_reserva(
                        produto_id=comp_data['componente_id'],
                        deposito_id=deposito_id,
                        ordem_id=po_id
                    )
            except Exception as e:
                # Log a critical error but continue to cancel the OP itself
                print(f"CRITICAL: Failed to release all stock reservations for OP {po_id}. Manual check required. Error: {str(e)}")

        # Atualizar status da OP
        updates = {
            'status': 'CANCELED',
            'updated_at': datetime.utcnow().isoformat()
        }
        self.table.update(updates).eq('id', po_id).execute()

        return self.get_by_id(po_id)

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

    def registrar_producao_imediata(self, produto_id: str, quantidade: float, data_producao: str, user_id: str = 'System') -> Dict[str, Any]:
        """
        Cria uma OP já finalizada, consome componentes e dá entrada no produto final de forma imediata.
        Usado para o registro rápido de produção (+).
        """
        # Validações Iniciais
        if float(quantidade) <= 0:
            raise ValueError("Quantidade deve ser positiva.")
        
        product = product_service.get_by_id(produto_id)
        if not product:
            raise ValueError(f"Produto {produto_id} não encontrado.")
        
        # Enriquecer para garantir mapeamento de campos (nome -> name, etc)
        product = product_service.enrich_product_data(product)

        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
             raise ValueError("Depósito de produção padrão não configurado.")

        # 1. Verifica se o produto tem Ficha Técnica (BOM)
        bom_components = product_service.get_bom_components(produto_id)
        if not bom_components:
            raise ValueError(f"Produção não permitida: O produto '{product.get('name', produto_id)}' não possui Ficha Técnica (BOM) cadastrada.")

        # 2. Cria a OP já como COMPLETED (para histórico/rastreio)
        op_data = {
            'ordem_id': str(uuid.uuid4()),
            'produto_id': produto_id,
            'sku': product.get('sku', ''),
            'descricao': f"Produção imediata registrada em {data_producao}",
            'quantidade': int(float(quantidade)),  # Converter para inteiro
            'status': 'COMPLETED',
            'data_inicio': datetime.utcnow().date().isoformat(),
            'data_fim': datetime.utcnow().date().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'responsavel_id': int(user_id) if str(user_id).isdigit() else None
        }

        # Insert OP
        res_op = self.table.insert(op_data).execute()
        if not res_op.data:
            raise Exception("Falha ao criar Ordem de Produção.")

        op_created = res_op.data[0]
        po_id = str(op_created['id'])

        # Realizar a produção com insumos em uma transação atômica
        # Como o Supabase não suporta transações verdadeiras, faremos uma implementação manual
        # com lógica de compensação para garantir atomicidade

        # --- VERIFICAÇÃO DE ESTOQUE (Aviso, não trava) ---
        warning_msg = None
        insufficient_stock = []
        for comp in bom_components:
            qty_required = float(comp['quantity']) * float(quantidade)
            saldo = estoque_service.get_saldo_atual(comp['component_id'], deposito_id)
            available = float(saldo.get('quantidade_disponivel', 0))
            
            if qty_required > available:
                shortage = qty_required - available
                comp_name = comp.get('name') or comp.get('descricao') or comp['component_id']
                insufficient_stock.append(f"{comp_name} (Faltam {shortage:.2f})")
        
        if insufficient_stock:
            warning_msg = f"Aviso: Os seguintes componentes ficaram com estoque negativo: {', '.join(insufficient_stock)}."
        # -------------------------------------------------------

        componentes_registrados = []  # Para rastrear componentes já registrados
        entrada_acabado_realizada = False
        
        try:
            # 3. Processa BOM e Movimenta Estoque

            # 3.1 Consumir Componentes
            for comp in bom_components:
                qty_required = float(comp['quantity']) * float(quantidade)

                # Registra movimento de saída (consumo)
                estoque_service.registrar_saida(
                    produto_id=comp['component_id'],
                    deposito_id=deposito_id,
                    quantidade=qty_required,
                    motivo=f"Consumo OP {po_id} (Imediata)",
                    usuario_id=int(user_id) if str(user_id).isdigit() else None
                )

                # Registra na tabela de componentes da OP para rastreabilidade
                comp_data = {
                    'ordem_producao_id': po_id,
                    'componente_id': comp['component_id'],
                    'sku': comp.get('sku', ''),
                    'descricao': comp.get('name', ''),
                    'quantidade_necessaria': int(qty_required),
                    'quantidade_utilizada': int(qty_required),
                    'status': 'CONCLUIDO'
                }

                # Armazena para rastreamento (lógica de reversão)
                componentes_registrados.append(comp_data)

                # Insere no banco de dados
                self.components_table.insert(comp_data).execute()

            # 3.2 Entrada do Produto Acabado
            estoque_service.registrar_entrada(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=float(quantidade),
                observacao=f"Conclusão OP {po_id} (Imediata)",
                usuario_id=int(user_id) if str(user_id).isdigit() else None
            )
            entrada_acabado_realizada = True

            # --- INTEGRAÇÃO COM DASHBOARD DE DEMANDA ---
            try:
                from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
                
                # Identifica o papel do produto
                role = product_service.identify_product_role(str(produto_id))
                
                # Regra: Miolos NÃO sensibilizam demanda na entrada (+), apenas na saída (-)
                if role != 'MIOLO':
                    demanda_producao_service.alocar_producao_automatica(
                        produto_id=produto_id,
                        quantidade=float(quantidade),
                        user_id=user_id
                    )
            except Exception as demanda_error:
                print(f"Erro ao alocar produção imediata de {produto_id} para demandas: {demanda_error}")
            
            # 3. Log de Produção Diária
            from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
            
            try:
                log_date = datetime.strptime(data_producao, '%Y-%m-%d').date()
            except ValueError:
                log_date = datetime.fromisoformat(data_producao).date()

            daily_production_log_service.create_log(
                log_date=log_date,
                product_id=produto_id,
                product_name=product['name'],
                quantity=float(quantidade),
                production_order_id=po_id,
                component_stock_snapshot=[],
                user_email=str(user_id)
            )

            return {
                'success': True,
                'op': op_created,
                'message': 'Produção registrada com sucesso.',
                'warning': warning_msg
            }

        except Exception as e:
            # Lógica de Compensação (Rollback Manual)
            print(f"Erro durante produção imediata: {str(e)}. Tentando reverter...")

            # 1. Reverter os componentes registrados (devolver ao estoque)
            for comp_data in componentes_registrados:
                try:
                    estoque_service.registrar_entrada(
                        produto_id=comp_data['componente_id'],
                        deposito_id=deposito_id,
                        quantidade=comp_data['quantidade_necessaria'],
                        observacao=f"Reversão da OP {po_id} - Erro na produção",
                        usuario_id=int(user_id) if str(user_id).isdigit() else None
                    )
                except Exception as revert_comp_error:
                    print(f"CRITICAL: Erro ao reverter componente {comp_data['componente_id']}: {str(revert_comp_error)}")

            # 2. Reverter a entrada do produto acabado (se ocorreu)
            if entrada_acabado_realizada:
                try:
                    estoque_service.registrar_saida(
                        produto_id=produto_id,
                        deposito_id=deposito_id,
                        quantidade=float(quantidade),
                        motivo=f"Reversão da OP {po_id} - Erro na produção",
                        usuario_id=int(user_id) if str(user_id).isdigit() else None
                    )
                except Exception as revert_prod_error:
                    print(f"CRITICAL: Erro ao reverter entrada do produto acabado: {str(revert_prod_error)}")

            # 3. Limpeza do Banco de Dados (OP e Componentes)
            try:
                self.components_table.delete().eq('ordem_producao_id', po_id).execute()
                self.table.delete().eq('id', po_id).execute()
            except Exception as db_cleanup_error:
                print(f"Erro ao limpar registros da OP {po_id} no banco: {db_cleanup_error}")
            
            # Re-lança a exceção original para o chamador
            raise e



ordem_producao_service = OrdemProducaoService()

