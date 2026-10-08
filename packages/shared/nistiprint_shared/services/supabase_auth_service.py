"""
Supabase Authentication Service
This service handles user authentication using Supabase Auth
"""
import os
from typing import Dict, Optional
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SupabaseAuthService:
    """
    Service for handling authentication with Supabase Auth
    """
    
    def __init__(self):
        self.supabase_url = os.environ.get('SUPABASE_URL')
        self.supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")

        try:
            self.client: Client = create_client(self.supabase_url, self.supabase_key)
            print("Successfully connected to Supabase")
        except Exception as e:
            print(f"Failed to connect to Supabase: {e}")
            raise

    def authenticate(self, email: str, password: str) -> Optional[Dict]:
        """
        Authenticate a user with email and password using Supabase Auth
        """
        try:
            # Sign in with email and password
            # Auth clients keep mutable session state. Create one per login so
            # concurrent requests never overwrite a different user's token.
            client = create_client(self.supabase_url, self.supabase_key)
            response = client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            user = response.user
            return {
                'id': user.id,
                'email': user.email,
                'user_metadata': user.user_metadata,
                'app_metadata': user.app_metadata
            }
        except Exception as e:
            print(f"Authentication failed: {e}")
            return None

    def create_user(self, email: str, password: str, name: str):
        """Create a confirmed account through the server-only Auth Admin API."""
        response = self.client.auth.admin.create_user({
            'email': email,
            'password': password,
            'email_confirm': True,
            'user_metadata': {'name': name},
        })
        user = getattr(response, 'user', None)
        if not user:
            raise RuntimeError('Supabase Auth não retornou a conta criada.')
        return user

    def find_user_by_email(self, email: str):
        """Find one existing Auth identity so interrupted provisioning can be resumed."""
        normalized_email = str(email or '').strip().lower()
        matches = []
        per_page = 100
        for page in range(1, 101):
            users = self.client.auth.admin.list_users(page=page, per_page=per_page)
            matches.extend(
                user for user in users
                if str(getattr(user, 'email', '') or '').strip().lower() == normalized_email
            )
            if len(matches) > 1 or len(users) < per_page:
                break
        if len(matches) > 1:
            raise RuntimeError('Mais de uma identidade Auth corresponde ao e-mail informado.')
        return matches[0] if matches else None

    def update_user(self, auth_user_id: str, attributes: Dict):
        response = self.client.auth.admin.update_user_by_id(auth_user_id, attributes)
        user = getattr(response, 'user', None)
        if not user:
            raise RuntimeError('Supabase Auth não confirmou a atualização da conta.')
        return user

    def delete_user(self, auth_user_id: str):
        self.client.auth.admin.delete_user(auth_user_id)

    def change_password(self, email: str, current_password: str, new_password: str):
        client = create_client(self.supabase_url, self.supabase_key)
        signed_in = client.auth.sign_in_with_password({
            'email': email,
            'password': current_password,
        })
        if not getattr(signed_in, 'user', None):
            raise ValueError('A senha atual está incorreta.')
        client.auth.update_user({'password': new_password})

    def sign_up(self, email: str, password: str, user_metadata: Optional[Dict] = None) -> Optional[Dict]:
        """
        Sign up a new user with email and password
        """
        try:
            response = self.client.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": user_metadata or {}
                }
            })
            
            user = response.user
            return {
                'id': user.id,
                'email': user.email,
                'user_metadata': user.user_metadata,
                'app_metadata': user.app_metadata
            }
        except Exception as e:
            print(f"Sign up failed: {e}")
            return None

    def get_user(self, access_token: str):
        """
        Get user info from access token
        """
        try:
            user = self.client.auth.get_user(access_token).user
            return {
                'id': user.id,
                'email': user.email,
                'user_metadata': user.user_metadata,
                'app_metadata': user.app_metadata
            }
        except Exception as e:
            print(f"Failed to get user: {e}")
            return None

    def sign_out(self, access_token: str):
        """
        Sign out user
        """
        try:
            self.client.auth.sign_out(access_token)
            return True
        except Exception as e:
            print(f"Sign out failed: {e}")
            return False


# Global instance of the Supabase auth service
supabase_auth = SupabaseAuthService()

