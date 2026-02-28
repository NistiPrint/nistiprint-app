from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.setor import Setor

class SetorService:
    """Service for managing setores (departments/sectors)."""

    def get_all(self):
        """Get all setores ordered by name."""
        setores = Setor.query.filter_by(ativo=True).order_by(Setor.nome).all()
        return [setor.to_dict() for setor in setores]

    def get_all_including_inactive(self):
        """Get all setores including inactive ones."""
        setores = Setor.query.order_by(Setor.nome).all()
        return [setor.to_dict() for setor in setores]

    def get_by_id(self, setor_id: int):
        """Get setor by ID."""
        setor = Setor.query.filter_by(id=setor_id, ativo=True).first()
        return setor.to_dict() if setor else None

    def create(self, setor_data):
        """Create a new setor."""
        # Check if name already exists
        existing = Setor.query.filter_by(nome=setor_data['nome']).first()
        if existing:
            raise ValueError(f"Setor com nome '{setor_data['nome']}' já existe")

        setor = Setor(
            nome=setor_data['nome'],
            descricao=setor_data.get('descricao', ''),
            ativo=setor_data.get('ativo', True)
        )

        # Only add to session if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.add(setor)
            db.session.commit()
        else:
            # For Supabase, we need to handle the creation differently
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Convert the setor object to a dictionary
            setor_dict = {}
            for attr_name in dir(setor):
                if not attr_name.startswith('_') and not callable(getattr(setor, attr_name)):
                    attr_value = getattr(setor, attr_name)
                    if attr_name != 'query':  # Skip the query attribute
                        setor_dict[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in setor_dict:
                del setor_dict['query']

            # Insert the setor into Supabase
            result = supabase_db.insert('setores', setor_dict)
            if result:
                setor.id = result.get('id')

        return setor.to_dict()

    def update(self, setor_id: int, setor_data):
        """Update an existing setor."""
        setor = Setor.query.filter_by(id=setor_id).first()
        if not setor:
            raise ValueError(f"Setor com ID '{setor_id}' não encontrado")

        # Check if name conflicts with another setor
        if 'nome' in setor_data:
            existing = Setor.query.filter_by(nome=setor_data['nome']).filter(Setor.id != setor_id).first()
            if existing:
                raise ValueError(f"Setor com nome '{setor_data['nome']}' já existe")

            setor.nome = setor_data['nome']

        if 'descricao' in setor_data:
            setor.descricao = setor_data['descricao']

        if 'ativo' in setor_data:
            setor.ativo = setor_data['ativo']

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            # Convert the setor object to a dictionary with only the fields to update
            update_data = {}
            for attr_name in ['nome', 'descricao', 'ativo']:
                if hasattr(setor, attr_name):
                    attr_value = getattr(setor, attr_name)
                    if attr_value is not None:
                        update_data[attr_name] = attr_value

            # Remove any SQLAlchemy-specific attributes that don't belong in the database
            if 'query' in update_data:
                del update_data['query']

            # Update the setor in Supabase
            result = supabase_db.update('setores', setor.id, update_data)
            if result:
                # Update the object with the returned data
                for key, value in result.items():
                    if hasattr(setor, key):
                        setattr(setor, key, value)

        return setor.to_dict()

    def delete(self, setor_id: int):
        """Soft delete a setor by setting ativo to False."""
        setor = Setor.query.filter_by(id=setor_id).first()
        if not setor:
            raise ValueError(f"Setor com ID '{setor_id}' não encontrado")

        # Check if there are users in this setor
        if hasattr(setor, 'usuarios') and setor.usuarios:
            raise ValueError(f"Não é possível excluir setor '{setor.nome}' pois existem usuários vinculados a ele")

        setor.ativo = False

        # Only commit if using SQLAlchemy mode, not Supabase
        if get_current_database_mode().name != 'SUPABASE':
            db.session.commit()
        else:
            # For Supabase, update the record directly
            from nistiprint_shared.database.supabase_db_service import supabase_db
            result = supabase_db.update('setores', setor.id, {'ativo': False})
            if result:
                setor.ativo = result.get('ativo', False)

        return True

    def count(self):
        """Get total count of active setores."""
        return Setor.query.filter_by(ativo=True).count()

# Global instance for use throughout the application
setor_service = SetorService()

