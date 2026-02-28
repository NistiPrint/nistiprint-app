from datetime import datetime
from nistiprint_shared.database.supabase_db_service import get_db_session
from nistiprint_shared.models.print_job import PrintJob
from nistiprint_shared.models.demanda_producao import DemandaProducaoItem, DemandaProducao
from nistiprint_shared.models.product import Product
from nistiprint_shared.models.product_artwork import ProductArtwork

class PrintService:
    def __init__(self):
        pass

    def create_job_from_item(self, item_id, artwork_type_filter=None, mode='full'):
        """
        Create print jobs for a specific production demand item.
        
        :param item_id: ID of the demand item.
        :param artwork_type_filter: Filter for 'capa' or 'miolo'.
        :param mode: 'full' (print total quantity) or 'balance' (print remaining quantity).
        """
        with get_db_session() as session:
            # 1. Fetch item
            item = session.query_model(DemandaProducaoItem).filter_by(id=item_id).first()
            if not item:
                raise ValueError(f"Item de demanda {item_id} não encontrado")
            
            product_id = item.produto_id
            if not product_id:
                 raise ValueError(f"Item {item_id} não possui produto associado")

            # 2. Fetch artworks for the product
            artworks = session.query_model(ProductArtwork).filter_by(product_id=product_id).all()
            
            if not artworks:
                 raise ValueError(f"Produto {product_id} não possui artes cadastradas")
            
            created_jobs = []
            
            for artwork in artworks:
                # Logic to determine type
                tipo_arquivo = 'indefinido'
                lower_name = artwork.original_filename.lower()
                if 'capa' in lower_name:
                    tipo_arquivo = 'capa'
                elif 'miolo' in lower_name:
                    tipo_arquivo = 'miolo'
                
                # Apply filter if provided
                if artwork_type_filter and artwork_type_filter.lower() != tipo_arquivo:
                    continue

                # Calculate quantity based on mode
                quantidade_job = item.quantidade  # Default 'full'
                if mode == 'balance':
                    # Determine what "printed" means based on file type
                    # Ideally we should track 'printed' status per component type (capa vs miolo)
                    # Currently DemandaProducaoItem has 'capas_impressas_qtd'
                    # Assuming 'capas_impressas_qtd' tracks the main print progress
                    
                    already_printed = item.capas_impressas_qtd or 0
                    quantidade_job = max(0, item.quantidade - already_printed)
                
                if quantidade_job <= 0:
                    continue # Nothing to print

                new_job = PrintJob(
                    demanda_item_id=item_id,
                    product_id=product_id,
                    artwork_id=artwork.id,
                    tipo_arquivo=tipo_arquivo,
                    status='pendente',
                    quantidade=quantidade_job,
                    tentativas=0,
                    logs=f"Job criado em {datetime.now().isoformat()}. Mode: {mode}. Qtd: {quantidade_job}"
                )
                session.add(new_job)
                created_jobs.append(new_job)
            
            session.commit()
            
            # Refresh to get IDs
            return [job.to_dict() for job in created_jobs]

    def create_jobs_for_demanda(self, demanda_id, mode='full'):
        """Create print jobs for all items in a demand."""
        
        with get_db_session() as session:
            # Check if it's an integer or try to find by string ID
            demanda = None
            if str(demanda_id).isdigit():
                demanda = session.query_model(DemandaProducao).filter_by(id=int(demanda_id)).first()
            
            if not demanda:
                 # Try finding by demanda_id string
                 demanda = session.query_model(DemandaProducao).filter_by(demanda_id=str(demanda_id)).first()
            
            if not demanda:
                raise ValueError(f"Demanda {demanda_id} não encontrada")

            items = session.query_model(DemandaProducaoItem).filter_by(demanda_id=demanda.id).all()
            
            all_jobs = []
            for item in items:
                try:
                    jobs = self.create_job_from_item(item.id, mode=mode)
                    all_jobs.extend(jobs)
                except ValueError as e:
                    # Log error but continue with other items? Or fail?
                    # For now, we'll just log/print and continue, maybe adding to a report
                    print(f"Skipping item {item.id}: {e}")
            
            return all_jobs

    def retry_job(self, job_id):
        with get_db_session() as session:
            job = session.query_model(PrintJob).filter_by(id=job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} não encontrado")
            
            job.status = 'pendente'
            job.tentativas += 1
            job.logs += f"\nRetrying at {datetime.now().isoformat()}"
            session.commit()
            return job.to_dict()

    def get_job_status(self, job_id):
        with get_db_session() as session:
            job = session.query_model(PrintJob).filter_by(id=job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} não encontrado")
            return job.to_dict()

    def get_product_jobs(self, product_id):
         with get_db_session() as session:
            jobs = session.query_model(PrintJob).filter_by(product_id=product_id).all()
            return [job.to_dict() for job in jobs]

    def cancel_job(self, job_id):
        with get_db_session() as session:
            job = session.query_model(PrintJob).filter_by(id=job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} não encontrado")
            
            job.status = 'cancelado'
            job.logs += f"\nCancelled at {datetime.now().isoformat()}"
            session.commit()
            return job.to_dict()

# Create a global instance of the service
print_service = PrintService()

