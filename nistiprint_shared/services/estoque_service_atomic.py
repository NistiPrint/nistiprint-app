from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.uom_conversion_service import uom_conversion_service
from nistiprint_shared.services.deposito_service import deposito_service
from nistiprint_shared.services.system_log_service import system_log_service

class EstoqueServiceAtomic:
    """Serviço para gerenciamento de estoque e movimentações com transações atômicas (Supabase Version)"""

    def __init__(self):
        self._movimentacoes_table = None
        self._saldos_table = None

    @property
    def movimentacoes_table(self):
        if self._movimentacoes_table is None:
            self._movimentacoes_table = supabase_db.table('movimentacoes_estoque')
        return self._movimentacoes_table

    @property
    def saldos_table(self):
        if self._saldos_table is None:
            self._saldos_table = supabase_db.table('estoque_atual')
        return self._saldos_table

    def _resolve_deposito(self, deposito_id: Any) -> Any:
        """Resolve deposito_id. If None, tries to find default."""
        if deposito_id:
            return deposito_id

        # First, try to get the default deposit from deposit service
        default_deposito = deposito_service.get_default()

        if default_deposito:
            return default_deposito['id']

        # If no default deposit is found in the deposit service, check system configuration
        from nistiprint_shared.services.app_config_service import app_config_service
        config_default_deposit_id = app_config_service.get_config('default_production_deposit_id')

        if config_default_deposit_id:
            # Validate that the configured deposit actually exists
            configured_deposit = deposito_service.get_by_id(config_default_deposit_id)
            if configured_deposit:
                return configured_deposit['id']

        # If no default deposit is found, try to get the first active deposit as fallback
        all_deposits = deposito_service.get_all()
        if all_deposits:
            return all_deposits[0]['id']

        raise ValueError("Depósito não informado e nenhum depósito padrão configurado.")

    def _validate_stock_eligibility(self, produto_id: Any):
        """
        Validates if the product can hold stock (is not a Parent Product).
        Raises ValueError if the product is a template for variations.
        """
        try:
            from nistiprint_shared.services.product_service import product_service
            # Ensure ID is string for the service check
            if not product_service.can_hold_stock(str(produto_id)):
                raise ValueError("Este produto possui variações. Selecione a cor/tamanho específico (Variação) para movimentar o estoque.")
        except ImportError:
            # Fallback if circular import or service not ready (unlikely in prod)
            pass
        except ValueError as ve:
            raise ve
        except Exception as e:
            # Log warning but don't block if check fails for other reasons
            print(f"Warning: Could not validate stock eligibility for product {produto_id}: {e}")

    def _validate_sector_permission(self, produto_id: Any, user_context: Dict[str, Any]):
        """
        Verifica se o usuário tem permissão para movimentar este produto.
        Regra: Admin move tudo. Usuário comum só move produtos do seu setor.
        Abordagem inicial: Permite produtos sem setor definido.
        """
        if not user_context:
            # Operações de sistema (sem usuário) podem ser permitidas
            return

        if user_context.get('is_admin'):
            return

        from nistiprint_shared.services.product_service import product_service
        product = product_service.get_by_id(str(produto_id))

        if not product:
            raise ValueError(f"Produto {produto_id} não encontrado.")

        setor_produto = product.get('setor_responsavel_id')

        # Se o produto não tem setor definido, liberamos para evitar travamento na migração
        # Esta é a abordagem inicial menos restritiva
        if setor_produto is None:
            return

        user_setor = user_context.get('setor_id')

        if str(setor_produto) != str(user_setor):
            raise PermissionError(
                f"Acesso Negado: Este produto pertence ao setor '{product.get('setor_responsavel_nome')}' "
                f"e você é do setor '{user_context.get('setor_nome')}'."
            )

    def registrar_entrada(self, produto_id: Any, deposito_id: Any, quantidade: float,
                         observacao: str = "", ordem_compra_id: Optional[str] = None,
                         usuario_id: Optional[int] = None, unit_name: Optional[str] = None,
                         user_context: dict = None, allow_negative_stock: bool = True) -> str:
        """Registra entrada de mercadoria no estoque."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)  # Nova validação
        deposito_id = self._resolve_deposito(deposito_id)
        final_quantity = quantidade
        if unit_name:
            try:
                conversions = uom_conversion_service.get_conversions_for_product(str(produto_id))
            except Exception as e:
                print(f"Erro ao buscar conversões para o produto {produto_id}: {e}")
                conversions = []

            matching_conversion = next((c for c in conversions if c.get('unitName') == unit_name), None)
            if matching_conversion:
                final_quantity = quantidade * matching_conversion['conversionFactor']
                observacao = f"{observacao} (Entrada de {quantidade} {unit_name})"
            else:
                raise ValueError(f"A proporção '{unit_name}' não foi encontrada para o produto ID {produto_id}.")

        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='ENTRADA',
            quantidade=final_quantity,
            motivo=observacao,
            documento_referencia=ordem_compra_id,
            usuario_id=usuario_id,
            user_context=user_context,
            allow_negative_stock=allow_negative_stock
        )

    def registrar_saida(self, produto_id: Any, deposito_id: Any, quantidade: float,
                       motivo: str = "", usuario_id: Optional[int] = None,
                       user_context: dict = None, allow_negative_stock: bool = True) -> str:
        """Registra saída de mercadoria do estoque."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)  # Nova validação
        deposito_id = self._resolve_deposito(deposito_id)
        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='SAIDA',
            quantidade=-abs(quantidade),
            motivo=motivo,
            usuario_id=usuario_id,
            user_context=user_context,
            allow_negative_stock=allow_negative_stock
        )

    def registrar_balanco(self, produto_id: Any, deposito_id: Any, quantidade_ajuste: float,
                         motivo: str = "", usuario_id: Optional[int] = None, unit_name: Optional[str] = None,
                         user_context: dict = None, allow_negative_stock: bool = False) -> str:
        """Registra ajuste/balanço de inventário."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)  # Nova validação
        deposito_id = self._resolve_deposito(deposito_id)
        final_quantity_ajuste = quantidade_ajuste
        if unit_name:
            try:
                conversions = uom_conversion_service.get_conversions_for_product(str(produto_id))
            except Exception as e:
                print(f"Erro ao buscar conversões para o produto {produto_id}: {e}")
                conversions = []

            matching_conversion = next((c for c in conversions if c.get('unitName') == unit_name), None)
            if matching_conversion:
                final_quantity_ajuste = quantidade_ajuste * matching_conversion['conversionFactor']
                motivo = f"{motivo} (Ajuste de {quantidade_ajuste} {unit_name})"
            else:
                raise ValueError(f"A proporção '{unit_name}' não foi encontrada para o produto ID {produto_id}.")

        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='BALANCO',
            quantidade=final_quantity_ajuste,
            motivo=motivo,
            usuario_id=usuario_id,
            user_context=user_context,
            allow_negative_stock=allow_negative_stock
        )

    def registrar_transferencia(self, produto_id: Any, deposito_origem_id: Any, deposito_destino_id: Any,
                               quantidade: float, observacao: str = "", usuario_id: Optional[int] = None,
                               user_context: dict = None, allow_negative_stock: bool = True) -> str:
        """Registra transferência de estoque entre depósitos."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)  # Nova validação
        if deposito_origem_id == deposito_destino_id:
            raise ValueError("Depósito de origem e destino devem ser diferentes.")

        # Realizar a transferência em uma transação atômica
        with supabase_db.transaction() as transaction:
            try:
                # 1. Registrar Saída do Origem
                saida_id = self._registrar_movimento(
                    produto_id=produto_id,
                    deposito_id=deposito_origem_id,
                    tipo_movimentacao='TRANSFERENCIA_SAIDA',
                    quantidade=-abs(quantidade),
                    motivo=f"Transferência para depósito {deposito_destino_id}. {observacao}",
                    usuario_id=usuario_id,
                    user_context=user_context,
                    transaction=transaction,
                    allow_negative_stock=allow_negative_stock
                )

                # 2. Registrar Entrada no Destino
                entrada_id = self._registrar_movimento(
                    produto_id=produto_id,
                    deposito_id=deposito_destino_id,
                    tipo_movimentacao='TRANSFERENCIA_ENTRADA',
                    quantidade=abs(quantidade),
                    motivo=f"Transferência do depósito {deposito_origem_id}. {observacao}",
                    usuario_id=usuario_id,
                    user_context=user_context,
                    transaction=transaction,
                    allow_negative_stock=True  # Permitir entrada em qualquer situação
                )

                # Confirmar a transação
                transaction.commit()
                return entrada_id  # Retornar o ID da movimentação de entrada
            except Exception as e:
                # Em caso de erro, fazer rollback
                transaction.rollback()
                raise e

    def movimentar_por_delta(self, produto_id: Any, delta: float, role: str, motivo: str = "", usuario_id: Optional[int] = None, user_context: dict = None, allow_negative_stock: bool = True) -> None:
        """
        Processa uma movimentação de estoque baseada em um 'Delta' (mudança manual no dashboard).
        Se delta > 0 (aumentou o progresso), registra SAÍDA (consumo).
        Se delta < 0 (reduziu o progresso), registra ENTRADA (estorno).
        """
        if delta == 0: return

        from nistiprint_shared.services.app_config_service import app_config_service
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

        if delta > 0:
            # Aumentou progresso -> CONSUMO (SAÍDA)
            self.registrar_saida(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=abs(delta),
                motivo=f"{motivo} (Consumo via Dashboard)",
                usuario_id=usuario_id,
                user_context=user_context,
                allow_negative_stock=allow_negative_stock
            )
        else:
            # Reduziu progresso -> ESTORNO (ENTRADA)
            # Para Miolos/Capas, a entrada deve ser simples (não gera nova produção de subcomponentes)
            self.registrar_entrada(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=abs(delta),
                observacao=f"{motivo} (Estorno via Dashboard)",
                usuario_id=usuario_id,
                user_context=user_context,
                allow_negative_stock=True  # Permitir entrada em qualquer situação
            )

    def registrar_producao_com_insumos(self, produto_id: Any, quantidade: float, deposito_id: Any = None,
                                     motivo: str = "", usuario_id: Optional[int] = None, user_context: dict = None, allow_negative_stock: bool = True) -> str:
        """
        Registra a entrada de um produto produzido e baixa automaticamente seus componentes via BOM.
        Por padrão, permite estoque negativo nos insumos (não trava o processo se faltar insumo).
        """
        from nistiprint_shared.services.bom_service import bom_service

        deposito_id = self._resolve_deposito(deposito_id)

        # Realizar a produção com insumos em uma transação atômica
        with supabase_db.transaction() as transaction:
            try:
                # 1. Registrar entrada do produto produzido
                mov_id = self.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=quantidade,
                    observacao=motivo,
                    usuario_id=usuario_id,
                    user_context=user_context,
                    allow_negative_stock=True  # Permitir entrada em qualquer situação
                )

                # 2. Buscar componentes na BOM e baixar
                try:
                    componentes = bom_service.get_bom_for_produto(int(produto_id))
                    for comp in componentes:
                        qtd_consumo = comp.quantidade * quantidade
                        # Registra saída do insumo (permite negativo por padrão em registrar_saida se não validarmos)
                        # O método registrar_saida atual lança ValueError se saldo insuficiente.
                        # Para atender ao requisito "Não Travamento", precisamos ignorar essa validação específica aqui.
                        try:
                            self._registrar_movimento(
                                produto_id=comp.componente_id,
                                deposito_id=deposito_id,
                                tipo_movimentacao='SAIDA_INSUMO_PRODUCAO',
                                quantidade=-abs(qtd_consumo),
                                motivo=f"Consumo automático para produção de {quantidade} un de ID {produto_id}",
                                usuario_id=usuario_id,
                                user_context=user_context,
                                allow_negative_stock=allow_negative_stock  # Permitir saída mesmo com saldo insuficiente
                            )
                        except Exception as e:
                            print(f"ERRO ao baixar insumo {comp.componente_id} para produto {produto_id}: {e}")
                            # Loga mas continua (Resiliência)
                except Exception as e:
                    print(f"Aviso: Produto {produto_id} sem BOM ou erro ao processar insumos: {e}")

                # Confirmar a transação
                transaction.commit()
                return mov_id
            except Exception as e:
                # Em caso de erro, fazer rollback
                transaction.rollback()
                raise e

    def _update_saldo(self, produto_id: Any, deposito_id: Any, quantidade_movimento: float, tipo_movimentacao: str, transaction=None, allow_negative_stock: bool = None) -> Tuple[float, float]:
        """Atualiza o saldo atual na tabela estoque_atual."""
        # Busca registro existente
        query = self.saldos_table.select("*").eq('produto_id', produto_id).eq('deposito_id', deposito_id)

        if transaction:
            query = transaction.query(query)

        response = query.execute()

        saldo_anterior = 0
        reservado = 0

        if response.data:
            record = response.data[0]
            saldo_anterior = float(record.get('saldo_atual', 0))
            reservado = float(record.get('reservado', 0))

            # Para BALANCO, calculamos a diferença entre o valor informado e o saldo atual
            if tipo_movimentacao == 'BALANCO':
                diferenca = quantidade_movimento - saldo_anterior
                saldo_posterior = quantidade_movimento
                # Por padrão, não permitimos estoque negativo em operações de balanço
                if allow_negative_stock is None:
                    allow_negative_stock = False
            else:
                diferenca = quantidade_movimento
                saldo_posterior = saldo_anterior + diferenca
                # Por padrão, permitimos estoque negativo em outras operações
                if allow_negative_stock is None:
                    allow_negative_stock = True

            # Validação para impedir saldo negativo, exceto quando explicitamente permitido
            if saldo_posterior < 0 and not allow_negative_stock:
                raise ValueError(f"Operação de {tipo_movimentacao} resultaria em saldo negativo para o produto {produto_id}. Saldo atual: {saldo_anterior}, Quantidade movimento: {quantidade_movimento}")

            # Log de alerta para saldo negativo (apenas informativo, não impede a operação se allow_negative_stock=True)
            if saldo_posterior < 0:
                 print(f"AVISSO: Saldo negativo gerado para o produto {produto_id}. Saldo atual: {saldo_posterior}")

            update_data = {
                'saldo_atual': saldo_posterior,
                'ultima_atualizacao': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }

            if transaction:
                transaction.update(self.saldos_table, update_data).eq('id', record['id']).execute()
            else:
                self.saldos_table.update(update_data).eq('id', record['id']).execute()
        else:
            # Criar novo registro de saldo
            saldo_anterior = 0
            saldo_posterior = quantidade_movimento if tipo_movimentacao != 'BALANCO' else quantidade_movimento

            # Determinar política de estoque negativo baseada no tipo de movimentação
            if allow_negative_stock is None:
                if tipo_movimentacao == 'BALANCO':
                    allow_negative_stock = False
                else:
                    allow_negative_stock = True

            if saldo_posterior < 0 and tipo_movimentacao != 'BALANCO' and not allow_negative_stock:
                raise ValueError(f"Não é possível iniciar estoque com saldo negativo para o produto {produto_id}")

            insert_data = {
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'saldo_atual': saldo_posterior,
                'reservado': 0,
                'nivel_minimo': 0,
                'ultima_atualizacao': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }

            if transaction:
                transaction.insert(self.saldos_table, insert_data).execute()
            else:
                self.saldos_table.insert(insert_data).execute()

        return saldo_anterior, saldo_posterior

    def _registrar_movimento(self, produto_id: Any, deposito_id: Any, tipo_movimentacao: str,
                           quantidade: float, motivo: str = "",
                           documento_referencia: Optional[str] = None,
                           usuario_id: Optional[int] = None,
                           user_context: dict = None,
                           transaction=None,
                           allow_negative_stock: bool = False) -> str:
        """Interno: registra movimentação e atualiza saldo."""
        try:
            # 1. Atualizar Saldo
            saldo_antes, saldo_depois = self._update_saldo(produto_id, deposito_id, quantidade, tipo_movimentacao, transaction, allow_negative_stock)

            # 2. Inserir Movimentação
            # Para BALANCO, a quantidade registrada é a diferença entre o saldo antes e depois
            if tipo_movimentacao == 'BALANCO':
                quantidade_registrada = float(quantidade - saldo_antes)  # A diferença real
            else:
                # Para outros tipos, usamos a diferença entre saldo_depois e saldo_antes
                quantidade_registrada = float(saldo_depois - saldo_antes)

            mov_data = {
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'tipo_movimentacao': tipo_movimentacao,
                'quantidade': abs(quantidade_registrada),
                'saldo_antes': float(saldo_antes),
                'saldo_depois': float(saldo_depois),
                'documento_referencia': documento_referencia,
                'motivo': motivo,
                'usuario_id': usuario_id,
                'data_movimentacao': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat()
            }

            if transaction:
                response = transaction.insert(self.movimentacoes_table, mov_data).execute()
            else:
                response = self.movimentacoes_table.insert(mov_data).execute()

            if response.data:
                return str(response.data[0]['id'])
            else:
                raise Exception("Falha ao inserir o registro de movimentação")
        except Exception as e:
            print(f"Erro no registro de movimento de estoque: {e}")
            raise

    def get_saldo_atual(self, produto_id: Any, deposito_id: Any = None) -> Dict[str, Any]:
        deposito_id = self._resolve_deposito(deposito_id)
        response = self.saldos_table.select("*").eq('produto_id', produto_id).eq('deposito_id', deposito_id).execute()
        if response.data:
            record = response.data[0]
            return {
                'produto_id': record['produto_id'],
                'deposito_id': record['deposito_id'],
                'quantidade': record['saldo_atual'],
                'quantidade_reservada': record.get('reservado', 0),
                'quantidade_disponivel': record.get('disponivel', record['saldo_atual']),
                'ultima_atualizacao': record['ultima_atualizacao']
            }
        return {'quantidade': 0, 'quantidade_reservada': 0, 'quantidade_disponivel': 0}

    def get_saldos_em_lote(self, produto_ids: List[Any], deposito_id: Any = None) -> Dict[str, Dict[str, Any]]:
        """Busca saldos de múltiplos produtos de uma vez para otimização de performance."""
        # Sanitização básica de IDs
        clean_ids = [str(pid) for pid in produto_ids if pid is not None and str(pid).strip()]
        
        if not clean_ids:
            return {}
            
        try:
            deposito_id = self._resolve_deposito(deposito_id)
            query = self.saldos_table.select("*").eq('deposito_id', deposito_id).in_('produto_id', clean_ids)
            response = supabase_db.execute_with_retry(query)

            saldos = {}
            if response and response.data:
                for record in response.data:
                    produto_id = str(record['produto_id'])
                    saldos[produto_id] = {
                        'produto_id': record['produto_id'],
                        'deposito_id': record['deposito_id'],
                        'quantidade': record['saldo_atual'],
                        'quantidade_reservada': record.get('reservado', 0),
                        'quantidade_disponivel': record.get('disponivel', record['saldo_atual']),
                        'ultima_atualizacao': record['ultima_atualizacao']
                    }

            # Para produtos sem saldo, retornar valores padrão
            for produto_id in clean_ids:
                if produto_id not in saldos:
                    saldos[produto_id] = {'quantidade': 0, 'quantidade_reservada': 0, 'quantidade_disponivel': 0}

            return saldos
        except Exception as e:
            print(f"ERRO SILENCIOSO em get_saldos_em_lote (Atomic): {e}")
            
            # Registrar no log do sistema para auditoria
            system_log_service.log_estoque_error(
                message=f"Falha ao buscar saldos em lote (Atomic): {str(e)}",
                action="get_saldos_em_lote_atomic",
                reference_id=str(deposito_id) if deposito_id else "NONE",
                metadata={
                    "produto_ids": clean_ids,
                    "deposito_id": str(deposito_id),
                    "error": str(e)
                }
            )

            # Em caso de erro (ex: deposito não encontrado), retorna zerado para não travar a UI
            fallback = {}
            for pid in clean_ids:
                fallback[pid] = {'quantidade': 0, 'quantidade_reservada': 0, 'quantidade_disponivel': 0}
            return fallback

    def get_posicao_estoque(self, filtro_produtos: Optional[List[str]] = None, filter_by_sector_id: str = None) -> List[Dict[str, Any]]:
        """Busca a posição atual de todos os estoques."""
        query = self.saldos_table.select("*, produtos(nome, sku)")

        if filtro_produtos:
            query = query.in_('produto_id', filtro_produtos)

        # Adiciona filtro por setor responsável se especificado
        if filter_by_sector_id:
            query = query.in_('produtos.setor_responsavel_id', [filter_by_sector_id])

        response = query.execute()
        results = []
        for row in response.data:
            item = dict(row)
            item['quantidade'] = item.get('saldo_atual', 0)
            results.append(item)
        return results

    def get_recent_movimentacoes(self, limit: int = 20, tipo_movimento: str = None, filter_by_sector_id: str = None) -> List[Dict[str, Any]]:
        """Busca as movimentações mais recentes."""
        query = self.movimentacoes_table.select("*, produtos(nome, sku), depositos(nome)")
        if tipo_movimento:
            query = query.eq('tipo_movimentacao', tipo_movimento.upper())

        # Adiciona filtro por setor responsável se especificado
        if filter_by_sector_id:
            query = query.in_('produtos.setor_responsavel_id', [filter_by_sector_id])

        response = query.order('data_movimentacao', desc=True).limit(limit).execute()
        results = []
        for row in response.data:
            m = dict(row)
            m['tipo_movimento'] = m.get('tipo_movimentacao')
            results.append(m)
        return results

    def get_movimentacoes_produto(self, produto_id: Any, deposito_id: Any = None, tipo_movimento: str = None,
                                 data_inicio: datetime = None, data_fim: datetime = None, limit: int = 100, filter_by_sector_id: str = None) -> List[Dict[str, Any]]:
        """Busca histórico de movimentações de um produto específico."""
        query = self.movimentacoes_table.select("*, produtos(nome, sku), depositos(nome)").eq('produto_id', produto_id)

        if deposito_id:
            query = query.eq('deposito_id', deposito_id)
        if tipo_movimento:
            query = query.eq('tipo_movimentacao', tipo_movimento.upper())
        if data_inicio:
            query = query.gte('data_movimentacao', data_inicio.isoformat())
        if data_fim:
            query = query.lte('data_movimentacao', data_fim.isoformat())

        # Adiciona filtro por setor responsável se especificado
        if filter_by_sector_id:
            query = query.in_('produtos.setor_responsavel_id', [filter_by_sector_id])

        response = query.order('data_movimentacao', desc=True).limit(limit).execute()
        results = []
        for row in response.data:
            m = dict(row)
            m['tipo_movimento'] = m.get('tipo_movimentacao')
            results.append(m)
        return results

    def get_alertas_estoque(self, filter_by_sector_id: str = None) -> List[Dict[str, Any]]:
        """Busca produtos com estoque abaixo do nível mínimo ou com risco de ruptura."""
        query = self.saldos_table.select("*, produtos(nome, sku)")

        # Adiciona filtro por setor responsável se especificado
        if filter_by_sector_id:
            query = query.in_('produtos.setor_responsavel_id', [filter_by_sector_id])

        response = query.execute()
        alertas = []
        for s in response.data:
            disponivel = float(s.get('disponivel', 0))
            minimo = float(s.get('nivel_minimo', 0))
            saldo_fisico = float(s.get('saldo_atual', 0))
            reservado = float(s.get('reservado', 0))

            if disponivel < 0:
                alertas.append({
                    'tipo': 'RISCO_RUPTURA',
                    'produto_id': s['produto_id'],
                    'sku': s.get('produtos', {}).get('sku'),
                    'nome': s.get('produtos', {}).get('nome'),
                    'disponivel': disponivel,
                    'reservado': reservado,
                    'saldo_fisico': saldo_fisico,
                    'mensagem': f"Risco de ruptura! Reservas ({reservado}) excedem saldo físico ({saldo_fisico})."
                })
            elif disponivel < minimo:
                alertas.append({
                    'tipo': 'ESTOQUE_BAIXO',
                    'produto_id': s['produto_id'],
                    'sku': s.get('produtos', {}).get('sku'),
                    'nome': s.get('produtos', {}).get('nome'),
                    'disponivel': disponivel,
                    'minimo': minimo,
                    'mensagem': f"Estoque disponível ({disponivel}) abaixo do mínimo ({minimo})."
                })
        return alertas

    def get_abc_analysis(self, days: int = 30) -> Dict[str, Any]:
        """Realiza análise Curva ABC baseada no volume de saídas e custo dos produtos."""
        start_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # 1. Buscar saídas no período
        response = self.movimentacoes_table.select("produto_id, quantidade")\
            .eq('tipo_movimentacao', 'saida')\
            .gte('data_movimentacao', start_date)\
            .execute()

        movs = response.data
        if not movs:
            return {'A': [], 'B': [], 'C': []}

        # 2. Agrupar quantidades por produto
        consumo_por_produto = {}
        for m in movs:
            pid = m['produto_id']
            consumo_por_produto[pid] = consumo_por_produto.get(pid, 0) + abs(m['quantidade'])

        # 3. Buscar custos dos produtos envolvidos
        p_ids = list(consumo_por_produto.keys())
        from nistiprint_shared.services.product_service import product_service
        products = product_service.get_by_ids(p_ids)

        # 4. Calcular Valor de Consumo (Quantidade * Custo)
        ranking = []
        total_valor_geral = 0
        for pid, qtd in consumo_por_produto.items():
            product = products.get(pid, {})
            custo = float(product.get('preco_custo') or 0)
            valor_total = qtd * custo
            total_valor_geral += valor_total
            ranking.append({
                'produto_id': pid,
                'nome': product.get('nome', 'N/A'),
                'sku': product.get('sku', 'N/A'),
                'quantidade': qtd,
                'valor_total': valor_total
            })

        # 5. Ordenar por valor total decrescente
        ranking.sort(key=lambda x: x['valor_total'], reverse=True)

        # 6. Categorizar
        abc = {'A': [], 'B': [], 'C': []}
        acumulado = 0
        for item in ranking:
            acumulado += item['valor_total']
            percentual = (acumulado / total_valor_geral * 100) if total_valor_geral > 0 else 100

            if percentual <= 70:
                abc['A'].append(item)
            elif percentual <= 90:
                abc['B'].append(item)
            else:
                abc['C'].append(item)

        return abc

    def get_inventory_valuation(self) -> List[Dict[str, Any]]:
        """Calcula o valor total do estoque (Saldo * Preço de Custo) de forma otimizada."""
        saldos = self.get_posicao_estoque()
        if not saldos:
            return []

        # Buscar apenas os custos dos produtos que POSSUEM saldo (Otimização Batch)
        produto_ids = list(set([str(s['produto_id']) for s in saldos]))

        from nistiprint_shared.services.product_service import product_service
        # Assume product_service.get_by_ids existe ou usamos client direto
        response = supabase_db.table('produtos').select("id, preco_custo, nome, sku").in_('id', produto_ids).execute()
        custos_map = {str(p['id']): float(p.get('preco_custo') or 0) for p in response.data}

        valuation = []
        for s in saldos:
            pid = str(s['produto_id'])
            custo = custos_map.get(pid, 0)
            quantidade = float(s.get('saldo_atual', 0))
            valor_total = quantidade * custo

            valuation.append({
                **s,
                'preco_custo': custo,
                'valor_total': valor_total
            })

        return valuation

    def reservar_estoque_em_lote(self, itens_reserva: List[Dict[str, Any]], deposito_id: Any = None, allow_backorder: bool = False) -> None:
        """Reserva múltiplas quantidades em lote para otimizar performance."""
        if not itens_reserva: return
        deposito_id = self._resolve_deposito(deposito_id)

        produto_ids = [str(i['produto_id']) for i in itens_reserva]
        # Busca todos os saldos de uma vez
        response = self.saldos_table.select("*").eq('deposito_id', deposito_id).in_('produto_id', produto_ids).execute()
        saldos_map = {str(r['produto_id']): r for r in response.data}

        for item in itens_reserva:
            pid = str(item['produto_id'])
            qtd = float(item['quantidade'])

            if pid not in saldos_map:
                # Inicializa se não existir
                self._update_saldo(item['produto_id'], deposito_id, 0, 'inicializacao_reserva')
                # Recarrega (simplificado, idealmente faríamos uma única busca após inicializar faltantes)
                res = self.saldos_table.select("*").eq('produto_id', item['produto_id']).eq('deposito_id', deposito_id).execute()
                record = res.data[0]
            else:
                record = saldos_map[pid]

            disponivel = float(record.get('disponivel', record['saldo_atual'] - record.get('reservado', 0)))
            if not allow_backorder and qtd > disponivel:
                raise ValueError(f"Estoque insuficiente para {pid}. Disponível: {disponivel}")

            novo_reservado = float(record.get('reservado', 0)) + qtd
            self.saldos_table.update({'reservado': novo_reservado, 'updated_at': datetime.utcnow().isoformat()}).eq('id', record['id']).execute()

    def liberar_reserva_em_lote(self, itens_liberacao: List[Dict[str, Any]], deposito_id: Any = None) -> None:
        """Libera múltiplas reservas em lote."""
        if not itens_liberacao: return
        deposito_id = self._resolve_deposito(deposito_id)

        produto_ids = [str(i['produto_id']) for i in itens_liberacao]
        response = self.saldos_table.select("*").eq('deposito_id', deposito_id).in_('produto_id', produto_ids).execute()
        saldos_map = {str(r['produto_id']): r for r in response.data}

        for item in itens_liberacao:
            pid = str(item['produto_id'])
            qtd = item.get('quantidade')

            if pid in saldos_map:
                record = saldos_map[pid]
                if qtd is None:
                    novo_reservado = 0
                else:
                    novo_reservado = max(0, float(record.get('reservado', 0)) - float(qtd))

                self.saldos_table.update({'reservado': novo_reservado, 'updated_at': datetime.utcnow().isoformat()}).eq('id', record['id']).execute()

    def reservar_estoque(self, produto_id: Any, quantidade: float, deposito_id: Any = None, allow_backorder: bool = False, ordem_id: str = None, tipo_ordem: str = None) -> None:
        """Reserva uma quantidade (Wrapper para o novo método de lote)."""
        self.reservar_estoque_em_lote([{'produto_id': produto_id, 'quantidade': quantidade}], deposito_id, allow_backorder)

    def liberar_reserva(self, produto_id: Any, quantidade: float = None, deposito_id: Any = None, ordem_id: str = None) -> bool:
        """Libera uma reserva, decrementando o campo reservado."""
        deposito_id = self._resolve_deposito(deposito_id)
        response = self.saldos_table.select("*").eq('produto_id', produto_id).eq('deposito_id', deposito_id).execute()
        if response.data:
            record = response.data[0]

            # Se a quantidade não for informada, mas o ordem_id for sintético (SALDO_...), liberamos tudo
            if quantidade is None or (ordem_id and str(ordem_id).startswith('SALDO_')):
                novo_reservado = 0
            else:
                novo_reservado = max(0, float(record.get('reservado', 0)) - quantidade)

            self.saldos_table.update({'reservado': novo_reservado, 'updated_at': datetime.utcnow().isoformat()}).eq('id', record['id']).execute()
            return True
        return False

    def confirmar_saida_reservada(self, produto_id: Any, quantidade: float, deposito_id: Any = None, motivo: str = "", usuario_id: Optional[int] = None, user_context: dict = None, allow_negative_stock: bool = True) -> str:
        """
        Confirma a saída de um item que estava reservado.
        Isso reduz o saldo físico e também a reserva.
        """
        deposito_id = self._resolve_deposito(deposito_id)
        # 1. Registrar a saída física
        mov_id = self.registrar_saida(produto_id, deposito_id, quantidade, motivo, usuario_id, user_context, allow_negative_stock)
        # 2. Liberar a reserva correspondente
        self.liberar_reserva(produto_id, quantidade, deposito_id)
        return mov_id

    def get_all_with_reservations(self) -> List[Dict[str, Any]]:
        """Busca todos os registros de estoque que possuem reserva ativa (>0)."""
        response = self.saldos_table.select("*").gt('reservado', 0).execute()
        return [dict(row) for row in response.data]

    def get_virtual_stock_for_kit(self, produto_id: Any) -> float:
        """
        Calculates the virtual stock for a kit based on its components.
        Virtual stock = min(estoque_componente_n / quantidade_na_bom)
        """
        from nistiprint_shared.services.product_service import product_service
        from nistiprint_shared.services.bom_service import bom_service

        # Get the product to verify it's a kit
        product = product_service.get_by_id(str(produto_id))
        if not product or product.get('formato') != 'kit':
            return 0.0

        # Get BOM components for this kit
        bom_components = bom_service.get_bom_for_produto(int(produto_id))

        if not bom_components:
            return 0.0

        # Calculate virtual stock based on components availability
        virtual_stocks = []

        for component in bom_components:
            component_id = component.componente_id
            required_quantity = component.quantidade

            # Get current stock for this component
            # Using the default deposito for calculation
            component_stock_info = self.get_saldo_atual(component_id, None)
            component_available = component_stock_info.get('quantidade_disponivel', 0)

            # Calculate how many kits we can make with this component
            if required_quantity > 0:
                possible_kits = component_available / required_quantity
                virtual_stocks.append(possible_kits)
            else:
                # If required quantity is 0 or invalid, this component doesn't limit the kit production
                continue

        # The virtual stock of the kit is limited by the scarcest component
        if virtual_stocks:
            return min(virtual_stocks)
        else:
            return 0.0

    def registrar_movimentacao_lote(self, movimentacoes: List[Dict[str, Any]], usuario_id: int, user_context: Dict[str, Any], allow_negative_stock: bool = True) -> Dict[str, Any]:
        """
        Registra múltiplas movimentações de estoque em lote.

        Args:
            movimentacoes: Lista de dicionários contendo 'produto_id', 'quantidade' e 'tipo_movimento'
            usuario_id: ID do usuário realizando a operação
            user_context: Contexto do usuário para validação de permissões
            allow_negative_stock: Define se permite ou não estoque negativo (padrão: True - permitido)

        Returns:
            Dicionário com resumo da operação (quantas movimentações foram bem-sucedidas e quais falharam)
        """
        sucesso = []
        falhas = []

        for movimentacao in movimentacoes:
            try:
                produto_id = movimentacao.get('produto_id')
                quantidade = movimentacao.get('quantidade')
                tipo_movimento = movimentacao.get('tipo_movimento')

                if not all([produto_id, quantidade, tipo_movimento]):
                    falhas.append({
                        'produto_id': produto_id,
                        'erro': 'Dados incompletos para a movimentação'
                    })
                    continue

                if tipo_movimento == 'ENTRADA':
                    self.registrar_entrada(
                        produto_id=produto_id,
                        deposito_id=None,  # Usa depósito padrão
                        quantidade=quantidade,
                        usuario_id=usuario_id,
                        user_context=user_context,
                        allow_negative_stock=True  # Permitir entrada em qualquer situação
                    )
                elif tipo_movimento == 'SAIDA':
                    self.registrar_saida(
                        produto_id=produto_id,
                        deposito_id=None,  # Usa depósito padrão
                        quantidade=quantidade,
                        usuario_id=usuario_id,
                        user_context=user_context,
                        allow_negative_stock=allow_negative_stock  # Permitir saída com saldo negativo por padrão
                    )
                else:
                    falhas.append({
                        'produto_id': produto_id,
                        'erro': f'Tipo de movimento inválido: {tipo_movimento}'
                    })
                    continue

                sucesso.append({
                    'produto_id': produto_id,
                    'tipo_movimento': tipo_movimento,
                    'quantidade': quantidade
                })

            except Exception as e:
                falhas.append({
                    'produto_id': movimentacao.get('produto_id'),
                    'erro': str(e)
                })

        return {
            'sucesso': len(sucesso),
            'falhas': len(falhas),
            'detalhes_sucesso': sucesso,
            'detalhes_falhas': falhas
        }


estoque_service_atomic = EstoqueServiceAtomic()

