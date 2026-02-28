from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.usuario import Usuario
from nistiprint_shared.models.setor import Setor
from datetime import datetime

class UsuarioService:
    """Service for managing usuários (users)."""

    def get_all(self):
        """Get all usuários ordered by name."""
        usuarios = Usuario.query.filter_by(ativo=True).order_by(Usuario.nome).all()
        results = [usuario.to_dict_without_password() for usuario in usuarios]
        
        # In Supabase mode, the relationship might not be loaded, so we manually populate setor_nome
        if get_current_database_mode().name == 'SUPABASE':
            self._populate_setor_nomes(results)
            
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
        usuario = Usuario.query.filter_by(email=email, ativo=True).first()
        if not usuario:
            return None
            
        data = usuario.to_dict_without_password()
        
        # In Supabase mode, the relationship might not be loaded, so we manually populate setor_nome
        if get_current_database_mode().name == 'SUPABASE' and not data.get('setor_nome'):
            setor = Setor.query.get(data['setor_id'])
            if setor:
                data['setor_nome'] = setor.nome
        elif not data.get('setor_nome') and usuario.setor:
            data['setor_nome'] = usuario.setor.nome
            
        return data

    def authenticate(self, email: str, senha: str):
        """Authenticate user by email and password."""
        usuario_model = Usuario.query.filter_by(email=email, ativo=True).first()
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
        # Check if email already exists
        existing = Usuario.query.filter_by(email=usuario_data['email']).first()
        if existing:
            raise ValueError(f"Usuário com email '{usuario_data['email']}' já existe")

        # Check if setor exists
        setor = Setor.query.filter_by(id=usuario_data['setor_id'], ativo=True).first()
        if not setor:
            raise ValueError(f"Setor com ID '{usuario_data['setor_id']}' não encontrado")

        usuario = Usuario(
            nome=usuario_data['nome'],
            email=usuario_data['email'],
            setor_id=usuario_data['setor_id'],
            ativo=usuario_data.get('ativo', True),
            is_admin=usuario_data.get('is_admin', False)
        )

        usuario.set_senha(usuario_data['senha'])

        # Only add to session if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.add(usuario)
            db.session.commit()
        else:
            # For Supabase, we need to handle the creation differently
            # This would typically involve calling the Supabase client directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Convert the usuario object to a dictionary
            usuario_dict = {}
            for attr_name in dir(usuario):
                if not attr_name.startswith('_') and not callable(getattr(usuario, attr_name)):
                    attr_value = getattr(usuario, attr_name)
                    if attr_name != 'query':  # Skip the query attribute
                        usuario_dict[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in usuario_dict:
                del usuario_dict['query']

            # Insert the user into Supabase
            result = supabase_db.insert('usuarios', usuario_dict)
            if result:
                usuario.id = result.get('id')

        return usuario.to_dict_without_password()

    def update(self, usuario_id: int, usuario_data):
        """Update an existing usuário."""
        usuario = Usuario.query.filter_by(id=usuario_id).first()
        if not usuario:
            raise ValueError(f"Usuário com ID '{usuario_id}' não encontrado")

        # Check if email conflicts with another usuário
        if 'email' in usuario_data:
            existing = Usuario.query.filter_by(email=usuario_data['email']).filter(Usuario.id != usuario_id).first()
            if existing:
                raise ValueError(f"Usuário com email '{usuario_data['email']}' já existe")

            usuario.email = usuario_data['email']

        # Check if setor exists
        if 'setor_id' in usuario_data:
            setor = Setor.query.filter_by(id=usuario_data['setor_id'], ativo=True).first()
            if not setor:
                raise ValueError(f"Setor com ID '{usuario_data['setor_id']}' não encontrado")

            usuario.setor_id = usuario_data['setor_id']

        if 'nome' in usuario_data:
            usuario.nome = usuario_data['nome']

        if 'ativo' in usuario_data:
            usuario.ativo = usuario_data['ativo']

        if 'is_admin' in usuario_data:
            usuario.is_admin = usuario_data['is_admin']

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
            for attr_name in ['nome', 'email', 'setor_id', 'ativo', 'is_admin', 'senha_hash', 'last_login']:
                if hasattr(usuario, attr_name):
                    attr_value = getattr(usuario, attr_name)
                    if attr_value is not None:
                        update_data[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in update_data:
                del update_data['query']

            # Update the user in Supabase
            result = supabase_db.update('usuarios', usuario.id, update_data)
            if result:
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

        usuario.ativo = False

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            result = supabase_db.update('usuarios', usuario.id, {'ativo': False})
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

