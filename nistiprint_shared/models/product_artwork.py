from datetime import datetime
from nistiprint_shared.database.database import db
from nistiprint_shared.services.supabase_storage_service import supabase_storage_service


class ProductArtwork(db.Model):
    __tablename__ = 'product_artworks'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    filename = db.Column(db.String, nullable=False)
    original_filename = db.Column(db.String, nullable=False)
    file_path = db.Column(db.String, nullable=False)
    file_size = db.Column(db.Integer)  # in bytes
    mime_type = db.Column(db.String)
    upload_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def get_updated_file_url(self):
        """Get an updated file URL that's guaranteed to be valid (with proper token for secure access)."""
        if not self.filename:
            # If there's no filename, fall back to the stored file_path
            return self.file_path
        return supabase_storage_service.get_file_url(self.filename)  # This now returns a signed URL for secure access

    def to_dict(self, use_updated_url=False):

        return {
            'id': self.id,
            'product_id': self.product_id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_path': file_path,  # This is now the public URL
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'upload_date': format_datetime(self.upload_date),
        }

# --- Relationships definitions at the bottom ---
ProductArtwork.product = db.relationship("Product", back_populates="artworks")
