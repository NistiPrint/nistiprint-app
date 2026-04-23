from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from uuid import uuid4
from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client
from services.uom_conversion_service import uom_conversion_service

class EstoqueService:
    """Serviço para gerenciamento de estoque e movimentações"""

    def __init__(self):
        self._lancamentos_collection = None
        self._saldos_collection = None

    @property
    def lancamentos_collection(self):
        if self._lancamentos_collection is None:
            self._lancamentos_collection = firestore_client.collection('lancamentos_estoque')
        return self._lancamentos_collection

    @property
    def saldos_collection(self):
        if self._saldos_collection is None:
            self._saldos_collection = firestore_client.collection('estoque_atual')
        return self._saldos_collection

    def registrar_entrada(self, produto_id: str, deposito_id: str, quantidade: float,
                         observacao: str = "", ordem_compra_id: Optional[str] = None,
                         usuario_id: Optional[int] = None, unit_name: Optional[str] = None) -> str:
        """Registra entrada de mercadoria no estoque, com suporte a conversão de unidades."""
        
        final_quantity = quantidade
        if unit_name:
            conversions = uom_conversion_service.get_conversions_for_product(produto_id)
            matching_conversion = next((c for c in conversions if c['unitName'] == unit_name), None)
            
            if matching_conversion:
                final_quantity = quantidade * matching_conversion['conversionFactor']
                observacao = f"{observacao} (Entrada de {quantidade} {unit_name})" # Add context to observation
            else:
                # If a unit_name is provided but not found, raise an error to avoid mistakes.
                raise ValueError(f"A proporção '{unit_name}' não foi encontrada para o produto ID {produto_id}.")

        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimento='ENTRADA',
            quantidade=final_quantity,
            observacao=observacao,
            ordem_compra_id=ordem_compra_id,
            usuario_id=usuario_id
        )

    def registrar_saida(self, produto_id: str, deposito_id: str, quantidade: float,
                       observacao: str = "", usuario_id: Optional[int] = None) -> str:
        """Registra saída de mercadoria do estoque"""
        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimento='SAIDA',
            quantidade=-abs(quantidade),  # Sempre negativo para saída
            observacao=observacao,
            usuario_id=usuario_id
        )

    def registrar_balanco(self, produto_id: str, deposito_id: str, quantidade_ajuste: float,
                         observacao: str = "", usuario_id: Optional[int] = None, unit_name: Optional[str] = None) -> str:
        """Registra ajuste/balanço de inventário, com suporte a conversão de unidades."""
        
        final_quantity_ajuste = quantidade_ajuste
        if unit_name:
            conversions = uom_conversion_service.get_conversions_for_product(produto_id)
            matching_conversion = next((c for c in conversions if c['unitName'] == unit_name), None)
            
            if matching_conversion:
                final_quantity_ajuste = quantidade_ajuste * matching_conversion['conversionFactor']
                observacao = f"{observacao} (Ajuste de {quantidade_ajuste} {unit_name})" # Add context to observation
            else:
                raise ValueError(f"A proporção '{unit_name}' não foi encontrada para o produto ID {produto_id}.")

        return self._registrar_movimento(
            produto_id=produto_id,
            deposito_id=deposito_id,
            tipo_movimento='BALANCO',
            quantidade=final_quantity_ajuste,
            observacao=observacao,
            usuario_id=usuario_id
        )

    def registrar_transferencia(self, produto_id: str, deposito_origem_id: str,
                               deposito_destino_id: str, quantidade: float,
                               observacao: str = "", usuario_id: Optional[int] = None) -> Tuple[str, str]:
        """Registra transferência entre depósitos de forma atômica."""
        
        transaction = firestore_client.db.transaction()
        
        @firestore.transactional
        def transfer_in_transaction(transaction_ref):
            # 1. Atualizar saldo na origem (saída)
            saldo_anterior_origem, saldo_posterior_origem = self._update_saldo_in_transaction(
                transaction_ref, produto_id, deposito_origem_id, -abs(quantidade)
            )

            # 2. Atualizar saldo no destino (entrada)
            saldo_anterior_destino, saldo_posterior_destino = self._update_saldo_in_transaction(
                transaction_ref, produto_id, deposito_destino_id, abs(quantidade)
            )

            # 3. Criar os dois lançamentos (saída e entrada)
            transferencia_id = str(uuid4())
            
            # Lançamento de Saída
            lancamento_saida_ref = self.lancamentos_collection.document(f"{transferencia_id}_saida")
            lancamento_saida_data = {
                'produto_id': produto_id,
                'deposito_id': deposito_origem_id,
                'tipo_movimento': 'TRANSFERENCIA_SAIDA',
                'quantidade': abs(quantidade),
                'saldo_anterior': saldo_anterior_origem,
                'saldo_posterior': saldo_posterior_origem,
                'data_hora': datetime.utcnow(),
                'observacao': f'{observacao} - Transferência para depósito {deposito_destino_id}',
                'usuario_id': usuario_id,
                'transferencia_id': transferencia_id
            }
            transaction_ref.set(lancamento_saida_ref, lancamento_saida_data)

            # Lançamento de Entrada
            lancamento_entrada_ref = self.lancamentos_collection.document(f"{transferencia_id}_entrada")
            lancamento_entrada_data = {
                'produto_id': produto_id,
                'deposito_id': deposito_destino_id,
                'tipo_movimento': 'TRANSFERENCIA_ENTRADA',
                'quantidade': abs(quantidade),
                'saldo_anterior': saldo_anterior_destino,
                'saldo_posterior': saldo_posterior_destino,
                'data_hora': datetime.utcnow(),
                'observacao': f'{observacao} - Transferência do depósito {deposito_origem_id}',
                'usuario_id': usuario_id,
                'transferencia_id': transferencia_id
            }
            transaction_ref.set(lancamento_entrada_ref, lancamento_entrada_data)
            
            return lancamento_saida_ref.id, lancamento_entrada_ref.id

        try:
            lanc_saida_id, lanc_entrada_id = transfer_in_transaction(transaction)
            return lanc_saida_id, lanc_entrada_id
        except Exception as e:
            print(f"Erro registrando transferência atômica: {str(e)}")
            raise

    def _update_saldo_in_transaction(self, transaction, produto_id: str, deposito_id: str, quantidade_movimento: float, tipo_movimento: Optional[str] = None) -> Tuple[float, float]:
        """Helper to update current balance within a transaction."""
        doc_key = f"{produto_id}_{deposito_id}"
        saldo_ref = self.saldos_collection.document(doc_key)

        # Read current balance within the transaction
        saldo_doc = saldo_ref.get(transaction=transaction)

        saldo_anterior = 0
        # Initialize reservation fields with default values
        quantidade_reservada = 0
        reservas = []
        versao_atual = 0 # Initialize versao_atual

        if saldo_doc.exists:
            saldo_data = saldo_doc.to_dict()
            saldo_anterior = saldo_data.get('quantidade', 0)
            # Preserve existing reservation fields if they exist
            quantidade_reservada = saldo_data.get('quantidade_reservada', 0)
            reservas = saldo_data.get('reservas', [])
            versao_atual = saldo_data.get('versao', 0) # Get current version, default to 0

        # Validar saldo antes de permitir a saída (não se aplica ao balanço)
        if tipo_movimento != 'BALANCO' and quantidade_movimento < 0 and saldo_anterior < abs(quantidade_movimento):
            raise ValueError(f"Saldo insuficiente para o produto {produto_id} no depósito {deposito_id}. Saldo: {saldo_anterior}, Saída: {abs(quantidade_movimento)}")

        if tipo_movimento == 'BALANCO':
            saldo_posterior = quantidade_movimento
        else:
            saldo_posterior = saldo_anterior + quantidade_movimento

        update_data = {
            'produto_id': produto_id,
            'deposito_id': deposito_id,
            'quantidade': saldo_posterior,  # Estoque físico
            'quantidade_reservada': quantidade_reservada,
            'reservas': reservas,
            'versao': versao_atual + 1, # Increment the version
            'data_ultima_atualizacao': datetime.utcnow()
        }

        transaction.set(saldo_ref, update_data)
        return saldo_anterior, saldo_posterior

    def _reservar_estoque_in_transaction(self, transaction, produto_id: str, deposito_id: str, ordem_id: str, tipo_ordem: str, quantidade: float, usuario_id: Optional[int] = None):
        """Helper que executa a lógica de reserva dentro de uma transação já existente."""
        if quantidade <= 0:
            raise ValueError("A quantidade a ser reservada deve ser positiva.")

        doc_key = f"{produto_id}_{deposito_id}"
        saldo_ref = self.saldos_collection.document(doc_key)
        
        saldo_doc = saldo_ref.get(transaction=transaction)

        saldo_data = {}
        if saldo_doc.exists:
            saldo_data = saldo_doc.to_dict()
        # If the document doesn't exist, we treat it as a zero-balance stock.
        # The logic below will correctly calculate available stock as 0.


        estoque_fisico = saldo_data.get('quantidade', 0)
        estoque_reservado = saldo_data.get('quantidade_reservada', 0)
        reservas_atuais = [{**r} for r in saldo_data.get('reservas', [])]
        versao_atual = saldo_data.get('versao', 0) # Get current version, default to 0

        for r in reservas_atuais:
            if r.get('ordem_id') == ordem_id:
                raise ValueError(f"A ordem {ordem_id} já possui uma reserva para este produto.")

        estoque_disponivel = estoque_fisico - estoque_reservado

        if quantidade > estoque_disponivel:
            raise ValueError(f"Estoque disponível insuficiente para reserva. Disponível: {estoque_disponivel}, Requerido: {quantidade}")

        nova_reserva = {
            'ordem_id': ordem_id,
            'tipo_ordem': tipo_ordem,
            'quantidade_original': quantidade,
            'quantidade_disponivel': quantidade,
            'quantidade_consumida': 0,
            'consumos': [],
            'data_reserva': datetime.utcnow(),
            'usuario_id': usuario_id
        }
        
        reservas_atuais.append(nova_reserva)
        novo_estoque_reservado = estoque_reservado + quantidade

        update_data = {
            'quantidade_reservada': novo_estoque_reservado,
            'reservas': reservas_atuais,
            'versao': versao_atual + 1,
            'data_ultima_atualizacao': datetime.utcnow()
        }

        transaction.set(saldo_ref, update_data, merge=True)
        return True

    def reservar_estoque(self, produto_id: str, deposito_id: str, ordem_id: str, tipo_ordem: str, quantidade: float, usuario_id: Optional[int] = None):
        """
        Reserva uma quantidade de um produto para uma ordem específica. Cria sua própria transação.
        """
        transaction = firestore_client.db.transaction()
        
        @firestore.transactional
        def _run_in_tx(tx):
            return self._reservar_estoque_in_transaction(
                transaction=tx,
                produto_id=produto_id,
                deposito_id=deposito_id,
                ordem_id=ordem_id,
                tipo_ordem=tipo_ordem,
                quantidade=quantidade,
                usuario_id=usuario_id
            )
        
        try:
            return _run_in_tx(transaction)
        except Exception as e:
            print(f"Erro ao reservar estoque: {str(e)}")
            raise

    def _liberar_reserva_in_transaction(self, transaction, produto_id: str, deposito_id: str, ordem_id: str, liberar_parcial: bool = False, quantidade_a_liberar: Optional[float] = None):
        """
        Helper que libera uma reserva de estoque dentro de uma transação.
        Por padrão, libera a reserva inteira.
        Se liberar_parcial=True e quantidade_a_liberar for fornecida, libera apenas essa quantidade.
        """
        doc_key = f"{produto_id}_{deposito_id}"
        saldo_ref = self.saldos_collection.document(doc_key)

        saldo_doc = saldo_ref.get(transaction=transaction)

        if not saldo_doc.exists:
            print(f"INFO: Documento de saldo para o produto {produto_id} no depósito {deposito_id} não existe. Nenhuma reserva para liberar.")
            return False

        saldo_data = saldo_doc.to_dict()
        
        estoque_reservado_total = saldo_data.get('quantidade_reservada', 0)
        reservas_atuais = saldo_data.get('reservas', [])
        versao_atual = saldo_data.get('versao', 0) # Get current version, default to 0

        reserva_idx, reserva_para_liberar = next(((i, r) for i, r in enumerate(reservas_atuais) if r.get('ordem_id') == ordem_id), (None, None))
        
        if not reserva_para_liberar:
            print(f"INFO: Documento de saldo para o produto {produto_id} no depósito {deposito_id} não existe. Nenhuma reserva para liberar.")
            return False

        quantidade_disponivel_na_reserva = reserva_para_liberar.get('quantidade_disponivel', 0)
        
        if liberar_parcial:
            if quantidade_a_liberar is None or quantidade_a_liberar <= 0:
                raise ValueError("Para liberação parcial, a quantidade a liberar deve ser um número positivo.")
            if quantidade_a_liberar > quantidade_disponivel_na_reserva:
                raise ValueError(f"Tentativa de liberar {quantidade_a_liberar} excede a quantidade disponível de {quantidade_disponivel_na_reserva}.")
            
            quantidade_liberada = quantidade_a_liberar
            reserva_para_liberar['quantidade_disponivel'] -= quantidade_liberada
            reservas_atuais[reserva_idx] = reserva_para_liberar
            
        else: # Liberação total do saldo da reserva
            quantidade_liberada = quantidade_disponivel_na_reserva
            # Remove a reserva da lista
            reservas_atuais.pop(reserva_idx)

        novo_estoque_reservado_total = estoque_reservado_total - quantidade_liberada
        if novo_estoque_reservado_total < 0:
            novo_estoque_reservado_total = 0

        update_data = {
            'quantidade_reservada': novo_estoque_reservado_total,
            'reservas': reservas_atuais,
            'versao': versao_atual + 1,
            'data_ultima_atualizacao': datetime.utcnow()
        }

        transaction.set(saldo_ref, update_data, merge=True)
        return True


    def liberar_reserva(self, produto_id: str, deposito_id: str, ordem_id: str):
        """
        Libera (cancela) uma reserva de estoque para uma ordem. Cria sua própria transação.
        """
        transaction = firestore_client.db.transaction()

        @firestore.transactional
        def _run_in_tx(tx):
            return self._liberar_reserva_in_transaction(
                transaction=tx,
                produto_id=produto_id,
                deposito_id=deposito_id,
                ordem_id=ordem_id
            )

        try:
            return _run_in_tx(transaction)
        except Exception as e:
            print(f"Erro ao liberar reserva: {str(e)}")
            raise

    def _consumir_reserva_in_transaction(self, transaction, produto_id: str, deposito_id: str, ordem_id: str, quantidade_a_consumir: float, entrega_id: Optional[str] = None, observacao: str = "", usuario_id: Optional[int] = None):
        """Helper que consome total ou parcialmente uma reserva dentro de uma transação."""
        doc_key = f"{produto_id}_{deposito_id}"
        saldo_ref = self.saldos_collection.document(doc_key)
        saldo_doc = saldo_ref.get(transaction=transaction)

        if not saldo_doc.exists:
            raise ValueError(f"Documento de saldo para {produto_id} em {deposito_id} não existe.")

        saldo_data = saldo_doc.to_dict()
        estoque_fisico_anterior = saldo_data.get('quantidade', 0)
        estoque_reservado_anterior = saldo_data.get('quantidade_reservada', 0)
        reservas_atuais = [{**r} for r in saldo_data.get('reservas', [])]
        versao_atual = saldo_data.get('versao', 0) # Get current version, default to 0

        reserva_idx, reserva_para_consumir = next(((i, r) for i, r in enumerate(reservas_atuais) if r.get('ordem_id') == ordem_id), (None, None))

        if not reserva_para_consumir:
            raise ValueError(f"Nenhuma reserva encontrada para a ordem {ordem_id} no produto {produto_id}.")

        quantidade_disponivel_reserva = reserva_para_consumir.get('quantidade_disponivel', 0)

        if quantidade_a_consumir > quantidade_disponivel_reserva:
            raise ValueError(f"Tentativa de consumir {quantidade_a_consumir} excede a quantidade disponível na reserva de {quantidade_disponivel_na_reserva}.")

        if estoque_fisico_anterior < quantidade_a_consumir:
            raise ValueError(f"Inconsistência: Estoque físico ({estoque_fisico_anterior}) é menor que a quantidade a consumir ({quantidade_a_consumir}).")

        # Atualiza a reserva
        reserva_para_consumir['quantidade_disponivel'] -= quantidade_a_consumir
        reserva_para_consumir['quantidade_consumida'] += quantidade_a_consumir
        
        novo_consumo = {
            'data': datetime.utcnow(),
            'quantidade': quantidade_a_consumir,
            'entrega_id': entrega_id,
            'usuario_id': usuario_id
        }
        reserva_para_consumir.setdefault('consumos', []).append(novo_consumo)

        # Se a reserva foi totalmente consumida, remove da lista
        if reserva_para_consumir['quantidade_disponivel'] <= 0:
            reservas_atuais.pop(reserva_idx)
        else:
            reservas_atuais[reserva_idx] = reserva_para_consumir

        # Atualiza saldos globais
        novo_estoque_reservado = estoque_reservado_anterior - quantidade_a_consumir
        novo_estoque_fisico = estoque_fisico_anterior - quantidade_a_consumir

        update_data = {
            'quantidade': novo_estoque_fisico,
            'quantidade_reservada': novo_estoque_reservado,
            'reservas': reservas_atuais,
            'versao': versao_atual + 1,
            'data_ultima_atualizacao': datetime.utcnow()
        }
        transaction.set(saldo_ref, update_data, merge=True)

        # Cria o lançamento de estoque para a saída
        lancamento_ref = self.lancamentos_collection.document()
        lancamento_data = {
            'produto_id': produto_id,
            'deposito_id': deposito_id,
            'tipo_movimento': 'SAIDA_RESERVA',
            'quantidade': quantidade_a_consumir,
            'saldo_anterior': estoque_fisico_anterior,
            'saldo_posterior': novo_estoque_fisico,
            'data_hora': datetime.utcnow(),
            'observacao': f"Consumo de reserva para a ordem {ordem_id}. {observacao}",
            'usuario_id': usuario_id,
            'ordem_id': ordem_id,
            'entrega_id': entrega_id
        }
        transaction.set(lancamento_ref, lancamento_data)
        return lancamento_ref.id

    def consumir_reserva(self, produto_id: str, deposito_id: str, ordem_id: str, quantidade: Optional[float] = None, entrega_id: Optional[str] = None, observacao: str = "", usuario_id: Optional[int] = None):
        """
        Consome uma reserva de estoque. Se a quantidade não for especificada, consome a reserva inteira.
        """
        transaction = firestore_client.db.transaction()

        @firestore.transactional
        def _run_in_tx(tx):
            # Se a quantidade não for fornecida, busca a quantidade total da reserva
            quantidade_a_consumir = quantidade
            if quantidade_a_consumir is None:
                doc_key = f"{produto_id}_{deposito_id}"
                saldo_doc = self.saldos_collection.document(doc_key).get(transaction=tx)
                if not saldo_doc.exists:
                    raise ValueError("Documento de saldo não encontrado para determinar a quantidade total da reserva.")
                
                reservas_atuais = saldo_doc.to_dict().get('reservas', [])
                reserva = next((r for r in reservas_atuais if r.get('ordem_id') == ordem_id), None)
                if not reserva:
                    raise ValueError(f"Reserva para a ordem {ordem_id} não encontrada.")
                quantidade_a_consumir = reserva['quantidade_disponivel']

            return self._consumir_reserva_in_transaction(
                transaction=tx,
                produto_id=produto_id,
                deposito_id=deposito_id,
                ordem_id=ordem_id,
                quantidade_a_consumir=quantidade_a_consumir,
                entrega_id=entrega_id,
                observacao=observacao,
                usuario_id=usuario_id
            )
        
        try:
            return _run_in_tx(transaction)
        except Exception as e:
            print(f"Erro ao consumir reserva: {str(e)}")
            raise

    def reverter_movimentacao(self, lancamento_id: str, usuario_id: Optional[int] = None):
        """
        Reverte uma movimentação de estoque criando uma transação oposta.
        Marca a movimentação original como cancelada.
        A operação é transacional.
        """
        
        @firestore.transactional
        def _reverter_in_transaction(transaction):
            lancamento_ref = self.lancamentos_collection.document(lancamento_id)
            lancamento_doc = lancamento_ref.get(transaction=transaction)

            if not lancamento_doc.exists:
                raise ValueError("Lançamento não encontrado.")

            lancamento_data = lancamento_doc.to_dict()

            if lancamento_data.get('cancelado'):
                raise ValueError("Este lançamento já foi cancelado.")
    
            if lancamento_data['tipo_movimento'].startswith('REVERSAO_'):
                raise ValueError("Não é possível reverter uma movimentação que já é uma reversão.")
            
            tipo_original = lancamento_data['tipo_movimento']
            produto_id = lancamento_data['produto_id']
            deposito_id = lancamento_data['deposito_id']

            movimento_original = lancamento_data['saldo_posterior'] - lancamento_data['saldo_anterior']
            quantidade_reversao = -movimento_original

            if tipo_original in ['ENTRADA', 'SAIDA', 'SAIDA_RESERVA', 'BALANCO']:
                tipo_reversao = f"REVERSAO_{tipo_original}"
            elif tipo_original in ['TRANSFERENCIA_SAIDA', 'TRANSFERENCIA_ENTRADA']:
                raise ValueError("Transferências devem ser revertidas pela operação completa, não por partes.")
            else:
                raise ValueError(f"Tipo de movimento '{tipo_original}' não pode ser revertido.")

            # 1. Registrar o movimento de reversão (que atualiza o saldo)
            saldo_anterior_rev, saldo_posterior_rev = self._update_saldo_in_transaction(
                transaction, produto_id, deposito_id, quantidade_reversao
            )

            # 2. Criar o lançamento para a reversão
            reversao_ref = self.lancamentos_collection.document()
            reversao_data = {
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'tipo_movimento': tipo_reversao,
                'quantidade': abs(quantidade_reversao),
                'saldo_anterior': saldo_anterior_rev,
                'saldo_posterior': saldo_posterior_rev,
                'data_hora': datetime.utcnow(),
                'observacao': f"Reversão do lançamento {lancamento_id}",
                'usuario_id': usuario_id,
                'reverte_lancamento_id': lancamento_id
            }
            transaction.set(reversao_ref, reversao_data)

            # 3. Marcar o lançamento original como cancelado
            update_original = {
                'cancelado': True,
                'revertido_em': datetime.utcnow(),
                'revertido_pelo_lancamento_id': reversao_ref.id
            }
            transaction.set(lancamento_ref, update_original, merge=True)

            return reversao_ref.id

        return _reverter_in_transaction(firestore_client.db.transaction())

    def _registrar_movimento(self, produto_id: str, deposito_id: str, tipo_movimento: str,
                           quantidade: float, observacao: str = "",
                           ordem_compra_id: Optional[str] = None,
                           usuario_id: Optional[int] = None) -> str:
        """Registra movimento de estoque e atualiza saldo de forma transacional."""
        try:
            transaction = firestore_client.db.transaction()
            
            @firestore.transactional
            def update_in_transaction(transaction_ref):
                saldo_anterior, saldo_posterior = self._update_saldo_in_transaction(
                    transaction_ref, produto_id, deposito_id, quantidade, tipo_movimento=tipo_movimento
                )

                # Cria lançamento dentro da transação
                lancamento_data = {
                    'produto_id': produto_id,
                    'deposito_id': deposito_id,
                    'tipo_movimento': tipo_movimento,
                    'quantidade': abs(saldo_posterior - saldo_anterior),  # Sempre positivo no registro
                    'saldo_anterior': saldo_anterior,
                    'saldo_posterior': saldo_posterior,
                    'data_hora': datetime.utcnow(),
                    'observacao': observacao,
                    'ordem_compra_id': ordem_compra_id,
                    'usuario_id': usuario_id
                }
                
                # Adiciona o lançamento à coleção de lançamentos dentro da transação
                # Firestore transactions do not support .add(), so we generate an ID and use .set()
                new_lancamento_ref = self.lancamentos_collection.document()
                transaction_ref.set(new_lancamento_ref, lancamento_data)
                return new_lancamento_ref.id

            lancamento_id = update_in_transaction(transaction)
            return lancamento_id
        except Exception as e:
            print(f"Erro registrando movimento transacional: {str(e)}")
            raise

    def get_saldo_atual(self, produto_id: str, deposito_id: str) -> Dict[str, Any]:
        """Busca saldo atual de produto em depósito específico, incluindo detalhes de reserva."""
        try:
            doc_key = f"{produto_id}_{deposito_id}"
            doc = self.saldos_collection.document(doc_key).get()

            if doc.exists:
                saldo = doc.to_dict()
                
                # Garantir que os campos de reserva existam e calcular o disponível
                saldo['quantidade'] = saldo.get('quantidade', 0)  # Estoque Físico
                saldo['quantidade_reservada'] = saldo.get('quantidade_reservada', 0)
                saldo['quantidade_disponivel'] = saldo['quantidade'] - saldo['quantidade_reservada']
                
                # Adicionar IDs para consistência
                saldo['produto_id'] = produto_id
                saldo['deposito_id'] = deposito_id
                return saldo
            else:
                # Retorna saldo zero se não existe
                return {
                    'produto_id': produto_id,
                    'deposito_id': deposito_id,
                    'quantidade': 0,
                    'quantidade_reservada': 0,
                    'quantidade_disponivel': 0,
                    'data_ultima_atualizacao': datetime.utcnow()
                }
        except Exception as e:
            print(f"Erro buscando saldo atual: {str(e)}")
            return {
                'produto_id': produto_id,
                'deposito_id': deposito_id,
                'quantidade': 0,
                'quantidade_reservada': 0,
                'quantidade_disponivel': 0,
                'data_ultima_atualizacao': None
            }

    def get_saldos_produto(self, produto_id: str) -> List[Dict[str, Any]]:
        """Busca saldos do produto em todos os depósitos, incluindo detalhes de reserva."""
        try:
            query = self.saldos_collection.where('produto_id', '==', produto_id)
            docs = query.stream()
            saldos = []
            for doc in docs:
                saldo = doc.to_dict()
                saldo['quantidade'] = saldo.get('quantidade', 0)
                saldo['quantidade_reservada'] = saldo.get('quantidade_reservada', 0)
                saldo['quantidade_disponivel'] = saldo['quantidade'] - saldo['quantidade_reservada']
                saldos.append(saldo)
            return saldos
        except Exception as e:
            print(f"Erro buscando saldos produto: {str(e)}")
            return []

    def get_posicao_estoque(self, filtro_produtos: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Busca posição atual de estoque para produtos, incluindo detalhes de reserva."""
        try:
            if filtro_produtos:
                # Busca saldos específicos. Esta parte agora retorna os dados completos
                # pois get_saldos_produto foi atualizada.
                posicao = []
                for produto_id in filtro_produtos:
                    saldos_produto = self.get_saldos_produto(produto_id)
                    posicao.extend(saldos_produto)
                return posicao
            else:
                # Busca todos os saldos e calcula o disponível
                docs = self.saldos_collection.stream()
                posicao = []
                for doc in docs:
                    saldo = doc.to_dict()
                    saldo['quantidade'] = saldo.get('quantidade', 0)
                    saldo['quantidade_reservada'] = saldo.get('quantidade_reservada', 0)
                    saldo['quantidade_disponivel'] = saldo['quantidade'] - saldo['quantidade_reservada']
                    posicao.append(saldo)
                return posicao
        except Exception as e:
            print(f"Erro buscando posição estoque: {str(e)}")
            return []

    def get_all_with_reservations(self) -> List[Dict[str, Any]]:
        """Busca todos os saldos que possuem itens reservados."""
        try:
            query = self.saldos_collection.where('quantidade_reservada', '>', 0)
            docs = query.stream()
            
            reservas_list = []
            for doc in docs:
                saldo = doc.to_dict()
                # It's useful to have the calculated available amount here too
                saldo['quantidade'] = saldo.get('quantidade', 0)
                saldo['quantidade_reservada'] = saldo.get('quantidade_reservada', 0)
                saldo['quantidade_disponivel'] = saldo['quantidade'] - saldo['quantidade_reservada']
                reservas_list.append(saldo)
                
            return reservas_list
        except Exception as e:
            print(f"Erro buscando saldos com reservas: {str(e)}")
            return []

    def get_saldos_for_products_in_deposit(self, produto_ids: List[str], deposito_id: str) -> Dict[str, Dict[str, Any]]:
        """Busca saldos para uma lista de produtos em um depósito específico.
        Retorna um dicionário {produto_id: saldo_completo}.
        """
        saldos_map = {pid: {
            'produto_id': pid,
            'deposito_id': deposito_id,
            'quantidade': 0,
            'quantidade_reservada': 0,
            'quantidade_disponivel': 0,
            'reservas': []
        } for pid in produto_ids}
        if not produto_ids:
            return saldos_map

        # Firestore allows 'in' queries for up to 10 values
        # For more than 10, multiple queries or a different approach would be needed
        # Assuming produto_ids won't exceed this limit for a single API call
        
        # Construct document keys for direct lookup
        doc_keys = [f"{pid}_{deposito_id}" for pid in produto_ids]
        
        # Fetch documents by their IDs
        docs = firestore_client.db.get_all([self.saldos_collection.document(key) for key in doc_keys])

        for doc in docs:
            if doc.exists:
                saldo_data = doc.to_dict()
                produto_id = saldo_data.get('produto_id')
                if produto_id in produto_ids:
                    saldo_data['quantidade'] = saldo_data.get('quantidade', 0)
                    saldo_data['quantidade_reservada'] = saldo_data.get('quantidade_reservada', 0)
                    saldo_data['quantidade_disponivel'] = saldo_data['quantidade'] - saldo_data['quantidade_reservada']
                    saldos_map[produto_id] = saldo_data
        
        return saldos_map

    def get_saldos_for_products_all_deposits(self, produto_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Busca saldos para uma lista de produtos em todos os depósitos, somando as quantidades.
        Retorna um dicionário {produto_id: {'quantidade': total_fisico, 'quantidade_reservada': total_reservado}}.
        """
        aggregated_saldos = {pid: {'quantidade': 0, 'quantidade_reservada': 0, 'quantidade_disponivel': 0} for pid in produto_ids}
        if not produto_ids:
            return aggregated_saldos

        # Firestore 'in' query for produto_id
        # Max 10 product_ids per query
        for i in range(0, len(produto_ids), 10):
            batch_ids = produto_ids[i:i+10]
            query = self.saldos_collection.where('produto_id', 'in', batch_ids)
            docs = query.stream()

            for doc in docs:
                saldo_data = doc.to_dict()
                produto_id = saldo_data.get('produto_id')
                if produto_id in aggregated_saldos:
                    aggregated_saldos[produto_id]['quantidade'] += saldo_data.get('quantidade', 0)
                    aggregated_saldos[produto_id]['quantidade_reservada'] += saldo_data.get('quantidade_reservada', 0)
        
        for pid in aggregated_saldos:
            aggregated_saldos[pid]['quantidade_disponivel'] = aggregated_saldos[pid]['quantidade'] - aggregated_saldos[pid]['quantidade_reservada']

        return aggregated_saldos

    def get_movimentacoes_produto(self, produto_id: str, deposito_id: Optional[str] = None,
                                tipo_movimento: Optional[str] = None,
                                data_inicio: Optional[datetime] = None,
                                data_fim: Optional[datetime] = None,
                                limit: int = 100) -> List[Dict[str, Any]]:
        """Busca histórico de movimentações de um produto"""
        try:
            query = self.lancamentos_collection.where('produto_id', '==', produto_id)

            if deposito_id:
                query = query.where('deposito_id', '==', deposito_id)
            if tipo_movimento:
                query = query.where('tipo_movimento', '==', tipo_movimento)

            query = query.order_by('data_hora', direction='DESCENDING').limit(limit)

            docs = query.stream()
            movimentacoes = []
            for doc in docs:
                mov_data = {**doc.to_dict(), 'id': doc.id}
                # Ensure data_hora is a standard datetime object
                if 'data_hora' in mov_data and hasattr(mov_data['data_hora'], 'astimezone'):
                    mov_data['data_hora'] = mov_data['data_hora'].astimezone(datetime.utcnow().tzinfo)
                elif 'data_hora' in mov_data and isinstance(mov_data['data_hora'], firestore.SERVER_TIMESTAMP):
                    # Handle SERVER_TIMESTAMP if it's not automatically converted
                    mov_data['data_hora'] = datetime.utcnow() # Placeholder or more sophisticated handling
                movimentacoes.append(mov_data)

            # Filtra por data se especificado
            if data_inicio or data_fim:
                filtradas = []
                for mov in movimentacoes:
                    data_mov = mov.get('data_hora')
                    if data_inicio and data_mov < data_inicio:
                        continue
                    if data_fim and data_mov > data_fim:
                        continue
                    filtradas.append(mov)
                movimentacoes = filtradas

            return movimentacoes
        except Exception as e:
            print(f"Erro buscando movimentações: {str(e)}")
            return []

    def get_recent_movimentacoes(self, limit: int = 20, tipo_movimento: Optional[str] = None) -> List[Dict[str, Any]]:
        """Busca as últimas movimentações de estoque, independente do produto."""
        try:
            query = self.lancamentos_collection
            if tipo_movimento:
                query = query.where('tipo_movimento', '==', tipo_movimento)
            query = query.order_by('data_hora', direction='DESCENDING').limit(limit)
            
            docs = query.stream()
            movimentacoes = []
            for doc in docs:
                mov_data = {**doc.to_dict(), 'id': doc.id}
                # Ensure data_hora is a standard datetime object
                if 'data_hora' in mov_data and hasattr(mov_data['data_hora'], 'astimezone'):
                    mov_data['data_hora'] = mov_data['data_hora'].astimezone(datetime.utcnow().tzinfo)
                elif 'data_hora' in mov_data and isinstance(mov_data['data_hora'], firestore.SERVER_TIMESTAMP):
                    # Handle SERVER_TIMESTAMP if it's not automatically converted
                    mov_data['data_hora'] = datetime.utcnow() # Placeholder or more sophisticated handling
                movimentacoes.append(mov_data)
            
            return movimentacoes
        except Exception as e:
            print(f"DEBUG: Erro buscando movimentações recentes: {str(e)}")
            return []

    def get_alertas_estoque(self) -> List[Dict[str, Any]]:
        """Busca produtos com estoque baixo (menor que mínimo)"""
        from services.product_service import product_service

        try:
            produtos = product_service.get_all(per_page=9999)
            alertas = []

            for produto in produtos:
                if not produto.get('ativo', True):
                    continue

                estoque_minimo = produto.get('estoque_minimo', 0)
                if estoque_minimo <= 0:
                    continue

                # Soma saldos em todos os depósitos
                saldos = self.get_saldos_produto(produto['id'])
                quantidade_total = sum(saldo.get('quantidade', 0) for saldo in saldos)

                if quantidade_total < estoque_minimo:
                    alertas.append({
                        'produto_id': produto['id'],
                        'produto_nome': produto.get('nome', ''),
                        'estoque_atual': quantidade_total,
                        'estoque_minimo': estoque_minimo,
                        'diferenca': estoque_minimo - quantidade_total
                    })

            return sorted(alertas, key=lambda x: x['diferenca'], reverse=True)
        except Exception as e:
            print(f"Erro buscando alertas: {str(e)}")
            return []



estoque_service = EstoqueService()
