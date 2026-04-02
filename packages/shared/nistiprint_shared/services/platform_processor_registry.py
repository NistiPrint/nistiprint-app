"""
Platform Processor Registry

Registro centralizado de processadores de arquivos por plataforma.
Nova arquitetura (Fase 7 - Refatoração):
- Substitui if/else hardcoded em consolidar.py
- Permite registro dinâmico de novos processadores
- Mantém backward compatibility com processadores existentes

Uso:
    from nistiprint_shared.services.platform_processor_registry import PlatformProcessorRegistry
    
    processor = PlatformProcessorRegistry.get_processor('shopee')
    result = processor(filepath, period_filter, options, bling_client)
"""

from typing import Dict, Callable, Any, Optional
import logging

logger = logging.getLogger("PlatformProcessorRegistry")


class PlatformProcessorRegistry:
    """
    Registro de processadores de arquivos por plataforma.
    
    Padrão de mercado para roteamento de processamento:
    - Chave: platform_slug (ex: 'shopee', 'amazon', 'mercadolivre')
    - Valor: função processadora (ex: process_shopee, process_amazon)
    """
    
    # Registro estático de processadores
    _processors: Dict[str, Callable] = {}
    
    @classmethod
    def initialize_default_processors(cls):
        """Inicializa processadores padrão (lazy loading para evitar circular imports)."""
        if not cls._processors:
            # Importação lazy para evitar circular dependency
            from nistiprint_shared.services.file_processors import (
                process_mercadolivre,
                process_shopee,
                process_amazon,
                process_shein
            )
            
            cls._processors = {
                'mercadolivre': process_mercadolivre,
                'shopee': process_shopee,
                'amazon': process_amazon,
                'shein': process_shein,
                # Adicionar novos processadores aqui:
                # 'tiktokshop': process_tiktok,
                # 'lojaintegrada': process_lojaintegrada,
            }
            
            logger.info(f"PlatformProcessorRegistry initialized with {len(cls._processors)} processors")
    
    @classmethod
    def get_processor(cls, platform_slug: str) -> Optional[Callable]:
        """
        Obtém processador baseado no slug da plataforma.
        
        Args:
            platform_slug: Slug da plataforma (ex: 'shopee', 'amazon', 'mercadolivre')
                          Pode conter sufixos como 'shopee_flex', 'shopee_standard'
        
        Returns:
            Função processadora ou None se não encontrado
            
        Raises:
            ValueError: Se nenhum processador for encontrado para a plataforma
        """
        if not cls._processors:
            cls.initialize_default_processors()
        
        # Normalização para backward compatibility
        platform_slug_normalized = platform_slug.lower().strip().replace(' ', '').replace('_', '')
        
        # 1. Busca exata
        if platform_slug_normalized in cls._processors:
            logger.debug(f"Processor found for '{platform_slug}': exact match")
            return cls._processors[platform_slug_normalized]
        
        # 2. Busca parcial (para casos como 'shopee_flex', 'shopee_standard')
        for key, processor in cls._processors.items():
            if key in platform_slug_normalized:
                logger.debug(f"Processor found for '{platform_slug}': partial match with '{key}'")
                return processor
        
        # 3. Busca com fallback para variações comuns
        fallback_map = {
            'mercadolivre': ['ml', 'mercadolivre', 'mercadolivrebr'],
            'shopee': ['shopee', 'shopeebr', 'shopeeflex'],
            'amazon': ['amazon', 'amazonbr', 'amazonmercadolivre'],
            'shein': ['shein', 'sheinbr'],
            'tiktokshop': ['tiktok', 'tiktokshop', 'tiktok_br'],
        }
        
        for processor_key, aliases in fallback_map.items():
            if any(alias in platform_slug_normalized for alias in aliases):
                if processor_key in cls._processors:
                    logger.debug(f"Processor found for '{platform_slug}': fallback match with '{processor_key}'")
                    return cls._processors[processor_key]
        
        # 4. Nenhum processador encontrado
        available_keys = list(cls._processors.keys())
        error_msg = (
            f"Processador não encontrado para plataforma: '{platform_slug}' "
            f"(normalized: '{platform_slug_normalized}'). "
            f"Processadores disponíveis: {available_keys}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    @classmethod
    def register_processor(cls, platform_slug: str, processor: Callable):
        """
        Registra novo processador.
        
        Args:
            platform_slug: Slug da plataforma (ex: 'tiktokshop')
            processor: Função processadora com assinatura:
                       processor(file, period_filter, options=None, bling_client=None)
        
        Exemplo:
            def process_tiktok(file, period_filter, options=None, bling_client=None):
                # Lógica de processamento
                return result
            
            PlatformProcessorRegistry.register_processor('tiktokshop', process_tiktok)
        """
        platform_slug_normalized = platform_slug.lower().strip().replace(' ', '').replace('_', '')
        cls._processors[platform_slug_normalized] = processor
        logger.info(f"Processor registered for '{platform_slug}': {processor.__name__}")
    
    @classmethod
    def unregister_processor(cls, platform_slug: str):
        """Remove processador do registro."""
        platform_slug_normalized = platform_slug.lower().strip().replace(' ', '').replace('_', '')
        if platform_slug_normalized in cls._processors:
            del cls._processors[platform_slug_normalized]
            logger.info(f"Processor unregistered for '{platform_slug}'")
    
    @classmethod
    def list_processors(cls) -> Dict[str, str]:
        """
        Lista todos os processadores registrados.
        
        Returns:
            Dict com platform_slug -> nome da função processadora
        """
        if not cls._processors:
            cls.initialize_default_processors()
        
        return {
            slug: processor.__name__ 
            for slug, processor in cls._processors.items()
        }
    
    @classmethod
    def is_registered(cls, platform_slug: str) -> bool:
        """Verifica se processador está registrado para a plataforma."""
        if not cls._processors:
            cls.initialize_default_processors()
        
        platform_slug_normalized = platform_slug.lower().strip().replace(' ', '').replace('_', '')
        
        # Busca exata
        if platform_slug_normalized in cls._processors:
            return True
        
        # Busca parcial
        for key in cls._processors.keys():
            if key in platform_slug_normalized:
                return True
        
        return False


# Singleton instance para conveniência
registry = PlatformProcessorRegistry()
