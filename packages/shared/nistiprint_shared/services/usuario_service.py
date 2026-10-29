from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.usuario import Usuario
from nistiprint_shared.models.setor import Setor
from datetime import datetime
from sqlalchemy import func

class UsuarioService:
    """Service for managing usuários (users)."""

    def _matching_email_ids(self, email, *, active=None):
        normalized_email = str(email or '').strip().lower()
        if get_current_database_mode().name == 'SUPABASE':
            from nistiprint_shared.database.supabase_db_service import supabase_db
            query = supabase_db.table('usuarios').select('id').ilike('email', normalized_email)
            if active is not None:
                query = query.eq('ativo', bool(active))
            return [int(row['id']) for row in (query.execute().data or []) if row.get('id') is not None]
        query = Usuario.query.filter(func.lower(Usuario.email) == normalized_email)
        if active is not None:
            query = query.filter(Usuario.ativo == bool(active))
        return [int(row.id) for row in query.all()]

    def _active_admin_count(self):
        if get_current_database_mode().name == 'SUPABASE':
            from nistiprint_shared.database.supabase_db_service import supabase_db
            result = (supabase_db.table('usuarios').select('id', count='exact', head=True)
                      .eq('ativo', True).eq('is_admin', True).execute())
            return int(getattr(result, 'count', 0) or 0)
        return Usuario.query.filter_by(ativo=True, is_admin=True).count()

    def get_all(self):
        """Get all usuários, including inactive accounts, ordered by name."""
        if get_current_database_mode().name == 'SUPABASE':
            from nistiprint_shared.database.supabase_db_service import supabase_db
            rows = supabase_db.get_all('usuarios', raise_on_error=True)
            results = [{key: value for key, value in row.items() if key != 'senha_hash'} for row in rows]
            results.sort(key=lambda usuario: str(usuario.get('nome') or '').casefold())
            self._populate_setor_nomes(results)
            return results

        usuarios = Usuario.query.order_by(Usuario.nome).all()
        results = [usuario.to_dict_without_password() for usuario in usuarios]
        return results

    def get_all_including_inactive(self):
        """Get all usuários including inactive ones."""
        usuarios = Usuario.query.order_by(Usuario.nome).all()
        results = [usuario.to_dict_without_password() for usuario in usuarios]
        
        if get_current_database_mode().name == 'SUPABASE':
            self._populate_setor_nomes(results)
            
        return results

    def get_by_id(self, usuario_id: int):
        """Get usuário by ID."""
        usuario = Usuario.query.filter_by(id=usuario_id, ativo=True).first()
        if not usuario:
            return None

        data = usuario.to_dict_without_password()

        if get_current_database_mode().name == 'SUPABASE' and not data.get('setor_nome'):
            setor = Setor.query.get(data['setor_id'])
            if setor:
                data['setor_nome'] = setor.nome
        elif not data.get('setor_nome') and usuario.setor:
            # For SQLAlchemy mode, ensure setor_nome is populated
            data['setor_nome'] = usuario.setor.nome

        return data

    def get_by_id_including_inactive(self, usuario_id: int):
        usuario = Usuario.query.filter_by(id=usuario_id).first()
        if not usuario:
            return None
        data = usuario.to_dict_without_password()
        if get_current_database_mode().name == 'SUPABASE' and not data.get('setor_nome'):
            setor = Setor.query.get(data['setor_id'])
            if setor:
                data['setor_nome'] = setor.nome
        return data

    def _populate_setor_nomes(self, usuario_dicts):
        """Helper to populate setor_nome for a list of user dictionaries."""
        if not usuario_dicts:
            return
            
        setores = Setor.query.all()
        setor_map = {s.id: s.nome for s in setores}
        
        for u in usuario_dicts:
            if not u.get('setor_nome') and u.get('setor_id') in setor_map:
                u['setor_nome'] = setor_map[u['setor_id']]

    def get_by_email(self, email: str):
        """Get usuário by email."""
        normalized_email = str(email or '').strip().lower()
        matching_ids = self._matching_email_ids(normalized_email, active=True)
        if len(matching_ids) != 1:
            return None
        data = self.get_by_id(matching_ids[0])
        if not data:
            return None
        
        return data

    def email_belongs_uniquely_to(self, email: str, usuario_id: int):
        """Return whether exactly one account owns an email, including inactive accounts."""
        matching_ids = self._matching_email_ids(email)
        return len(matching_ids) == 1 and matching_ids[0] == int(usuario_id)

    def authenticate(self, email: str, senha: str):
        """Authenticate user by email and password."""
        normalized_email = str(email or '').strip().lower()
        usuario_model = Usuario.query.filter(func.lower(Usuario.email) == normalized_email, Usuario.ativo.is_(True)).first()
        if usuario_model and usuario_model.check_senha(senha):
            # Update last login
            usuario_model.last_login = datetime.utcnow()

            # Only commit if using SQLAlchemy mode, not Supabase
            if get_current_database_mode().name != 'SUPABASE':
                db.session.commit()

            # Ensure setor_nome is included in the returned data
            user_data = usuario_model.to_dict_without_password()
            
            if get_current_database_mode().name == 'SUPABASE' and not user_data.get('setor_nome'):
                setor = Setor.query.get(user_data['setor_id'])
                if setor:
                    user_data['setor_nome'] = setor.nome
            elif not user_data.get('setor_nome') and usuario_model.setor:
                user_data['setor_nome'] = usuario_model.setor.nome

            return user_data
        return None

    def create(self, usuario_data):
        """Create a new usuário."""
        normalized_email = self.validate_create(usuario_data)

        usuario = Usuario(
            nome=usuario_data['nome'],
            email=normalized_email,
            setor_id=usuario_data['setor_id'],
            ativo=usuario_data.get('ativo', True),
            is_admin=usuario_data.get('is_admin', False)
        )
        if usuario_data.get('auth_user_id'):
            usuario.auth_user_id = usuario_data['auth_user_id']
        usuario.must_change_password = bool(usuario_data.get('must_change_password', False))

        usuario.set_senha(usuario_data['senha'])

        # Only add to session if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.add(usuario)
            db.session.commit()
        else:
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Send only persisted columns. Iterating over the SQLAlchemy model
            # also includes descriptors and internal fields that PostgREST
            # cannot insert, and the old adapter swallowed that failure.
            usuario_record = {
                'nome': usuario.nome,
                'email': usuario.email,
                'senha_hash': usuario.senha_hash,
                'setor_id': usuario.setor_id,
                'ativo': usuario.ativo,
                'is_admin': usuario.is_admin,
                'must_change_password': usuario.must_change_password,
                'session_version': usuario.session_version or 0,
            }
            if usuario.auth_user_id:
                usuario_record['auth_user_id'] = str(usuario.auth_user_id)

            result = supabase_db.insert('usuarios', usuario_record, raise_on_error=True)
            if not result or result.get('id') is None:
                raise RuntimeError('O Supabase não confirmou a gravação do usuário. Tente novamente.')
            usuario.id = result['id']

        return usuario.to_dict_without_password()

    def validate_create(self, usuario_data):
        """Validate DB-backed fields before provisioning an external Auth identity."""
        normalized_email = str(usuario_data.get('email') or '').strip().lower()
        if self._matching_email_ids(normalized_email):
            raise ValueError(f"Usuário com email '{normalized_email}' já existe")

        setor = Setor.query.filter_by(id=usuario_data['setor_id'], ativo=True).first()
        if not setor:
            raise ValueError(f"Setor com ID '{usuario_data['setor_id']}' não encontrado")
        return normalized_email

    def validate_update(self, usuario_id: int, usuario_data):
        """Validate account changes before coordinating with external Auth."""
        usuario = Usuario.query.filter_by(id=usuario_id).first()
        if not usuario:
            raise ValueError(f"Usuário com ID '{usuario_id}' não encontrado")
        is_default_admin = str(usuario.email or '').strip().lower() == 'admin@admin.com'
        next_email = str(usuario_data.get('email', usuario.email) or '').strip().lower()
        if is_default_admin and (
            usuario_data.get('ativo', usuario.ativo) is False
            or usuario_data.get('is_admin', usuario.is_admin) is False
            or next_email != 'admin@admin.com'
        ):
            raise ValueError('A conta administrativa padrão deve permanecer ativa, administrativa e com o e-mail padrão.')
        loses_admin_access = bool(usuario.is_admin) and (
            usuario_data.get('ativo', usuario.ativo) is False
            or usuario_data.get('is_admin', usuario.is_admin) is False
        )
        if loses_admin_access and self._active_admin_count() <= 1:
            raise ValueError('Não é possível desativar ou rebaixar o último administrador ativo.')
        if 'email' in usuario_data:
            normalized_email = str(usuario_data['email'] or '').strip().lower()
            existing_ids = self._matching_email_ids(normalized_email)
            if any(existing_id != int(usuario_id) for existing_id in existing_ids):
                raise ValueError(f"Usuário com email '{normalized_email}' já existe")
        if 'setor_id' in usuario_data and int(usuario_data['setor_id']) != int(usuario.setor_id or 0):
            setor = Setor.query.filter_by(id=usuario_data['setor_id'], ativo=True).first()
            if not setor:
                raise ValueError(f"Setor com ID '{usuario_data['setor_id']}' não encontrado")
        return usuario

    def update(self, usuario_id: int, usuario_data):
        """Update an existing usuário."""
        usuario = self.validate_update(usuario_id, usuario_data)

        if 'email' in usuario_data:
            normalized_email = str(usuario_data['email'] or '').strip().lower()
            usuario.email = normalized_email

        # Keep an existing inactive sector assignment editable for inactive
        # users. A sector must be active when the assignment changes.
        if 'setor_id' in usuario_data and int(usuario_data['setor_id']) != int(usuario.setor_id or 0):
            usuario.setor_id = usuario_data['setor_id']

        if 'nome' in usuario_data:
            usuario.nome = usuario_data['nome']

        if 'ativo' in usuario_data:
            usuario.ativo = usuario_data['ativo']

        if 'is_admin' in usuario_data:
            usuario.is_admin = usuario_data['is_admin']

        if 'auth_user_id' in usuario_data:
            usuario.auth_user_id = usuario_data['auth_user_id']
        if 'must_change_password' in usuario_data:
            usuario.must_change_password = usuario_data['must_change_password']
        if 'session_version' in usuario_data:
            usuario.session_version = usuario_data['session_version']

        # Update password if provided
        if 'senha' in usuario_data and usuario_data['senha']:
            usuario.set_senha(usuario_data['senha'])

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Convert the usuario object to a dictionary with only the fields to update
            update_data = {}
            for attr_name in ['nome', 'email', 'setor_id', 'ativo', 'is_admin', 'senha_hash', 'last_login', 'auth_user_id', 'must_change_password', 'session_version']:
                if hasattr(usuario, attr_name):
                    attr_value = getattr(usuario, attr_name)
                    if attr_value is not None:
                        update_data[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in update_data:
                del update_data['query']

            # Update the user in Supabase
            result = supabase_db.update('usuarios', usuario.id, update_data, raise_on_error=True)
            if not result:
                raise RuntimeError(f"O Supabase não confirmou a atualização do usuário {usuario.id}.")
            # Update the object with the returned data
            for key, value in result.items():
                if hasattr(usuario, key):
                    setattr(usuario, key, value)

        return usuario.to_dict_without_password()

    def delete(self, usuario_id: int):
        """Soft delete a usuário by setting ativo to False."""
        usuario = Usuario.query.filter_by(id=usuario_id).first()
        if not usuario:
            raise ValueError(f"Usuário com ID '{usuario_id}' não encontrado")

        if str(usuario.email or '').strip().lower() == 'admin@admin.com':
            raise ValueError('A conta administrativa padrão deve permanecer ativa.')
        if usuario.is_admin and self._active_admin_count() <= 1:
            raise ValueError('Não é possível desativar o último administrador ativo.')

        usuario.session_version = int(usuario.session_version or 0) + 1

        usuario.ativo = False

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            result = supabase_db.update('usuarios', usuario.id, {
                'ativo': False,
                'session_version': usuario.session_version,
            })
            if result:
                usuario.ativo = result.get('ativo', False)

        return True

    def change_password(self, usuario_id: int, senha_atual: str, nova_senha: str):
        """Change user password."""
        usuario = Usuario.query.filter_by(id=usuario_id).first()
        if not usuario:
            raise ValueError(f"Usuário com ID '{usuario_id}' não encontrado")

        if not usuario.check_senha(senha_atual):
            raise ValueError("Senha atual incorreta")

        usuario.set_senha(nova_senha)

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            result = supabase_db.update('usuarios', usuario.id, {'senha_hash': usuario.senha_hash})
            if result:
                usuario.senha_hash = result.get('senha_hash')

        return True

    def count(self):
        """Get total count of active usuários."""
        return Usuario.query.filter_by(ativo=True).count()

# Global instance for use throughout the application
usuario_service = UsuarioService()

