from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.permissao import Recurso, PermissaoSetor
from nistiprint_shared.models.usuario import Usuario

class PermissaoService:
    """Service for managing permissions."""

    def get_setor_permissions(self, setor_id: int):
        """Get all permissions for a specific sector."""
        # Get all permissions for the sector
        if get_current_database_mode().name == 'SUPABASE':
            from nistiprint_shared.database.supabase_db_service import supabase_db
            response = supabase_db.execute_with_retry(
                supabase_db.table('permissoes_setor').select("*").eq('setor_id', setor_id)
            )
            permissoes_data = response.data or []
            
            # Map data to a list of objects or dicts
            recurso_ids = [p['recurso_id'] for p in permissoes_data]
            recursos_map = {}

            if recurso_ids:
                res_recursos = supabase_db.execute_with_retry(
                    supabase_db.table('recursos').select("id, nome").in_('id', recurso_ids)
                )
                recursos_map = {r['id']: r['nome'] for r in res_recursos.data or []}

            result = {}
            for p in permissoes_data:
                recurso_nome = recursos_map.get(p['recurso_id'])
                if recurso_nome:
                    result[recurso_nome] = {
                        'ler': p.get('pode_ler', False),
                        'criar': p.get('pode_criar', False),
                        'editar': p.get('pode_editar', False),
                        'excluir': p.get('pode_excluir', False)
                    }
            return result
        else:
            # SQLAlchemy legacy mode
            permissoes = PermissaoSetor.query.filter_by(setor_id=setor_id).all() or []

            # Create a mapping of recurso_id to recurso name for lookup
            recurso_ids = [p.recurso_id for p in permissoes]
            recursos_map = {}

            if recurso_ids:
                # Get all recursos that are referenced in the permissions
                recursos = Recurso.query.filter(Recurso.id.in_(recurso_ids)).all()
                recursos_map = {r.id: r.nome for r in recursos}

            # Build the permissions dictionary
            result = {}
            for p in permissoes:
                recurso_nome = recursos_map.get(p.recurso_id)
                if recurso_nome:
                    result[recurso_nome] = {
                        'ler': p.pode_ler,
                        'criar': p.pode_criar,
                        'editar': p.pode_editar,
                        'excluir': p.pode_excluir
                    }

            return result

    def has_permission(self, usuario_id: int, recurso_nome: str, acao: str):
        """
        Check if a user has permission for a resource and action.
        acao can be: 'ler', 'criar', 'editar', 'excluir'
        """
        if usuario_id is None:
            return False

        # Get User and Sector info
        if get_current_database_mode().name == 'SUPABASE':
            from nistiprint_shared.database.supabase_db_service import supabase_db
            res_user = supabase_db.execute_with_retry(
                supabase_db.table('usuarios').select("*, setores(nome)").eq('id', usuario_id).single()
            )
            usuario = res_user.data
            if not usuario or not usuario.get('ativo'):
                return False
            
            if usuario.get('is_admin'):
                return True
            
            sector_name = usuario.get('setores', {}).get('nome') if usuario.get('setores') else None
            if sector_name == 'Administrativo':
                return True

            # Check specific permission
            res_perm = supabase_db.execute_with_retry(
                supabase_db.table('permissoes_setor')
                .select("*, recursos!inner(nome)")
                .eq('setor_id', usuario['setor_id'])
                .eq('recursos.nome', recurso_nome)
                .single()
            )
            permissao = res_perm.data
            if not permissao:
                return False

            mapping = {
                'ler': 'pode_ler',
                'criar': 'pode_criar',
                'editar': 'pode_editar',
                'excluir': 'pode_excluir'
            }
            return permissao.get(mapping.get(acao), False)
        else:
            # SQLAlchemy legacy mode
            usuario = Usuario.query.get(usuario_id)
            if not usuario or not usuario.ativo:
                return False

            if usuario.is_admin or (usuario.setor and usuario.setor.nome == 'Administrativo'):
                return True

            recurso = Recurso.query.filter_by(nome=recurso_nome).first()
            if not recurso:
                return False

            permissao = PermissaoSetor.query.filter_by(
                setor_id=usuario.setor_id,
                recurso_id=recurso.id
            ).first()

            if not permissao:
                return False

            if acao == 'ler': return permissao.pode_ler
            if acao == 'criar': return permissao.pode_criar
            if acao == 'editar': return permissao.pode_editar
            if acao == 'excluir': return permissao.pode_excluir
            return False

    def update_setor_permission(self, setor_id: int, recurso_nome: str, pode_ler=None, pode_criar=None, pode_editar=None, pode_excluir=None):
        """Update permissions for a sector and resource."""
        recurso = Recurso.query.filter_by(nome=recurso_nome).first()
        if not recurso:
            raise ValueError(f"Recurso '{recurso_nome}' não encontrado")

        permissao = PermissaoSetor.query.filter_by(
            setor_id=setor_id,
            recurso_id=recurso.id
        ).first()

        if not permissao:
            permissao = PermissaoSetor(setor_id=setor_id, recurso_id=recurso.id)
            # Only add to session if using SQLAlchemy mode, not Supabase
            if get_current_database_mode().name != 'SUPABASE':
                db.session.add(permissao)
            else:
                # For Supabase, we need to handle the creation differently
                from nistiprint_shared.database.supabase_db_service import supabase_db
                # Convert the permissao object to a dictionary
                permissao_dict = {}
                for attr_name in dir(permissao):
                    if not attr_name.startswith('_') and not callable(getattr(permissao, attr_name)):
                        attr_value = getattr(permissao, attr_name)
                        if attr_name != 'query':  # Skip the query attribute
                            permissao_dict[attr_name] = attr_value

                # Remove any SQLAlchemy-specific attributes that don't belong in the database
                if 'query' in permissao_dict:
                    del permissao_dict['query']

                # Insert the permissao into Supabase
                result = supabase_db.insert('permissoes_setor', permissao_dict)
                if result:
                    permissao.id = result.get('id')

        if pode_ler is not None:
            permissao.pode_ler = pode_ler
        if pode_criar is not None:
            permissao.pode_criar = pode_criar
        if pode_editar is not None:
            permissao.pode_editar = pode_editar
        if pode_excluir is not None:
            permissao.pode_excluir = pode_excluir

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Convert the permissao object to a dictionary with only the fields to update
            update_data = {}
            for attr_name in ['setor_id', 'recurso_id', 'pode_ler', 'pode_criar', 'pode_editar', 'pode_excluir']:
                if hasattr(permissao, attr_name):
                    attr_value = getattr(permissao, attr_name)
                    if attr_value is not None:
                        update_data[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in update_data:
                del update_data['query']

            # Update the permissao in Supabase
            result = supabase_db.update('permissoes_setor', permissao.id, update_data)
            if result:
                # Update the object with the returned data
                for key, value in result.items():
                    if hasattr(permissao, key):
                        setattr(permissao, key, value)

        return permissao.to_dict()

permissao_service = PermissaoService()

