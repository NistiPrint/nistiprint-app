"""
Centralizador de inicialização do nistiprint-shared.
Resolve dependências circulares garantindo que modelos sejam importados apenas quando necessário.
"""
import logging
from nistiprint_shared.database.supabase_db_service import SupabaseQueryInterface

def setup_mock_query_interface():
    """
    Configura a interface de query para os modelos quando em modo Supabase.
    Deve ser chamada explicitamente pelo main.py da API ou Worker após o carregamento do app.
    """
    logging.info("Inicializando Interface de Query Legada (Supabase Mock)...")
    
    try:
        # Imports tardios (dentro da função) para evitar loops de importação
        from nistiprint_shared.models.usuario import Usuario
        from nistiprint_shared.models.setor import Setor
        from nistiprint_shared.models.permissao import Recurso, PermissaoSetor
        from nistiprint_shared.models.ai_execution_log import AiExecutionLog
        from nistiprint_shared.models.pedido import Pedido, ItemPedido
        
        # Mapeamento dinâmico de modelos (registre novos modelos aqui)
        models_to_init = {
            'Usuario': Usuario,
            'Setor': Setor,
            'Recurso': Recurso,
            'PermissaoSetor': PermissaoSetor,
            'AiExecutionLog': AiExecutionLog,
            'Pedido': Pedido,
            'ItemPedido': ItemPedido
        }

        # Modelos opcionais/novos que podem não existir ou falhar no import
        optional_models = [
            ('nistiprint_shared.models.product', 'Product'),
            ('nistiprint_shared.models.venda', 'Venda'),
            ('nistiprint_shared.models.ordem_producao', 'OrdemProducao'),
            ('nistiprint_shared.models.ordem_compra', 'OrdemCompra'),
            ('nistiprint_shared.models.tag', 'Tag'),
            ('nistiprint_shared.models.unidade_medida', 'UnidadeMedida'),
            ('nistiprint_shared.models.plataforma', 'Plataforma'),
            ('nistiprint_shared.models.canal_venda', 'CanalVenda'),
            ('nistiprint_shared.models.categoria', 'Categoria'),
            ('nistiprint_shared.models.daily_production_log', 'DailyProductionLog'),
            ('nistiprint_shared.models.demanda_producao', 'DemandaProducao'),
            ('nistiprint_shared.models.deposito', 'Deposito'),
            ('nistiprint_shared.models.estoque_atual', 'EstoqueAtual'),
            ('nistiprint_shared.models.recurso_produtivo', 'RecursoProdutivo'),
            ('nistiprint_shared.models.notificacao', 'Notificacao'),
            ('nistiprint_shared.models.configuracao_aplicacao', 'ConfiguracaoAplicacao'),
            ('nistiprint_shared.models.fornecedor', 'Fornecedor'),
            ('nistiprint_shared.models.product_artwork', 'ProductArtwork'),
            ('nistiprint_shared.models.bling_pedidos', 'BlingPedidos'),
            ('nistiprint_shared.models.bling_pedido_itens', 'BlingPedidoItens'),
            ('nistiprint_shared.models.shopee_orders', 'ShopeeOrders'),
            ('nistiprint_shared.models.produto_externo', 'ProdutoExterno'),
            ('nistiprint_shared.models.demanda_item_origem', 'DemandaItemOrigem'),
            ('nistiprint_shared.models.system_events_log', 'SystemEventsLog'),
            ('nistiprint_shared.models.supabase_chat', 'MensagemChatShopee'),
            ('nistiprint_shared.models.supabase_ai_log', 'LogsExecucaoIA'),
            ('nistiprint_shared.models.supabase_personalizacao', 'PersonalizacaoPedido')
        ]

        import importlib
        for module_path, class_name in optional_models:
            try:
                module = importlib.import_module(module_path)
                model_class = getattr(module, class_name)
                models_to_init[class_name] = model_class
            except (ImportError, AttributeError):
                continue

        # Aplica a interface de query a todos os modelos localizados
        for name, model_cls in models_to_init.items():
            if model_cls:
                model_cls.query = SupabaseQueryInterface(model_cls)
                
        logging.info(f"✓ {len(models_to_init)} modelos inicializados com sucesso.")
        return True
        
    except Exception as e:
        logging.error(f"Erro crítico na inicialização da interface de query: {e}")
        return False
