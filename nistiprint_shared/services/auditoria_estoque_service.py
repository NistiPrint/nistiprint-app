from datetime import datetime
from typing import List, Optional, Dict, Any
from nistiprint_shared.database.database import db
from nistiprint_shared.models.contagem_auditoria import ContagemAuditoria
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.deposito_service import deposito_service

class AuditoriaEstoqueService:
    def registrar_contagem(self, produto_id: int, deposito_id: int, quantidade_contada: float, 
                          usuario_id: int, observacao: str = None, sessao_id: str = None) -> Dict[str, Any]:
        """
        Registra uma nova contagem física para auditoria (registro paralelo).
        Captura o saldo do sistema no momento exato (snapshot).
        """
        # 1. Capturar Snapshot do Sistema
        # get_saldo_atual retorna dict: {'quantidade': 10.0, ...}
        saldo_atual_info = estoque_service.get_saldo_atual(produto_id, deposito_id)
        saldo_sistema_snapshot = float(saldo_atual_info.get('quantidade', 0))
        
        # 2. Calcular Diferença
        diferenca = quantidade_contada - saldo_sistema_snapshot
        
        # 3. Criar Registro
        nova_contagem = ContagemAuditoria(
            produto_id=produto_id,
            deposito_id=deposito_id,
            usuario_id=usuario_id,
            quantidade_contada=quantidade_contada,
            saldo_sistema_snapshot=saldo_sistema_snapshot,
            diferenca=diferenca,
            data_contagem=datetime.utcnow(),
            status='PENDENTE',
            observacao=observacao,
            sessao_inventario_id=sessao_id
        )
        
        db.session.add(nova_contagem)
        db.session.commit()
        
        return nova_contagem.to_dict()

    def listar_contagens(self, status: str = None, deposito_id: int = None, 
                         produto_id: int = None, start_date: datetime = None, end_date: datetime = None) -> List[Dict[str, Any]]:
        """Lista contagens com filtros."""
        query = ContagemAuditoria.query
        
        if status:
            query = query.filter_by(status=status)
        if deposito_id:
            query = query.filter_by(deposito_id=deposito_id)
        if produto_id:
            query = query.filter_by(produto_id=produto_id)
        if start_date:
            query = query.filter(ContagemAuditoria.data_contagem >= start_date)
        if end_date:
            query = query.filter(ContagemAuditoria.data_contagem <= end_date)
            
        contagens = query.order_by(ContagemAuditoria.data_contagem.desc()).all()
        return [c.to_dict() for c in contagens]

    def obter_contagem(self, contagem_id: int) -> Optional[ContagemAuditoria]:
        return ContagemAuditoria.query.get(contagem_id)

    def aprovar_contagem(self, contagem_id: int, usuario_aprovador_id: int) -> Dict[str, Any]:
        """
        Aprova a contagem e efetiva o ajuste de estoque.
        ATENÇÃO: O ajuste é feito para igualar o estoque à 'quantidade_contada'.
        """
        contagem = self.obter_contagem(contagem_id)
        if not contagem:
            raise ValueError(f"Contagem {contagem_id} não encontrada.")
        
        if contagem.status != 'PENDENTE':
            raise ValueError(f"Contagem {contagem_id} já foi processada (Status: {contagem.status}).")

        # 1. Efetivar Ajuste no Estoque
        try:
            # Aqui assumimos que a aprovação significa "O valor contado é o correto".
            # Nota: Se o estoque mudou desde a contagem (vendas, entradas), sobrescrever com quantidade_contada
            # pode ser perigoso se não for o desejado. 
            # Opção A (Atual): Ajustar para o valor contado (Balanço).
            # Opção B (Delta): Ajustar a diferença (Entrada/Saída).
            # O método registrar_balanco faz o saldo ficar igual ao valor passado.
            
            # Se quisermos considerar movimentações no intervalo, teríamos que recalcular.
            # Por simplicidade e definição de "Balanço", ajustamos para o valor contado.
            
            estoque_service.registrar_balanco(
                produto_id=contagem.produto_id,
                deposito_id=contagem.deposito_id,
                quantidade_ajuste=contagem.quantidade_contada,
                motivo=f"Auditoria Aprovada (ID: {contagem.id}). Obs: {contagem.observacao or ''}",
                usuario_id=usuario_aprovador_id,
                user_context=None # Poderíamos passar contexto se disponível
            )
            
            # 2. Atualizar Registro de Auditoria
            contagem.status = 'APROVADO'
            contagem.usuario_aprovador_id = usuario_aprovador_id
            contagem.data_processamento = datetime.utcnow()
            
            db.session.commit()
            return contagem.to_dict()
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Erro ao aprovar contagem: {str(e)}")

    def rejeitar_contagem(self, contagem_id: int, usuario_aprovador_id: int) -> Dict[str, Any]:
        """Rejeita a contagem (não altera estoque)."""
        contagem = self.obter_contagem(contagem_id)
        if not contagem:
            raise ValueError(f"Contagem {contagem_id} não encontrada.")
            
        if contagem.status != 'PENDENTE':
            raise ValueError(f"Contagem {contagem_id} já foi processada (Status: {contagem.status}).")
            
        contagem.status = 'REJEITADO'
        contagem.usuario_aprovador_id = usuario_aprovador_id
        contagem.data_processamento = datetime.utcnow()
        
        db.session.commit()
        return contagem.to_dict()

auditoria_estoque_service = AuditoriaEstoqueService()

