"""
Simple OAuth provider for MCP servers.

This module contains a basic OAuth implementation using hardcoded user credentials
for demonstration purposes. No external authentication provider is required.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.

"""

import logging
import secrets
import time
from typing import Any

import jwt
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)


class SimpleAuthSettings(BaseSettings):
    """Simple OAuth settings for demo purposes."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    # Demo user credentials
    demo_username: str = "demo_user"
    demo_password: str = "demo_password"

    # MCP OAuth scope
    mcp_scope: str = "user"


class SimpleOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """
    Simple OAuth provider for demo purposes.

    This provider handles the OAuth flow by:
    1. Providing a simple login form for demo credentials
    2. Issuing MCP tokens after successful authentication
    3. Maintaining token state for introspection
    """

    def __init__(self, settings: SimpleAuthSettings, auth_callback_url: str, server_url: str):
        self.settings = settings
        self.auth_callback_url = auth_callback_url
        self.server_url = server_url
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.state_mapping: dict[str, dict[str, str | None]] = {}
        # Store authenticated user information
        self.user_data: dict[str, dict[str, Any]] = {}
        # Store client public keys for JWT Bearer Grant validation
        self.client_public_keys: dict[str, str] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get OAuth client information."""
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        """Register a new OAuth client."""
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Generate an authorization URL for simple login flow."""
        state = params.state or secrets.token_hex(16)

        # Store state mapping for callback
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
            "resource": params.resource,  # RFC 8707
        }

        # Build simple login URL that points to login page
        auth_url = f"{self.auth_callback_url}?state={state}&client_id={client.client_id}"

        return auth_url

    async def get_login_page(self, state: str) -> HTMLResponse:
        """Generate login page HTML for the given state."""
        if not state:
            raise HTTPException(400, "Missing state parameter")

        # Create simple login form HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MCP Demo Authentication</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; }}
                .form-group {{ margin-bottom: 15px; }}
                input {{ width: 100%; padding: 8px; margin-top: 5px; }}
                button {{ background-color: #4CAF50; color: white; padding: 10px 15px; border: none; cursor: pointer; }}
            </style>
        </head>
        <body>
            <h2>MCP Demo Authentication</h2>
            <p>This is a simplified authentication demo. Use the demo credentials below:</p>
            <p><strong>Username:</strong> demo_user<br>
            <strong>Password:</strong> demo_password</p>

            <form action="{self.server_url.rstrip("/")}/login/callback" method="post">
                <input type="hidden" name="state" value="{state}">
                <div class="form-group">
                    <label>Username:</label>
                    <input type="text" name="username" value="demo_user" required>
                </div>
                <div class="form-group">
                    <label>Password:</label>
                    <input type="password" name="password" value="demo_password" required>
                </div>
                <button type="submit">Sign In</button>
            </form>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    async def handle_login_callback(self, request: Request) -> Response:
        """Handle login form submission callback."""
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        state = form.get("state")

        if not username or not password or not state:
            raise HTTPException(400, "Missing username, password, or state parameter")

        # Ensure we have strings, not UploadFile objects
        if not isinstance(username, str) or not isinstance(password, str) or not isinstance(state, str):
            raise HTTPException(400, "Invalid parameter types")

        redirect_uri = await self.handle_simple_callback(username, password, state)
        return RedirectResponse(url=redirect_uri, status_code=302)

    async def handle_simple_callback(self, username: str, password: str, state: str) -> str:
        """Handle simple authentication callback and return redirect URI."""
        state_data = self.state_mapping.get(state)
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
        self.auth_codes[new_code] = auth_code

        # Store user data
        self.user_data[username] = {
            "username": username,
            "user_id": f"user_{secrets.token_hex(8)}",
            "authenticated_at": time.time(),
        }

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=new_code, state=state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load an authorization code."""
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        if authorization_code.code not in self.auth_codes:
            raise ValueError("Invalid authorization code")

        # Generate MCP access token
        mcp_token = f"mcp_{secrets.token_hex(32)}"

        # Store MCP token
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 3600,
            resource=authorization_code.resource,  # RFC 8707
        )

        # Store user data mapping for this token
        self.user_data[mcp_token] = {
            "username": self.settings.demo_username,
            "user_id": f"user_{secrets.token_hex(8)}",
            "authenticated_at": time.time(),
        }

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=mcp_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load and validate an access token."""
        access_token = self.tokens.get(token)
        if not access_token:
            return None

        # Check if expired
        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            return None

        return access_token

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        """Load a refresh token - not supported in this example."""
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token - not supported in this example."""
        raise NotImplementedError("Refresh tokens not supported")

    # TODO(Marcelo): The type hint is wrong. We need to fix, and test to check if it works.
    async def revoke_token(self, token: str, token_type_hint: str | None = None) -> None:  # type: ignore
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]

    # Client Credentials Flow (RFC 6749 Section 4.4)
    async def exchange_client_credentials(
        self,
        client: OAuthClientInformationFull,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Exchange client credentials for access token.
        Used for machine-to-machine authentication.

        Args:
            client: The OAuth client making the request
            scopes: Requested scopes

        Returns:
            Access token for the service account
        """
        if not client.client_id:
            raise ValueError("No client_id provided")

        # Validate client has permission for requested scopes
        client_scopes = set(client.scope.split()) if client.scope else set()
        allowed_scopes = set(scopes) & client_scopes

        if not allowed_scopes:
            raise ValueError(f"Client not authorized for requested scopes: {scopes}")

        # Generate service account token
        service_token = f"mcp_service_{secrets.token_hex(32)}"

        # Store token
        self.tokens[service_token] = AccessToken(
            token=service_token,
            client_id=client.client_id,
            scopes=list(allowed_scopes),
            expires_at=int(time.time()) + 3600,  # 1 hour
            resource=None,
        )

        # Store service account user data
        self.user_data[service_token] = {
            "client_id": client.client_id,
            "user_id": f"service_account_{client.client_id}",
            "authenticated_at": time.time(),
            "auth_method": "client_credentials",
        }

        logger.info(f"Issued client credentials token for {client.client_id} with scopes {allowed_scopes}")

        return OAuthToken(
            access_token=service_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(allowed_scopes),
        )

    # JWT Bearer Grant (RFC 7523)
    async def exchange_jwt_bearer(
        self,
        assertion: str,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Exchange JWT Bearer assertion for access token.
        Used for machine-to-machine authentication with asymmetric keys.

        Args:
            assertion: The JWT assertion signed by the client's private key
            scopes: Requested scopes

        Returns:
            Access token for the service account
        """
        try:
            # Decode JWT header to get the client_id (from 'iss' claim)
            unverified_claims = jwt.decode(assertion, options={"verify_signature": False})
            client_id = unverified_claims.get("iss")

            if not client_id:
                raise ValueError("JWT missing 'iss' (issuer) claim")

            # Get client information
            client = await self.get_client(client_id)
            if not client:
                raise ValueError(f"Unknown client: {client_id}")

            # Get client's public key
            public_key = self.client_public_keys.get(client_id)
            if not public_key:
                raise ValueError(f"No public key registered for client: {client_id}")

            # Verify JWT signature and claims
            # Normalize server_url (strip trailing slash) for audience comparison
            normalized_server_url = self.server_url.rstrip("/")
            claims = jwt.decode(
                assertion,
                public_key,
                algorithms=["RS256", "ES256"],
                audience=normalized_server_url,
                options={
                    "require": ["iss", "sub", "aud", "exp"],
                },
            )

            # Validate claims
            if claims["iss"] != client_id:
                raise ValueError("JWT 'iss' claim doesn't match client_id")

            if claims["sub"] != client_id:
                raise ValueError("JWT 'sub' claim doesn't match client_id")

            # Validate client has permission for requested scopes
            client_scopes = set(client.scope.split()) if client.scope else set()
            allowed_scopes = set(scopes) & client_scopes

            if not allowed_scopes:
                raise ValueError(f"Client not authorized for requested scopes: {scopes}")

            # Generate service account token
            service_token = f"mcp_jwt_{secrets.token_hex(32)}"

            # Store token
            self.tokens[service_token] = AccessToken(
                token=service_token,
                client_id=client.client_id,
                scopes=list(allowed_scopes),
                expires_at=int(time.time()) + 3600,  # 1 hour
                resource=None,
            )

            # Store service account user data
            self.user_data[service_token] = {
                "client_id": client.client_id,
                "user_id": f"service_account_{client.client_id}",
                "authenticated_at": time.time(),
                "auth_method": "jwt_bearer",
            }

            logger.info(f"Issued JWT bearer token for {client.client_id} with scopes {allowed_scopes}")

            return OAuthToken(
                access_token=service_token,
                token_type="Bearer",
                expires_in=3600,
                scope=" ".join(allowed_scopes),
            )

        except jwt.ExpiredSignatureError:
            raise ValueError("JWT has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid JWT: {e}")

    async def register_client_public_key(self, client_id: str, public_key_pem: str) -> None:
        """
        Register a public key for a client (for JWT Bearer Grant validation).

        Args:
            client_id: The client ID
            public_key_pem: The public key in PEM format
        """
        self.client_public_keys[client_id] = public_key_pem
        logger.info(f"Registered public key for client {client_id}")

