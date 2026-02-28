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
            response = self.client.auth.sign_in_with_password({
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

