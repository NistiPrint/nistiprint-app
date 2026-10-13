from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.uom_conversion_service import uom_conversion_service
from nistiprint_shared.services.deposito_service import deposito_service
from nistiprint_shared.services.system_log_service import system_log_service
from nistiprint_shared.utils.date_utils import get_now_iso

class EstoqueService:
    """Serviço para gerenciamento de estoque e movimentações (Supabase Version)"""

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

    @staticmethod
    def _execute_reservation_command(
        *, action: str, operation_id: str, source_type: str, source_id: str,
        product_id: Any, deposit_id: Any, quantity: Optional[float],
        motivo: str = "", usuario_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        import hashlib
        import json
        import uuid
        from decimal import Decimal, InvalidOperation
        amount = None
        if quantity is not None:
            try:
                amount = Decimal(str(quantity))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError('A quantidade da reserva é inválida.') from exc
            if not amount.is_finite() or amount <= 0 or amount.normalize().as_tuple().exponent < -4:
                raise ValueError('A quantidade da reserva deve ser positiva e ter até 4 casas decimais.')
        semantic = {
            'action': action,
            'source_type': str(source_type).strip().upper(),
            'source_id': str(source_id).strip(),
            'produto_id': int(product_id),
            'deposito_id': int(deposit_id),
            'quantidade': None if amount is None else format(amount.normalize(), 'f'),
            'motivo': str(motivo or ''),
            'actor_id': int(usuario_id) if usuario_id is not None else None,
        }
        if not semantic['source_type'] or not semantic['source_id']:
            raise ValueError('A origem da reserva é obrigatória.')
        try:
            normalized_operation_id = str(uuid.UUID(str(operation_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('operation_id deve ser um UUID estável.') from exc
        content_hash = hashlib.sha256(json.dumps(
            semantic, sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        response = supabase_db.rpc('executar_comando_reserva_estoque', {
            'p_operation_id': normalized_operation_id,
            'p_content_hash': content_hash,
            'p_action': action,
            'p_source': {
                'source_type': semantic['source_type'],
                'source_id': semantic['source_id'],
                'produto_id': semantic['produto_id'],
                'deposito_id': semantic['deposito_id'],
            },
            'p_actor_id': semantic['actor_id'],
            'p_produto_id': semantic['produto_id'],
            'p_deposito_id': semantic['deposito_id'],
            'p_quantidade': semantic['quantidade'],
            'p_motivo': semantic['motivo'],
        }).execute()
        result = response.data[0] if isinstance(response.data, list) and response.data else response.data
        if not isinstance(result, dict) or result.get('status') != 'CONFIRMADO':
            raise RuntimeError(f'Falha ao executar comando de reserva {normalized_operation_id}: {result!r}')
        return result

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
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(
                f"Não foi possível confirmar se o produto {produto_id} aceita movimentação de estoque."
            ) from e

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
                         user_context: dict = None, correlation_id: Optional[str] = None,
                         origem_tipo: Optional[int] = None, data_movimento: Optional[str] = None,
                         operation_id: Optional[str] = None, idempotency_key: Optional[str] = None) -> str:
        """Registra entrada de mercadoria no estoque."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)
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

        return self.registrar_movimento_hibrido(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='ENTRADA',
            quantidade=abs(final_quantity),
            motivo=observacao,
            documento_referencia=ordem_compra_id,
            usuario_id=usuario_id,
            correlation_id=correlation_id,
            origem_tipo=origem_tipo,
            data_movimento=data_movimento,
            operation_id=operation_id,
            idempotency_key=idempotency_key
        )

    def registrar_saida(self, produto_id: Any, deposito_id: Any, quantidade: float,
                       motivo: str = "", usuario_id: Optional[int] = None,
                       user_context: dict = None, documento_referencia: Optional[str] = None,
                       correlation_id: Optional[str] = None, origem_tipo: Optional[int] = None,
                       data_movimento: Optional[str] = None, operation_id: Optional[str] = None,
                       idempotency_key: Optional[str] = None) -> str:
        """Registra saída de mercadoria do estoque."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)
        deposito_id = self._resolve_deposito(deposito_id)
        return self.registrar_movimento_hibrido(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='SAIDA',
            quantidade=-abs(quantidade),
            motivo=motivo,
            usuario_id=usuario_id,
            documento_referencia=documento_referencia,
            correlation_id=correlation_id,
            origem_tipo=origem_tipo,
            data_movimento=data_movimento,
            operation_id=operation_id,
            idempotency_key=idempotency_key
        )

    def registrar_movimento_hibrido(self, produto_id: Any, deposito_id: Any, tipo_movimentacao: str,
                                  quantidade: float, motivo: str = "", 
                                  documento_referencia: Optional[str] = None,
                                  usuario_id: Optional[int] = None,
                                  correlation_id: Optional[str] = None,
                                  origem_tipo: Optional[int] = None,
                                  data_movimento: Optional[str] = None,
                                  operation_id: Optional[str] = None,
                                  idempotency_key: Optional[str] = None,
                                  expected_saldo: Optional[float] = None) -> str:
        """
        Registra o primeiro nível em uma RPC sem fallback de escrita.
        Com o núcleo v2 habilitado, retorna o operation_id persistido.
        """
        from nistiprint_shared.services.estoque_command_service import (
            estoque_command_service,
            new_operation_id,
        )

        if operation_id is None and idempotency_key:
            import uuid
            operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:estoque:{idempotency_key}"))
        operation_id = operation_id or new_operation_id()
        result = estoque_command_service.execute_command(
            {
                'operation_id': operation_id,
                'command_type': tipo_movimentacao,
                'source': {
                    'documento_referencia': str(documento_referencia) if documento_referencia else None,
                    'origem_tipo': origem_tipo,
                },
                'movimentos': [{
                    'produto_id': produto_id,
                    'deposito_id': deposito_id,
                    'tipo_movimentacao': tipo_movimentacao,
                    'quantidade': quantidade,
                    'motivo': motivo,
                    'documento_referencia': str(documento_referencia) if documento_referencia else None,
                    'origem_tipo': origem_tipo,
                    'correlation_id': correlation_id,
                    'expected_saldo': expected_saldo,
                }],
            },
            actor_context={'id': usuario_id} if usuario_id is not None else None,
            allow_when_disabled=True,
        )
        return str(result.get('operation_id') or operation_id)

    def registrar_balanco(self, produto_id: Any, deposito_id: Any, quantidade_ajuste: float,
                         motivo: str = "", observacao: str = "", usuario_id: Optional[int] = None, 
                         unit_name: Optional[str] = None, user_context: dict = None,
                         operation_id: Optional[str] = None, idempotency_key: Optional[str] = None,
                         expected_saldo: Optional[float] = None) -> str:
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

        if expected_saldo is None:
            # Usa a leitura feita no servidor como compare-and-swap; a RPC
            # verifica o valor novamente depois de bloquear o saldo.
            current = self.get_saldo_atual(produto_id, deposito_id)
            expected_saldo = current['quantidade']

        return self.registrar_movimento_hibrido(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimentacao='BALANCO',
            quantidade=final_quantity_ajuste,
            motivo=motivo,
            documento_referencia=observacao or None,
            usuario_id=usuario_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            expected_saldo=expected_saldo,
        )

    def registrar_transferencia(self, produto_id: Any, deposito_origem_id: Any, deposito_destino_id: Any,
                               quantidade: float, observacao: str = "", usuario_id: Optional[int] = None,
                               user_context: dict = None, operation_id: Optional[str] = None,
                               idempotency_key: Optional[str] = None) -> str:
        """Registra transferência de estoque entre depósitos."""
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)  # Nova validação
        if deposito_origem_id == deposito_destino_id:
            raise ValueError("Depósito de origem e destino devem ser diferentes.")

        from nistiprint_shared.services.estoque_command_service import (
            estoque_command_service,
            new_operation_id,
        )
        deposito_origem_id = self._resolve_deposito(deposito_origem_id)
        deposito_destino_id = self._resolve_deposito(deposito_destino_id)
        if operation_id is None and idempotency_key:
            import uuid
            operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:estoque:{idempotency_key}"))
        operation_id = operation_id or new_operation_id()
        result = estoque_command_service.execute_command(
            {
                'operation_id': operation_id,
                'command_type': 'TRANSFERENCIA',
                'source': {'produto_id': int(produto_id)},
                'movimentos': [
                    {
                        'produto_id': produto_id,
                        'deposito_id': deposito_origem_id,
                        'tipo_movimentacao': 'TRANSFERENCIA_SAIDA',
                        'quantidade': -abs(quantidade),
                        'motivo': f"Transferência para depósito {deposito_destino_id}. {observacao}",
                    },
                    {
                        'produto_id': produto_id,
                        'deposito_id': deposito_destino_id,
                        'tipo_movimentacao': 'TRANSFERENCIA_ENTRADA',
                        'quantidade': abs(quantidade),
                        'motivo': f"Transferência do depósito {deposito_origem_id}. {observacao}",
                    },
                ],
            },
            actor_context={'id': usuario_id} if usuario_id is not None else None,
            allow_when_disabled=True,
        )
        return str(result.get('operation_id') or operation_id)

    def movimentar_por_delta(self, produto_id: Any, delta: float, motivo: str = "", 
                           usuario_id: Optional[int] = None, user_context: dict = None,
                           documento_referencia: Optional[str] = None,
                           demanda_id: Optional[Any] = None,
                           item_id: Optional[Any] = None,
                           idempotency_key: Optional[str] = None) -> None:
        """
        Processa uma movimentação de estoque baseada em um 'Delta' (mudança manual no dashboard).
        Aumentos de progresso registram SAÍDA (consumo). Reduções falham até existir
        uma compensação física explícita e auditável.
        """
        if delta < 0:
            raise ValueError('REQUER_COMPENSACAO: redução de progresso não pode gerar entrada física automaticamente.')
        if delta == 0:
            return

        from nistiprint_shared.services.app_config_service import app_config_service
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

        # Documento referência prioritário
        doc_ref = documento_referencia or (f"Demanda:{demanda_id}" if demanda_id else None)
        
        # IDempotency key gerada se não fornecida
        idemp = idempotency_key or (f"delta:{demanda_id}:{item_id}:{delta}" if demanda_id and item_id else None)

        self.registrar_saida(
            produto_id=produto_id,
            deposito_id=deposito_id,
            quantidade=abs(delta),
            motivo=f"{motivo} (Consumo via Dashboard)",
            usuario_id=usuario_id,
            user_context=user_context,
            documento_referencia=doc_ref,
            idempotency_key=idemp
        )

    def registrar_producao_com_insumos(
        self,
        produto_id: Any,
        quantidade: float,
        deposito_id: Any = None,
        motivo: str = "",
        usuario_id: Optional[int] = None,
        user_context: dict = None,
        operation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Confirma produção e consumo da BOM efetiva em uma única operação."""
        import uuid
        from decimal import Decimal, InvalidOperation
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.estoque_command_service import (
            estoque_command_service,
            new_operation_id,
        )

        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)
        try:
            produced = Decimal(str(quantidade))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("A quantidade produzida deve ser numérica.") from exc
        if not produced.is_finite() or produced <= 0 or produced.normalize().as_tuple().exponent < -4:
            raise ValueError("A quantidade produzida deve ser positiva e ter até 4 casas decimais.")

        deposito_id = self._resolve_deposito(deposito_id)
        version = bom_service.publish_effective_version(int(produto_id), actor_id=usuario_id)
        root_node = (version.get('graph') or {}).get('nodes', {}).get(str(int(produto_id)))
        if root_node is None:
            raise ValueError(f"BOM_GRAPH_INCOMPLETE:{produto_id}")
        component_totals = {}
        for line in root_node.get('componentes') or []:
            component_id = int(line['componente_id'])
            amount = produced * Decimal(str(line['quantidade_necessaria']))
            unit = line.get('unidade_medida') or 'un'
            entry = component_totals.setdefault(component_id, {'quantidade_total': Decimal('0'), 'unidade': unit})
            if entry['unidade'] != unit:
                raise ValueError(f'BOM_UNIT_CONFLICT:{component_id}')
            entry['quantidade_total'] += amount
        components = [
            {'componente_id': component_id, 'quantidade_total': format(entry['quantidade_total'].normalize(), 'f')}
            for component_id, entry in sorted(component_totals.items())
        ]
        movements = [{
            "produto_id": int(produto_id),
            "deposito_id": int(deposito_id),
            "tipo_movimentacao": "ENTRADA",
            "quantidade": str(produced),
            "motivo": motivo or "Produção avulsa",
            "documento_referencia": f"BOM_VERSION:{version['id']}",
            "estagio": "PRODUCAO_IMEDIATA",
        }]
        for component in components:
            amount = Decimal(str(component["quantidade_total"]))
            if not amount.is_finite() or amount <= 0 or amount.normalize().as_tuple().exponent < -4:
                raise ValueError(
                    f"A quantidade calculada para o componente {component['componente_id']} "
                    "excede a precisão suportada de 4 casas decimais."
                )
            self._validate_stock_eligibility(component["componente_id"])
            self._validate_sector_permission(component["componente_id"], user_context)
            movements.append({
                "produto_id": int(component["componente_id"]),
                "deposito_id": int(deposito_id),
                "tipo_movimentacao": "SAIDA_INSUMO_PRODUCAO",
                "quantidade": str(-amount),
                "motivo": f"Consumo para produção de {produced} un do produto {produto_id}",
                "documento_referencia": f"BOM_VERSION:{version['id']}",
                "estagio": "PRODUCAO_IMEDIATA",
            })

        if operation_id is None and idempotency_key:
            operation_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"nistiprint:producao-imediata:{idempotency_key}"
            ))
        operation_id = operation_id or new_operation_id()
        result = estoque_command_service.execute_command(
            {
                "operation_id": operation_id,
                "command_type": "PRODUCAO_IMEDIATA",
                "source": {
                    "produto_id": int(produto_id),
                    "deposito_id": int(deposito_id),
                    "quantidade": str(produced),
                    "bom_version_id": str(version["id"]),
                    "bom_content_hash": version["content_hash"],
                },
                "movimentos": movements,
            },
            actor_context={"id": usuario_id} if usuario_id is not None else None,
            allow_when_disabled=True,
        )
        output_movement = next(
            (m for m in result.get("movimentos", [])
             if int(m.get("produto_id", -1)) == int(produto_id)
             and m.get("tipo_movimentacao") == "ENTRADA"),
            None,
        )
        if output_movement is None:
            raise RuntimeError(f"A operação {operation_id} foi confirmada sem movimento de produção.")
        return str(output_movement["movimento_id"])

    def _update_saldo(self, produto_id: Any, deposito_id: Any, quantidade_movimento: float, tipo_movimentacao: str) -> Tuple[float, float]:
        """Desativado: saldo e movimento devem ser atualizados pela mesma RPC."""
        raise RuntimeError('Gravação direta de estoque desativada; use um comando transacional.')

    def _registrar_movimento(self, produto_id: Any, deposito_id: Any, tipo_movimentacao: str,
                           quantidade: float, motivo: str = "", observacao: str = "",
                           documento_referencia: Optional[str] = None,
                           usuario_id: Optional[int] = None,
                           user_context: dict = None) -> str:
        """Desativado: saldo e movimento devem ser atualizados pela mesma RPC."""
        raise RuntimeError('Gravação direta de estoque desativada; use um comando transacional.')

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
            if response is None or getattr(response, 'data', None) is None:
                raise RuntimeError("A consulta de saldos não retornou uma resposta confirmada.")

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
            print(f"ERRO SILENCIOSO em get_saldos_em_lote: {e}")
            
            # Registrar no log do sistema para auditoria
            system_log_service.log_estoque_error(
                message=f"Falha ao buscar saldos em lote: {str(e)}",
                action="get_saldos_em_lote",
                reference_id=str(deposito_id) if deposito_id else "NONE",
                metadata={
                    "produto_ids": clean_ids,
                    "deposito_id": str(deposito_id),
                    "error": str(e)
                }
            )

            raise RuntimeError(f"Não foi possível confirmar os saldos do depósito {deposito_id}.") from e

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

    def get_movimentacoes_consolidadas(self, produto_id: Any = None, deposito_id: Any = None,
                                        demanda_id: Any = None, item_demanda_id: Any = None,
                                        data_inicio: datetime = None, data_fim: datetime = None,
                                        tipo_bloco: str = None, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Busca movimentacoes agrupadas por (correlation_id, estagio) via
        view_movimentacoes_consolidadas. Cada linha eh um bloco logico:
            - tipo_bloco='FINALIZACAO' -> "Finalizacao de N x produto"
            - tipo_bloco='JIT'         -> "Producao JIT de N x produto"
            - tipo_bloco='CONSUMO'     -> consumo direto de estoque

        Filtros sao aplicados sobre os movimentos crus (em movimentos jsonb)
        quando relevantes (produto_id, deposito_id) por meio de pos-processing,
        pois jsonb_path nao eh trivial via PostgREST.
        """
        from nistiprint_shared.database.supabase_db_service import supabase_db
        query = supabase_db.table('view_movimentacoes_consolidadas').select('*')

        if demanda_id is not None:
            try:
                query = query.eq('demanda_id_int', int(demanda_id))
            except (TypeError, ValueError):
                # Se vier o codigo alfanumerico (demanda_id VARCHAR), filtra por ele
                query = query.eq('demanda_codigo', str(demanda_id))
        if item_demanda_id is not None:
            try:
                query = query.eq('item_demanda_id', int(item_demanda_id))
            except (TypeError, ValueError):
                pass
        if tipo_bloco:
            query = query.eq('tipo_bloco', tipo_bloco)
        if data_inicio:
            query = query.gte('data_inicio', data_inicio.isoformat())
        if data_fim:
            query = query.lte('data_inicio', data_fim.isoformat())

        query = query.order('data_inicio', desc=True).limit(limit)
        response = query.execute()
        rows = response.data or []

        # Filtros por produto_id/deposito_id incidem sobre o conteudo jsonb
        # "movimentos". Aplicamos em Python (volume tipico baixo, < 1k linhas).
        if produto_id is not None or deposito_id is not None:
            try:
                pid = int(produto_id) if produto_id is not None else None
            except (TypeError, ValueError):
                pid = None
            try:
                did = int(deposito_id) if deposito_id is not None else None
            except (TypeError, ValueError):
                did = None

            filtered = []
            for row in rows:
                movs = row.get('movimentos') or []
                if pid is not None and not any(m.get('produto_id') == pid for m in movs):
                    continue
                if did is not None and not any(m.get('deposito_id') == did for m in movs):
                    continue
                filtered.append(row)
            rows = filtered

        return rows

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
        """ABC sobre consumo líquido confirmado, valorizado pelo custo atual."""
        from nistiprint_shared.services.consumption_service import consumption_service

        consumo = consumption_service.get_daily_consumption(days=days)
        consumo = {int(pid): row for pid, row in consumo.items() if float(row['total_periodo']) > 0}
        if not consumo:
            return {'A': [], 'B': [], 'C': []}

        p_ids = sorted(consumo)
        from nistiprint_shared.services.product_service import product_service
        products = product_service.get_by_ids(p_ids)

        ranking = []
        total_valor_geral = 0.0
        for pid, consumption in consumo.items():
            product = products.get(pid) or products.get(str(pid)) or {}
            qtd = float(consumption['total_periodo'])
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

        ranking.sort(key=lambda x: (-x['valor_total'], int(x['produto_id'])))

        abc = {'A': [], 'B': [], 'C': []}
        acumulado = 0
        for item in ranking:
            percentual_anterior = acumulado / total_valor_geral if total_valor_geral > 0 else 1
            if percentual_anterior < 0.70:
                abc['A'].append(item)
            elif percentual_anterior < 0.90:
                abc['B'].append(item)
            else:
                abc['C'].append(item)
            acumulado += item['valor_total']
        
        return abc

    def get_inventory_valuation(self) -> List[Dict[str, Any]]:
        """Return cost valuation with physical, reserved, available and planned quantities."""
        saldos = self.get_posicao_estoque()
        if not saldos:
            return []

        # Buscar apenas os custos dos produtos que POSSUEM saldo (Otimização Batch)
        produto_ids = list(set([str(s['produto_id']) for s in saldos]))
        
        from nistiprint_shared.services.product_service import product_service
        # Assume product_service.get_by_ids existe ou usamos client direto
        response = supabase_db.table('produtos').select("id, preco_custo, nome, sku").in_('id', produto_ids).execute()
        custos_map = {str(p['id']): float(p.get('preco_custo') or 0) for p in response.data}
        previsoes = (
            supabase_db.table('previsao_consumo_demanda')
            .select('produto_id, quantidade_prevista')
            .in_('produto_id', produto_ids)
            .eq('status', 'PLANEJADO')
            .execute()
        )
        previsto_por_produto: Dict[str, float] = {}
        for row in previsoes.data or []:
            key = str(row['produto_id'])
            previsto_por_produto[key] = previsto_por_produto.get(key, 0.0) + float(row.get('quantidade_prevista') or 0)

        valuation = []
        for s in saldos:
            pid = str(s['produto_id'])
            custo = custos_map.get(pid, 0)
            quantidade = float(s.get('saldo_atual', 0))
            reservado = float(s.get('reservado') or 0)
            valor_total = quantidade * custo
            
            valuation.append({
                **s,
                'fisico': quantidade,
                'reservado': reservado,
                'disponivel': float(s.get('disponivel') if s.get('disponivel') is not None else quantidade - reservado),
                'previsto': previsto_por_produto.get(pid, 0.0),
                'preco_custo': custo,
                'valor_total': valor_total
            })
            
        return valuation

    def reservar_estoque_em_lote(self, itens_reserva: List[Dict[str, Any]], deposito_id: Any = None, allow_backorder: bool = False) -> None:
        """A reserva sem uma origem explícita não é aceita."""
        if itens_reserva:
            raise ValueError('Informe a origem por item e use reservar_estoque para registrar a reserva transacional.')

    def liberar_reserva_em_lote(self, itens_liberacao: List[Dict[str, Any]], deposito_id: Any = None) -> None:
        """Liberação em lote exige operações idempotentes independentes por origem."""
        if itens_liberacao:
            raise ValueError('Liberação em lote sem chaves idempotentes por origem não é permitida.')

    def reservar_estoque(
        self, produto_id: Any, quantidade: float, deposito_id: Any = None,
        allow_backorder: bool = False, ordem_id: str = None, tipo_ordem: str = None,
        operation_id: str = None, idempotency_key: str = None,
    ) -> None:
        """Reserva por origem usando o RPC transacional e idempotente."""
        import uuid
        if not ordem_id:
            raise ValueError('ordem_id é obrigatório para vincular a reserva à origem.')
        source_type = tipo_ordem or 'ORDEM'
        if operation_id is None and idempotency_key:
            operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'nistiprint:reserva:{idempotency_key}'))
        operation_id = operation_id or str(uuid.uuid5(
            uuid.NAMESPACE_URL, f'nistiprint:reserva:{source_type}:{ordem_id}:{produto_id}'
        ))
        self._execute_reservation_command(
            action='RESERVAR', operation_id=operation_id, source_type=source_type,
            source_id=str(ordem_id), product_id=produto_id, deposit_id=self._resolve_deposito(deposito_id),
            quantity=quantidade,
        )

    def liberar_reserva(
        self, produto_id: Any, quantidade: float = None, deposito_id: Any = None,
        ordem_id: str = None, tipo_ordem: str = None,
        operation_id: str = None, idempotency_key: str = None,
        usuario_id: Optional[int] = None, user_context: dict = None,
    ) -> bool:
        """Libera somente a quantidade ainda reservada para a origem indicada."""
        import uuid
        if not ordem_id:
            raise ValueError('ordem_id é obrigatório para liberar uma reserva vinculada.')
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)
        source_type = tipo_ordem or 'ORDEM'
        if operation_id is None and idempotency_key:
            operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'nistiprint:reserva:{idempotency_key}'))
        if operation_id is None:
            operation_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f'nistiprint:liberacao:{source_type}:{ordem_id}:{produto_id}:{quantidade}',
            ))
        result = self._execute_reservation_command(
            action='LIBERAR', operation_id=operation_id, source_type=source_type,
            source_id=str(ordem_id), product_id=produto_id, deposit_id=self._resolve_deposito(deposito_id),
            quantity=quantidade, usuario_id=usuario_id,
        )
        return float(result.get('quantidade') or 0) > 0

    def confirmar_saida_reservada(
        self, produto_id: Any, quantidade: float, deposito_id: Any = None, motivo: str = "",
        usuario_id: Optional[int] = None, user_context: dict = None,
        ordem_id: str = None, tipo_ordem: str = None,
        operation_id: str = None, idempotency_key: str = None,
    ) -> str:
        """Consome a reserva e baixa o saldo físico em uma única transação."""
        import uuid
        self._validate_stock_eligibility(produto_id)
        self._validate_sector_permission(produto_id, user_context)
        if not ordem_id:
            raise ValueError('ordem_id é obrigatório para confirmar a saída reservada.')
        source_type = tipo_ordem or 'ORDEM'
        if operation_id is None and idempotency_key:
            operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'nistiprint:reserva:{idempotency_key}'))
        operation_id = operation_id or str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f'nistiprint:consumo-reserva:{source_type}:{ordem_id}:{produto_id}:{quantidade}',
        ))
        result = self._execute_reservation_command(
            action='CONSUMIR', operation_id=operation_id, source_type=source_type,
            source_id=str(ordem_id), product_id=produto_id, deposit_id=self._resolve_deposito(deposito_id),
            quantity=quantidade, motivo=motivo, usuario_id=usuario_id,
        )
        if not result.get('movimento_id'):
            raise RuntimeError(f'A operação {operation_id} confirmou o consumo sem movimento de estoque.')
        return str(result['movimento_id'])

    def get_all_with_reservations(self) -> List[Dict[str, Any]]:
        """Lista reservas vinculadas e expõe qualquer saldo legado sem origem."""
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        source_rows: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        offset = 0
        page_size = 1000
        while True:
            response = (supabase_db.table('estoque_reservas_operacionais')
                        .select('*').order('created_at').range(offset, offset + page_size - 1).execute())
            rows = response.data or []
            for row in rows:
                remaining = (
                    float(row.get('quantidade') or 0)
                    - float(row.get('quantidade_consumida') or 0)
                    - float(row.get('quantidade_liberada') or 0)
                )
                if remaining <= 0:
                    continue
                key = (str(row['produto_id']), str(row['deposito_id']))
                bucket = grouped.setdefault(key, {
                    'produto_id': row['produto_id'], 'deposito_id': row['deposito_id'],
                    'reservado': 0.0, 'reservas': [],
                })
                source_type = str(row.get('origem_tipo') or 'ORDEM')
                source_id = str(row.get('origem_id') or '')
                source_key = (key[0], key[1], source_type, source_id)
                reservation = source_rows.get(source_key)
                if reservation is None:
                    reservation = {
                        'quantidade': 0.0,
                        'quantidade_original': 0.0,
                        'quantidade_disponivel': 0.0,
                        'tipo_ordem': source_type,
                        'ordem_id': source_id,
                        'operation_ids': [],
                        'data_reserva': row.get('created_at'),
                    }
                    source_rows[source_key] = reservation
                    bucket['reservas'].append(reservation)
                reservation['quantidade'] += remaining
                reservation['quantidade_original'] += remaining
                reservation['quantidade_disponivel'] += remaining
                if row.get('operation_id'):
                    reservation['operation_ids'].append(str(row['operation_id']))
                bucket['reservado'] += remaining
            if len(rows) < page_size:
                break
            offset += page_size

        legacy_response = self.saldos_table.select(
            'id,produto_id,deposito_id,reservado,updated_at,ultima_atualizacao'
        ).gt('reservado', 0).execute()
        for row in legacy_response.data or []:
            key = (str(row['produto_id']), str(row['deposito_id']))
            bucket = grouped.setdefault(key, {
                'produto_id': row['produto_id'], 'deposito_id': row['deposito_id'],
                'reservado': 0.0, 'reservas': [],
            })
            residual = float(row.get('reservado') or 0) - bucket['reservado']
            if residual > 0:
                bucket['reservas'].append({
                    'quantidade': residual,
                    'quantidade_original': residual,
                    'quantidade_disponivel': residual,
                    'tipo_ordem': 'SEM_ORIGEM',
                    'ordem_id': None,
                    'data_reserva': row.get('updated_at') or row.get('ultima_atualizacao'),
                })
                bucket['reservado'] += residual
        return [row for row in grouped.values() if row['reservado'] > 0]

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

    def registrar_movimentacao_lote(
        self,
        movimentacoes: List[Dict[str, Any]],
        usuario_id: int,
        user_context: Dict[str, Any],
        *,
        operation_id: Optional[str] = None,
        source: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Registra todas as movimentações em uma única operação idempotente.

        Lotes sem identidade e origem explícitas falham antes de qualquer efeito.
        """
        if not operation_id:
            raise ValueError('operation_id é obrigatório para movimentação em lote.')
        if not isinstance(source, dict) or not source.get('source_type') or not source.get('source_id'):
            raise ValueError('source_type e source_id são obrigatórios para movimentação em lote.')
        if not isinstance(movimentacoes, list) or not movimentacoes:
            raise ValueError('O lote deve conter ao menos uma movimentação.')

        from decimal import Decimal, InvalidOperation
        from nistiprint_shared.services.estoque_command_service import (
            estoque_command_service,
        )

        command_movements = []
        for movimentacao in movimentacoes:
            if not isinstance(movimentacao, dict):
                raise ValueError('Cada movimentação do lote deve ser um objeto.')
            produto_id = movimentacao.get('produto_id')
            tipo_movimento = str(movimentacao.get('tipo_movimento') or '').strip().upper()
            if tipo_movimento not in {'ENTRADA', 'SAIDA'}:
                raise ValueError(f'Tipo de movimento inválido: {tipo_movimento or "ausente"}.')
            try:
                produto_id = int(produto_id)
                quantidade = Decimal(str(movimentacao.get('quantidade')))
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise ValueError('produto_id e quantidade devem ser válidos.') from exc
            if produto_id <= 0 or not quantidade.is_finite() or quantidade <= 0:
                raise ValueError('produto_id deve ser positivo e quantidade deve ser finita e maior que zero.')

            self._validate_stock_eligibility(produto_id)
            self._validate_sector_permission(produto_id, user_context)
            deposito_id = self._resolve_deposito(movimentacao.get('deposito_id'))
            try:
                deposito_id = int(deposito_id)
            except (TypeError, ValueError) as exc:
                raise ValueError('O depósito padrão precisa resolver para um ID inteiro válido.') from exc
            signed_quantity = quantidade if tipo_movimento == 'ENTRADA' else -quantidade
            command_movements.append({
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'tipo_movimentacao': tipo_movimento,
                'quantidade': format(signed_quantity.normalize(), 'f'),
                'motivo': str(movimentacao.get('motivo') or ''),
                'documento_referencia': movimentacao.get('documento_referencia'),
                'origem_tipo': movimentacao.get('origem_tipo'),
                'correlation_id': movimentacao.get('correlation_id'),
            })

        return estoque_command_service.execute_command(
            {
                'operation_id': operation_id,
                'command_type': 'MOVIMENTACAO_LOTE',
                'source': source,
                'movimentos': command_movements,
            },
            actor_context={'id': usuario_id},
            allow_when_disabled=True,
        )

estoque_service = EstoqueService()

