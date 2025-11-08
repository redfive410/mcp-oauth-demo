"""
Firestore client for OAuth provider persistence.

This module provides Firestore collections and helper functions for storing
OAuth state across CloudRun instance restarts.

Collections:
- oauth_clients: OAuth client registrations (DCR)
- oauth_tokens: Access tokens
- auth_codes: Authorization codes
- oauth_state: OAuth flow state mapping
- user_data: User session data
"""

import logging
import os
import time
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Firestore client for OAuth provider."""

    def __init__(self, project_id: str | None = None):
        """
        Initialize Firestore client.

        Args:
            project_id: GCP project ID. If None, uses default credentials.
        """
        self.db = firestore.Client(project=project_id)
        self.clients = self.db.collection("oauth_clients")
        self.tokens = self.db.collection("oauth_tokens")
        self.auth_codes = self.db.collection("auth_codes")
        self.oauth_state = self.db.collection("oauth_state")
        self.user_data = self.db.collection("user_data")

    # Client operations
    async def get_client(self, client_id: str) -> dict[str, Any] | None:
        """Get OAuth client by ID."""
        doc = self.clients.document(client_id).get()
        return doc.to_dict() if doc.exists else None

    async def set_client(self, client_id: str, client_data: dict[str, Any]) -> None:
        """Store OAuth client."""
        self.clients.document(client_id).set(client_data)

    # Token operations
    async def get_token(self, token: str) -> dict[str, Any] | None:
        """Get access token and check expiration."""
        doc = self.tokens.document(token).get()
        if not doc.exists:
            return None

        token_data = doc.to_dict()
        # Check if expired
        if token_data and token_data.get("expires_at", 0) < time.time():
            # Delete expired token
            self.tokens.document(token).delete()
            return None

        return token_data

    async def set_token(self, token: str, token_data: dict[str, Any]) -> None:
        """Store access token."""
        self.tokens.document(token).set(token_data)

    async def delete_token(self, token: str) -> None:
        """Delete access token."""
        self.tokens.document(token).delete()

    # Authorization code operations
    async def get_auth_code(self, code: str) -> dict[str, Any] | None:
        """Get authorization code and check expiration."""
        doc = self.auth_codes.document(code).get()
        if not doc.exists:
            return None

        code_data = doc.to_dict()
        # Check if expired
        if code_data and code_data.get("expires_at", 0) < time.time():
            # Delete expired code
            self.auth_codes.document(code).delete()
            return None

        return code_data

    async def set_auth_code(self, code: str, code_data: dict[str, Any]) -> None:
        """Store authorization code."""
        self.auth_codes.document(code).set(code_data)

    async def delete_auth_code(self, code: str) -> None:
        """Delete authorization code."""
        self.auth_codes.document(code).delete()

    # OAuth state operations
    async def get_state(self, state: str) -> dict[str, Any] | None:
        """Get OAuth state mapping."""
        doc = self.oauth_state.document(state).get()
        return doc.to_dict() if doc.exists else None

    async def set_state(self, state: str, state_data: dict[str, Any]) -> None:
        """Store OAuth state mapping."""
        self.oauth_state.document(state).set(state_data)

    async def delete_state(self, state: str) -> None:
        """Delete OAuth state mapping."""
        self.oauth_state.document(state).delete()

    # User data operations
    async def get_user_data(self, key: str) -> dict[str, Any] | None:
        """Get user data by key (username or token)."""
        doc = self.user_data.document(key).get()
        return doc.to_dict() if doc.exists else None

    async def set_user_data(self, key: str, data: dict[str, Any]) -> None:
        """Store user data."""
        self.user_data.document(key).set(data)

    # Cleanup operations
    async def cleanup_expired_tokens(self) -> int:
        """Delete all expired tokens. Returns count of deleted tokens."""
        now = time.time()
        expired_tokens = self.tokens.where(filter=FieldFilter("expires_at", "<", now)).stream()

        count = 0
        for doc in expired_tokens:
            doc.reference.delete()
            count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired tokens")

        return count

    async def cleanup_expired_auth_codes(self) -> int:
        """Delete all expired authorization codes. Returns count of deleted codes."""
        now = time.time()
        expired_codes = self.auth_codes.where(filter=FieldFilter("expires_at", "<", now)).stream()

        count = 0
        for doc in expired_codes:
            doc.reference.delete()
            count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired auth codes")

        return count


def get_firestore_client() -> FirestoreClient:
    """
    Get Firestore client singleton.

    Uses GCP_PROJECT_ID environment variable if set, otherwise uses default credentials.
    """
    project_id = os.environ.get("GCP_PROJECT_ID")
    return FirestoreClient(project_id=project_id)
