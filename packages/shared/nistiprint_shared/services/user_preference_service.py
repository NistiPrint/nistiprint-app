"""
User Preference Service - Serviço para gerenciar preferências de UX por usuário.

Este serviço permite personalizar a experiência do usuário, lembrando configurações,
filtros salvos, atalhos personalizados e outras preferências de interface.

Objetivos:
- Persistir preferências de UX por usuário
- Gerenciar filtros salvos (presets)
- Gerenciar atalhos de teclado personalizados
- Reduzir carga cognitiva ao lembrar configurações frequentes
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
import logging

logger = logging.getLogger("UserPreferenceService")


class UserPreferenceService:
    """Serviço para gerenciamento de preferências de UX por usuário."""

    def __init__(self):
        self.preferencias_table = supabase_db.table('preferencias_ux_usuario')

    # ========================================================================
    # MÉTODOS PÚBLICOS - Preferências Principais
    # ========================================================================

    def get_preferences(self, user_id: str) -> Dict[str, Any]:
        """
        Busca preferências de um usuário.

        Args:
            user_id: ID do usuário

        Returns:
            Dicionário com preferências do usuário
        """
        try:
            response = self.preferencias_table.select("*") \
                .eq('user_id', user_id) \
                .single() \
                .execute()

            if response.data:
                return self._normalize_preferences(response.data)
            
            # Retornar defaults se não existir
            return self._get_default_preferences(user_id)

        except Exception as e:
            logger.error(f"Erro ao buscar preferências: {e}", exc_info=True)
            return self._get_default_preferences(user_id)

    def save_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        """
        Salva preferências de um usuário.

        Args:
            user_id: ID do usuário
            preferences: Dicionário de preferências

        Returns:
            True se salvo, False se erro
        """
        try:
            # Verificar se já existe
            existing = self.preferencias_table.select("id") \
                .eq('user_id', user_id) \
                .execute()

            payload = {
                'user_id': user_id,
                'vista_padrao': preferences.get('vista_padrao', 'KANBAN'),
                'ordenacao_padrao': preferences.get('ordenacao_padrao', 'PRIORIDADE'),
                'agrupamento_padrao': preferences.get('agrupamento_padrao'),
                'filtros_salvos': preferences.get('filtros_salvos', []),
                'atalhos_personalizados': preferences.get('atalhos_personalizados'),
                'auto_fill_enabled': preferences.get('auto_fill_enabled', True),
                'show_suggestions': preferences.get('show_suggestions', True),
                'validate_on_blur': preferences.get('validate_on_blur', True),
                'updated_at': get_now_iso()
            }

            if existing.data:
                # Atualizar
                self.preferencias_table.update(payload) \
                    .eq('user_id', user_id) \
                    .execute()
            else:
                # Criar
                payload['created_at'] = get_now_iso()
                self.preferencias_table.insert(payload).execute()

            return True

        except Exception as e:
            logger.error(f"Erro ao salvar preferências: {e}", exc_info=True)
            return False

    def update_preference(
        self,
        user_id: str,
        key: str,
        value: Any
    ) -> bool:
        """
        Atualiza uma preferência específica.

        Args:
            user_id: ID do usuário
            key: Chave da preferência
            value: Novo valor

        Returns:
            True se atualizado, False se erro
        """
        try:
            # Buscar preferências atuais
            current = self.get_preferences(user_id)
            
            # Atualizar chave específica
            if key in [
                'vista_padrao', 'ordenacao_padrao', 'agrupamento_padrao',
                'auto_fill_enabled', 'show_suggestions', 'validate_on_blur'
            ]:
                current[key] = value
            elif key == 'filtros_salvos':
                current['filtros_salvos'] = value
            elif key == 'atalhos_personalizados':
                current['atalhos_personalizados'] = value

            return self.save_preferences(user_id, current)

        except Exception as e:
            logger.error(f"Erro ao atualizar preferência: {e}", exc_info=True)
            return False

    def reset_preferences(self, user_id: str) -> bool:
        """
        Reseta preferências para valores padrão.

        Args:
            user_id: ID do usuário

        Returns:
            True se resetado, False se erro
        """
        try:
            defaults = self._get_default_preferences(user_id)
            return self.save_preferences(user_id, defaults)

        except Exception as e:
            logger.error(f"Erro ao resetar preferências: {e}", exc_info=True)
            return False

    # ========================================================================
    # MÉTODOS PÚBLICOS - Filtros Salvos
    # ========================================================================

    def get_saved_filters(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Busca filtros salvos de um usuário.

        Args:
            user_id: ID do usuário

        Returns:
            Lista de filtros salvos
        """
        try:
            preferences = self.get_preferences(user_id)
            return preferences.get('filtros_salvos', [])

        except Exception as e:
            logger.error(f"Erro ao buscar filtros salvos: {e}", exc_info=True)
            return []

    def save_filter(self, user_id: str, filter_preset: Dict[str, Any]) -> bool:
        """
        Salva um filtro como preset.

        Args:
            user_id: ID do usuário
            filter_preset: Dicionário do filtro:
                - id: string (gerado se não existir)
                - nome: string
                - filtros: dict
                - is_default: bool

        Returns:
            True se salvo, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            filtros = preferences.get('filtros_salvos', [])

            # Gerar ID se não existir
            if 'id' not in filter_preset:
                import uuid
                filter_preset['id'] = str(uuid.uuid4())

            # Verificar se já existe filtro com mesmo nome
            existing_idx = None
            for i, f in enumerate(filtros):
                if f.get('nome') == filter_preset.get('nome'):
                    existing_idx = i
                    break

            if existing_idx is not None:
                # Atualizar existente
                filtros[existing_idx] = filter_preset
            else:
                # Adicionar novo
                filtros.append(filter_preset)

            preferences['filtros_salvos'] = filtros
            return self.save_preferences(user_id, preferences)

        except Exception as e:
            logger.error(f"Erro ao salvar filtro: {e}", exc_info=True)
            return False

    def delete_filter(self, user_id: str, filter_id: str) -> bool:
        """
        Exclui um filtro salvo.

        Args:
            user_id: ID do usuário
            filter_id: ID do filtro

        Returns:
            True se excluído, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            filtros = preferences.get('filtros_salvos', [])

            # Filtrar para remover o filtro
            filtros = [f for f in filtros if f.get('id') != filter_id]

            preferences['filtros_salvos'] = filtros
            return self.save_preferences(user_id, preferences)

        except Exception as e:
            logger.error(f"Erro ao excluir filtro: {e}", exc_info=True)
            return False

    def get_default_filter(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca filtro padrão do usuário.

        Args:
            user_id: ID do usuário

        Returns:
            Filtro padrão ou None
        """
        try:
            filtros = self.get_saved_filters(user_id)
            for f in filtros:
                if f.get('is_default'):
                    return f
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar filtro padrão: {e}", exc_info=True)
            return None

    def set_default_filter(self, user_id: str, filter_id: str) -> bool:
        """
        Define um filtro como padrão.

        Args:
            user_id: ID do usuário
            filter_id: ID do filtro

        Returns:
            True se definido, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            filtros = preferences.get('filtros_salvos', [])

            # Remover default de todos
            for f in filtros:
                f['is_default'] = False

            # Setar novo default
            for f in filtros:
                if f.get('id') == filter_id:
                    f['is_default'] = True
                    break

            preferences['filtros_salvos'] = filtros
            return self.save_preferences(user_id, preferences)

        except Exception as e:
            logger.error(f"Erro ao definir filtro padrão: {e}", exc_info=True)
            return False

    # ========================================================================
    # MÉTODOS PÚBLICOS - Atalhos de Teclado
    # ========================================================================

    def get_keyboard_shortcuts(self, user_id: str) -> Dict[str, str]:
        """
        Busca atalhos de teclado personalizados.

        Args:
            user_id: ID do usuário

        Returns:
            Dicionário {tecla: ação}
        """
        try:
            preferences = self.get_preferences(user_id)
            return preferences.get('atalhos_personalizados', {})

        except Exception as e:
            logger.error(f"Erro ao buscar atalhos: {e}", exc_info=True)
            return {}

    def save_keyboard_shortcut(
        self,
        user_id: str,
        key: str,
        action: str
    ) -> bool:
        """
        Salva atalho de teclado personalizado.

        Args:
            user_id: ID do usuário
            key: Combinação de teclas (ex: 'Ctrl+S')
            action: Ação associada

        Returns:
            True se salvo, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            atalhos = preferences.get('atalhos_personalizados', {})

            atalhos[key] = action
            preferences['atalhos_personalizados'] = atalhos

            return self.save_preferences(user_id, preferences)

        except Exception as e:
            logger.error(f"Erro ao salvar atalho: {e}", exc_info=True)
            return False

    def delete_keyboard_shortcut(self, user_id: str, key: str) -> bool:
        """
        Exclui atalho de teclado personalizado.

        Args:
            user_id: ID do usuário
            key: Combinação de teclas

        Returns:
            True se excluído, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            atalhos = preferences.get('atalhos_personalizados', {})

            if key in atalhos:
                del atalhos[key]
                preferences['atalhos_personalizados'] = atalhos
                return self.save_preferences(user_id, preferences)

            return True

        except Exception as e:
            logger.error(f"Erro ao excluir atalho: {e}", exc_info=True)
            return False

    def reset_keyboard_shortcuts(self, user_id: str) -> bool:
        """
        Reseta atalhos para padrão do sistema.

        Args:
            user_id: ID do usuário

        Returns:
            True se resetado, False se erro
        """
        try:
            return self.save_keyboard_shortcuts(user_id, {})

        except Exception as e:
            logger.error(f"Erro ao resetar atalhos: {e}", exc_info=True)
            return False

    def save_keyboard_shortcuts(
        self,
        user_id: str,
        shortcuts: Dict[str, str]
    ) -> bool:
        """
        Salva todos os atalhos de teclado.

        Args:
            user_id: ID do usuário
            shortcuts: Dicionário {tecla: ação}

        Returns:
            True se salvo, False se erro
        """
        try:
            preferences = self.get_preferences(user_id)
            preferences['atalhos_personalizados'] = shortcuts
            return self.save_preferences(user_id, preferences)

        except Exception as e:
            logger.error(f"Erro ao salvar atalhos: {e}", exc_info=True)
            return False

    # ========================================================================
    # MÉTODOS PÚBLICOS - Configurações de UX
    # ========================================================================

    def is_auto_fill_enabled(self, user_id: str) -> bool:
        """
        Verifica se autopreenchimento está habilitado.

        Args:
            user_id: ID do usuário

        Returns:
            True se habilitado
        """
        try:
            preferences = self.get_preferences(user_id)
            return preferences.get('auto_fill_enabled', True)

        except:
            return True

    def toggle_auto_fill(self, user_id: str) -> bool:
        """
        Alterna estado do autopreenchimento.

        Args:
            user_id: ID do usuário

        Returns:
            Novo estado
        """
        try:
            current = self.is_auto_fill_enabled(user_id)
            return self.update_preference(user_id, 'auto_fill_enabled', not current)

        except Exception as e:
            logger.error(f"Erro ao alternar autopreenchimento: {e}", exc_info=True)
            return False

    def is_show_suggestions(self, user_id: str) -> bool:
        """
        Verifica se sugestões estão habilitadas.

        Args:
            user_id: ID do usuário

        Returns:
            True se habilitado
        """
        try:
            preferences = self.get_preferences(user_id)
            return preferences.get('show_suggestions', True)

        except:
            return True

    def is_validate_on_blur(self, user_id: str) -> bool:
        """
        Verifica se validação ao perder foco está habilitada.

        Args:
            user_id: ID do usuário

        Returns:
            True se habilitado
        """
        try:
            preferences = self.get_preferences(user_id)
            return preferences.get('validate_on_blur', True)

        except:
            return True

    # ========================================================================
    # MÉTODOS PRIVADOS - Helpers
    # ========================================================================

    def _get_default_preferences(self, user_id: str) -> Dict[str, Any]:
        """Retorna preferências padrão."""
        return {
            'user_id': user_id,
            'vista_padrao': 'KANBAN',
            'ordenacao_padrao': 'PRIORIDADE',
            'agrupamento_padrao': None,
            'filtros_salvos': [],
            'atalhos_personalizados': {},
            'auto_fill_enabled': True,
            'show_suggestions': True,
            'validate_on_blur': True
        }

    def _normalize_preferences(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza preferências do banco."""
        return {
            'user_id': data.get('user_id'),
            'vista_padrao': data.get('vista_padrao', 'KANBAN'),
            'ordenacao_padrao': data.get('ordenacao_padrao', 'PRIORIDADE'),
            'agrupamento_padrao': data.get('agrupamento_padrao'),
            'filtros_salvos': data.get('filtros_salvos', []),
            'atalhos_personalizados': data.get('atalhos_personalizados', {}),
            'auto_fill_enabled': data.get('auto_fill_enabled', True),
            'show_suggestions': data.get('show_suggestions', True),
            'validate_on_blur': data.get('validate_on_blur', True),
            'updated_at': data.get('updated_at')
        }


# Instância singleton
user_preference_service = UserPreferenceService()
