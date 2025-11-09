"""
Firestore-backed OAuth provider for MCP servers.

This module extends SimpleOAuthProvider to persist all OAuth state in Firestore,
allowing the Authorization Server to survive CloudRun instance restarts.
"""

import logging
import secrets
import time
from typing import Any

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .firestore_client import FirestoreClient, get_firestore_client
from .simple_auth_provider import SimpleAuthSettings, SimpleOAuthProvider

logger = logging.getLogger(__name__)


class FirestoreOAuthProvider(SimpleOAuthProvider):
    """
    OAuth provider with Firestore persistence.

    Extends SimpleOAuthProvider to store all state in Firestore instead of in-memory
    dictionaries. This allows the server to survive CloudRun instance restarts.

    All OAuth state is persisted:
    - OAuth clients (DCR registrations)
    - Access tokens
    - Authorization codes
    - OAuth flow state
    - User session data
    """

    def __init__(
        self,
        settings: SimpleAuthSettings,
        auth_callback_url: str,
        server_url: str,
        firestore_client: FirestoreClient | None = None,
    ):
        """
        Initialize Firestore OAuth provider.

        Args:
            settings: OAuth settings
            auth_callback_url: URL for auth callback
            server_url: Server base URL
            firestore_client: Optional Firestore client (for testing)
        """
        super().__init__(settings, auth_callback_url, server_url)

        # Initialize Firestore client
        self.firestore = firestore_client or get_firestore_client()

        logger.info("Initialized FirestoreOAuthProvider with Firestore persistence")

    # Client operations - override to use Firestore
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get OAuth client information from Firestore."""
        client_data = await self.firestore.get_client(client_id)
        if not client_data:
            return None

        # Convert dict back to OAuthClientInformationFull
        return OAuthClientInformationFull(**client_data)

    async def register_client(self, client_info: OAuthClientInformationFull):
        """Register a new OAuth client in Firestore."""
        # Convert Pydantic model to dict for Firestore
        client_data = client_info.model_dump(mode="json")
        await self.firestore.set_client(client_info.client_id, client_data)
        logger.info(f"Registered client {client_info.client_id} in Firestore")

    # Authorization flow - override to use Firestore for state
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Generate an authorization URL and store state in Firestore."""
        state = params.state or secrets.token_hex(16)

        # Store state mapping in Firestore
        state_data = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
            "resource": params.resource,  # RFC 8707
        }
        await self.firestore.set_state(state, state_data)

        # Build simple login URL that points to login page
        auth_url = f"{self.auth_callback_url}?state={state}&client_id={client.client_id}"

        return auth_url

    async def handle_simple_callback(self, username: str, password: str, state: str) -> str:
        """Handle simple authentication callback using Firestore state."""
        # Load state from Firestore
        state_data = await self.firestore.get_state(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")

        redirect_uri = state_data["redirect_uri"]
        code_challenge = state_data["code_challenge"]
        redirect_uri_provided_explicitly = state_data["redirect_uri_provided_explicitly"] == "True"
        client_id = state_data["client_id"]
        resource = state_data.get("resource")  # RFC 8707

        # These are required values from our own state mapping
        assert redirect_uri is not None
        assert code_challenge is not None
        assert client_id is not None

        # Validate demo credentials
        if username != self.settings.demo_username or password != self.settings.demo_password:
            raise HTTPException(401, "Invalid credentials")

        # Create MCP authorization code
        new_code = f"mcp_{secrets.token_hex(16)}"
        auth_code = AuthorizationCode(
            code=new_code,
            client_id=client_id,
            redirect_uri=AnyHttpUrl(redirect_uri),
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            expires_at=time.time() + 300,
            scopes=[self.settings.mcp_scope],
            code_challenge=code_challenge,
            resource=resource,  # RFC 8707
        )

        # Store auth code in Firestore
        code_data = auth_code.model_dump(mode="json")
        await self.firestore.set_auth_code(new_code, code_data)

        # Store user data in Firestore
        user_data = {
            "username": username,
            "user_id": f"user_{secrets.token_hex(8)}",
            "authenticated_at": time.time(),
        }
        await self.firestore.set_user_data(username, user_data)

        # Delete used state from Firestore
        await self.firestore.delete_state(state)

        return construct_redirect_uri(redirect_uri, code=new_code, state=state)

    # Authorization code operations - override to use Firestore
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load an authorization code from Firestore."""
        code_data = await self.firestore.get_auth_code(authorization_code)
        if not code_data:
            return None

        # Convert dict back to AuthorizationCode
        return AuthorizationCode(**code_data)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens using Firestore."""
        # Verify code exists in Firestore
        code_data = await self.firestore.get_auth_code(authorization_code.code)
        if not code_data:
            raise ValueError("Invalid authorization code")

        # Generate MCP access token
        mcp_token = f"mcp_{secrets.token_hex(32)}"

        # Store MCP token in Firestore
        access_token = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 3600,
            resource=authorization_code.resource,  # RFC 8707
        )
        token_data = access_token.model_dump(mode="json")
        await self.firestore.set_token(mcp_token, token_data)

        # Store user data mapping for this token in Firestore
        user_data = {
            "username": self.settings.demo_username,
            "user_id": f"user_{secrets.token_hex(8)}",
            "authenticated_at": time.time(),
        }
        await self.firestore.set_user_data(mcp_token, user_data)

        # Delete used authorization code from Firestore
        await self.firestore.delete_auth_code(authorization_code.code)

        logger.info(f"Exchanged auth code for token {mcp_token[:20]}... (expires in 3600s)")

        return OAuthToken(
            access_token=mcp_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    # Token operations - override to use Firestore
    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load and validate an access token from Firestore."""
        token_data = await self.firestore.get_token(token)
        if not token_data:
            return None

        # Convert dict back to AccessToken
        return AccessToken(**token_data)

    async def revoke_token(self, token: str, token_type_hint: str | None = None) -> None:  # type: ignore
        """Revoke a token in Firestore."""
        await self.firestore.delete_token(token)
        logger.info(f"Revoked token {token[:20]}...")

    # Cleanup operations
    async def cleanup_expired_data(self) -> dict[str, int]:
        """
        Clean up expired tokens and auth codes from Firestore.

        Returns:
            Dictionary with counts of cleaned up items
        """
        tokens_cleaned = await self.firestore.cleanup_expired_tokens()
        codes_cleaned = await self.firestore.cleanup_expired_auth_codes()

        return {
            "tokens": tokens_cleaned,
            "auth_codes": codes_cleaned,
        }

    # Client Credentials Flow - override to use Firestore
    async def exchange_client_credentials(
        self,
        client: OAuthClientInformationFull,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Exchange client credentials for access token using Firestore.

        Args:
            client: The OAuth client making the request
            scopes: Requested scopes

        Returns:
            Access token for the service account
        """
        # Call parent implementation to generate token
        token = await super().exchange_client_credentials(client, scopes)

        # Token and user_data are already stored in parent's in-memory dicts
        # Now persist them to Firestore
        access_token = self.tokens[token.access_token]
        token_data = access_token.model_dump(mode="json")
        await self.firestore.set_token(token.access_token, token_data)

        user_data = self.user_data[token.access_token]
        await self.firestore.set_user_data(token.access_token, user_data)

        logger.info(f"Stored client credentials token in Firestore for {client.client_id}")

        return token

    # JWT Bearer Grant - override to use Firestore for public key storage
    async def register_client_public_key(self, client_id: str, public_key_pem: str) -> None:
        """
        Register a public key for a client in Firestore.

        Args:
            client_id: The client ID
            public_key_pem: The public key in PEM format
        """
        # Store in parent's in-memory dict
        await super().register_client_public_key(client_id, public_key_pem)

        # Also persist to Firestore
        await self.firestore.set_public_key(client_id, public_key_pem)
        logger.info(f"Stored public key in Firestore for client {client_id}")

    async def exchange_jwt_bearer(
        self,
        assertion: str,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Exchange JWT Bearer assertion for access token using Firestore.

        Args:
            assertion: The JWT assertion signed by the client's private key
            scopes: Requested scopes

        Returns:
            Access token for the service account
        """
        # First, load public key from Firestore if not in memory
        import jwt as jwt_lib

        # Decode without verification to get client_id
        unverified_claims = jwt_lib.decode(assertion, options={"verify_signature": False})
        client_id = unverified_claims.get("iss")

        if client_id and client_id not in self.client_public_keys:
            # Try to load from Firestore
            public_key = await self.firestore.get_public_key(client_id)
            if public_key:
                self.client_public_keys[client_id] = public_key
                logger.info(f"Loaded public key from Firestore for client {client_id}")

        # Call parent implementation to validate JWT and generate token
        token = await super().exchange_jwt_bearer(assertion, scopes)

        # Token and user_data are already stored in parent's in-memory dicts
        # Now persist them to Firestore
        access_token = self.tokens[token.access_token]
        token_data = access_token.model_dump(mode="json")
        await self.firestore.set_token(token.access_token, token_data)

        user_data = self.user_data[token.access_token]
        await self.firestore.set_user_data(token.access_token, user_data)

        logger.info(f"Stored JWT bearer token in Firestore for client {client_id}")

        return token
