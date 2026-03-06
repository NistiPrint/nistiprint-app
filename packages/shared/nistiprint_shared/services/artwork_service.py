import os
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session
from nistiprint_shared.models.product_artwork import ProductArtwork
from nistiprint_shared.models.product import Product
from flask import current_app
from nistiprint_shared.services.supabase_storage_service import supabase_storage_service


class ArtworkService:
    def __init__(self):
        self.allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'svg', 'bmp', 'tiff', 'webp'}
        self.max_file_size = 10 * 1024 * 1024  # 10MB in bytes

    def allowed_file(self, filename):
        """Check if the uploaded file has an allowed extension."""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in self.allowed_extensions

    def get_file_size(self, file):
        """Get the size of the uploaded file."""
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)  # Reset file pointer to the beginning
        return size

    def save_artwork(self, file, product_id):
        """Save the uploaded artwork file and create a record in the database."""
        # Validate inputs
        if not file or file.filename == '':
            raise ValueError("No file provided")

        if product_id is None or product_id == "None" or product_id == "":
            raise ValueError("Product ID is required and cannot be None or empty")

        if not self.allowed_file(file.filename):
            raise ValueError(f"File type not allowed. Allowed types: {', '.join(self.allowed_extensions)}")

        file_size = self.get_file_size(file)
        if file_size > self.max_file_size:
            raise ValueError(f"File size exceeds limit of {self.max_file_size // (1024*1024)}MB")

        # Find the product to ensure it exists using Supabase session
        with get_db_session() as session:
            product = session.query_model(Product).filter_by(id=product_id).first()
            if not product:
                raise ValueError(f"Product with ID {product_id} not found")

        # Upload file to Supabase storage
        upload_result = supabase_storage_service.upload_artwork(file, product_id)

        # Create database record using Supabase session
        artwork = ProductArtwork()
        artwork.product_id = product_id
        artwork.filename = upload_result['filename']
        artwork.original_filename = upload_result['original_filename']
        artwork.file_path = upload_result['public_url']  # Store the public URL
        artwork.file_size = upload_result['file_size']
        artwork.mime_type = upload_result['mime_type']
        artwork.upload_date = datetime.utcnow()  # Explicitly set the upload date

        with get_db_session() as session:
            session.add(artwork)
            session.commit()

            # Fetch the complete artwork record from the database to ensure all fields are populated
            complete_artwork = session.query_model(ProductArtwork).filter_by(
                id=artwork.id
            ).first()

        return complete_artwork
    
    def get_artworks_for_product(self, product_id):
        """Retrieve all artworks associated with a product."""
        if product_id is None or product_id == "None" or product_id == "":
            return []  # Return empty list if product_id is invalid

        try:
            with get_db_session() as session:
                artworks = session.query_model(ProductArtwork).filter_by(
                    product_id=product_id
                ).all()
            return artworks
        except Exception as e:
            import logging
            logging.warning(f"Error retrieving artworks for product {product_id}: {e}")
            return []

    def delete_artwork(self, artwork_id):
        """Delete an artwork file and its database record."""
        with get_db_session() as session:
            artwork = session.query_model(ProductArtwork).filter_by(
                id=artwork_id
            ).first()

            if not artwork:
                raise ValueError(f"Artwork with ID {artwork_id} not found")

            # Delete the file from Supabase storage
            supabase_storage_service.delete_artwork(artwork.filename)

            # Delete the database record
            session.delete(artwork)
            session.commit()

        return True

# Create a global instance of the service
artwork_service = ArtworkService()

