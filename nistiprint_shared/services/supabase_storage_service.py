import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SupabaseStorageService:
    def __init__(self):
        self.supabase_url = os.environ.get('SUPABASE_URL')
        self.supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")

        self.client = create_client(self.supabase_url, self.supabase_key)
        # Try different possible bucket names, starting with 'artworks'
        possible_bucket_names = [
            os.environ.get('SUPABASE_ARTWORKS_BUCKET', 'artworks'),
            'artworks',
            'public',
            'default',
            'images'
        ]

        self.bucket_name = None
        for bucket_name in possible_bucket_names:
            try:
                # Try to access the bucket by listing its content
                response = self.client.storage.from_(bucket_name).list('')
                self.bucket_name = bucket_name
                print(f"Using existing bucket: {self.bucket_name}")
                break
            except Exception:
                # If we can't access this bucket, try to create it
                try:
                    self.client.storage.create_bucket(bucket_name, options={"public": True})
                    self.bucket_name = bucket_name
                    print(f"Created new bucket: {self.bucket_name}")
                    break
                except Exception as create_error:
                    print(f"Could not use or create bucket '{bucket_name}': {create_error}")
                    continue

        if self.bucket_name is None:
            # If none of the common buckets worked, try to list what's available
            try:
                buckets_response = self.client.storage.list_buckets()
                available_buckets = [bucket.name for bucket in buckets_response.data]
                print(f"Available buckets: {available_buckets}")

                # Use the first available bucket if any exist
                if available_buckets:
                    self.bucket_name = available_buckets[0]
                    print(f"Using first available bucket: {self.bucket_name}")
                else:
                    raise ValueError("No storage buckets available in Supabase project")
            except Exception as list_error:
                print(f"Could not list buckets: {list_error}")
                raise ValueError("Could not access or create any storage bucket")

    def upload_artwork(self, file, product_id):
        """
        Upload an artwork file to Supabase storage
        """
        # Validate file
        if not file or file.filename == '':
            raise ValueError("No file provided")

        # Get file size before consuming the buffer
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)  # Reset file pointer to the beginning

        # Generate secure filename
        original_filename = secure_filename(file.filename)
        file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        unique_filename = f"products/{product_id}/{uuid.uuid4().hex}.{file_ext}"

        # Read the file content for upload
        file_content = file.read()

        # Upload file to Supabase storage
        response = self.client.storage.from_(self.bucket_name).upload(
            unique_filename,
            file_content,
            file_options={"content-type": file.content_type}
        )

        # Get public URL for the uploaded file
        try:
            # Use the download URL which should be publicly accessible
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(unique_filename)

            # Check if the URL ends with '?' which indicates missing token
            if public_url and public_url.endswith('?'):
                # If it ends with '?', it means we need a signed URL with token
                signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(unique_filename, 31536000)  # 1 year validity
                public_url = signed_url_response.signed_url
        except Exception as e:
            # If getting the public URL fails, try to generate a signed URL that's valid for a long time
            try:
                print(f"Error getting public URL: {e}")
                # Generate a signed URL that's valid for 1 year (31536000 seconds)
                signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(unique_filename, 31536000)
                public_url = signed_url_response.signed_url
            except Exception as signed_url_error:
                # If all else fails, construct the URL manually (though it may not work without proper permissions)
                print(f"Error creating signed URL: {signed_url_error}")
                public_url = f"{self.supabase_url}/storage/v1/object/public/{self.bucket_name}/{unique_filename}"

        return {
            'filename': unique_filename,
            'original_filename': original_filename,
            'public_url': public_url,
            'file_size': file_size,
            'mime_type': file.content_type
        }

    def delete_artwork(self, file_path):
        """
        Delete an artwork file from Supabase storage
        """
        try:
            self.client.storage.from_(self.bucket_name).remove([file_path])
            return True
        except Exception as e:
            print(f"Error deleting artwork from storage: {e}")
            return False

    def get_file_url(self, file_path):
        """
        Get the signed URL for a file in Supabase storage (requires authentication)
        """
        try:
            # Always generate a signed URL for secure access (valid for 1 hour)
            # This ensures only authenticated users can access the file
            signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(file_path, 3600)  # 1 hour validity
            return signed_url_response.signed_url
        except Exception as e:
            print(f"Error creating signed URL: {e}")
            try:
                # Fallback: try to get public URL first
                public_url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)

                # Check if the URL ends with '?' which indicates missing token
                if public_url and public_url.endswith('?'):
                    # If it ends with '?', try with a longer expiration time
                    signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(file_path, 31536000)  # 1 year validity
                    return signed_url_response.signed_url

                return public_url
            except Exception as fallback_error:
                print(f"Fallback also failed: {fallback_error}")
                # Last resort: construct the URL manually (may not work without proper permissions)
                return f"{self.supabase_url}/storage/v1/object/public/{self.bucket_name}/{file_path}"

    def get_public_url(self, file_path):
        """
        Get the public URL for a file in Supabase storage (for public access)
        """
        try:
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)

            # Check if the URL ends with '?' which indicates missing token
            if public_url and public_url.endswith('?'):
                # If it ends with '?', it means we need a signed URL with token
                signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(file_path, 31536000)  # 1 year validity
                return signed_url_response.signed_url

            return public_url
        except Exception as e:
            print(f"Error getting public URL: {e}")
            try:
                # If getting public URL fails, try to create a signed URL as fallback
                signed_url_response = self.client.storage.from_(self.bucket_name).create_signed_url(file_path, 31536000)  # 1 year validity
                return signed_url_response.signed_url
            except Exception as signed_url_error:
                print(f"Error creating signed URL: {signed_url_error}")
                return None

# Create a global instance of the service
supabase_storage_service = SupabaseStorageService()

