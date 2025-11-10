"""
Authorization Server for MCP Split Demo.

This server handles OAuth flows, client registration, and token issuance.
Can be replaced with enterprise authorization servers like Auth0, Entra ID, etc.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.

"""

import asyncio
import logging
import secrets
import time

import click
from pydantic import AnyHttpUrl, BaseModel
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from uvicorn import Config, Server

from mcp.server.auth.routes import cors_middleware, create_auth_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull

from .firestore_auth_provider import FirestoreOAuthProvider
from .simple_auth_provider import SimpleAuthSettings, SimpleOAuthProvider as InMemoryOAuthProvider

logger = logging.getLogger(__name__)


class AuthServerSettings(BaseModel):
    """Settings for the Authorization Server."""

    # Server settings
    host: str = "localhost"
    port: int = 9000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_callback_path: str = "http://localhost:9000/login/callback"


def create_authorization_server(server_settings: AuthServerSettings, auth_settings: SimpleAuthSettings, use_firestore: bool = True) -> Starlette:
    """Create the Authorization Server application."""

    # Try to use Firestore if requested, fall back to in-memory if not available
    if use_firestore:
        try:
            logger.info("Attempting to initialize Firestore OAuth provider...")
            oauth_provider = FirestoreOAuthProvider(
                auth_settings, server_settings.auth_callback_path, str(server_settings.server_url)
            )
            logger.info("✅ Using Firestore for OAuth state persistence")
        except Exception as e:
            logger.warning(f"Failed to initialize Firestore: {e}")
            logger.info("⚠️  Falling back to in-memory OAuth provider (state will not persist across restarts)")
            oauth_provider = InMemoryOAuthProvider(
                auth_settings, server_settings.auth_callback_path, str(server_settings.server_url)
            )
    else:
        logger.info("Using in-memory OAuth provider (state will not persist across restarts)")
        oauth_provider = InMemoryOAuthProvider(
            auth_settings, server_settings.auth_callback_path, str(server_settings.server_url)
        )

    mcp_auth_settings = AuthSettings(
        issuer_url=server_settings.server_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[auth_settings.mcp_scope],
            default_scopes=[auth_settings.mcp_scope],
        ),
        required_scopes=[auth_settings.mcp_scope],
        resource_server_url=None,
    )

    # Create OAuth routes
    routes = create_auth_routes(
        provider=oauth_provider,
        issuer_url=mcp_auth_settings.issuer_url,
        service_documentation_url=mcp_auth_settings.service_documentation_url,
        client_registration_options=mcp_auth_settings.client_registration_options,
        revocation_options=mcp_auth_settings.revocation_options,
    )

    # Add login page route (GET)
    async def login_page_handler(request: Request) -> Response:
        """Show login form."""
        state = request.query_params.get("state")
        if not state:
            raise HTTPException(400, "Missing state parameter")
        return await oauth_provider.get_login_page(state)

    routes.append(Route("/login", endpoint=login_page_handler, methods=["GET"]))

    # Add login callback route (POST)
    async def login_callback_handler(request: Request) -> Response:
        """Handle simple authentication callback."""
        return await oauth_provider.handle_login_callback(request)

    routes.append(Route("/login/callback", endpoint=login_callback_handler, methods=["POST"]))

    # Add token introspection endpoint (RFC 7662) for Resource Servers
    async def introspect_handler(request: Request) -> Response:
        """
        Token introspection endpoint for Resource Servers.

        Resource Servers call this endpoint to validate tokens without
        needing direct access to token storage.
        """
        form = await request.form()
        token = form.get("token")
        if not token or not isinstance(token, str):
            return JSONResponse({"active": False}, status_code=400)

        # Look up token in provider
        access_token = await oauth_provider.load_access_token(token)
        if not access_token:
            return JSONResponse({"active": False})

        return JSONResponse(
            {
                "active": True,
                "client_id": access_token.client_id,
                "scope": " ".join(access_token.scopes),
                "exp": access_token.expires_at,
                "iat": int(time.time()),
                "token_type": "Bearer",
                "aud": access_token.resource,  # RFC 8707 audience claim
            }
        )

    routes.append(
        Route(
            "/introspect",
            endpoint=cors_middleware(introspect_handler, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        )
    )

    # Add custom token endpoint to handle client_credentials and JWT bearer grants
    # Note: The MCP SDK's /token endpoint handles authorization_code flow
    # We intercept here to also handle client_credentials and jwt-bearer grants
    async def custom_token_handler(request: Request) -> Response:
        """
        Custom token endpoint that handles multiple grant types.

        Supports:
        - authorization_code (delegated to MCP SDK's default handler)
        - client_credentials (RFC 6749 Section 4.4)
        - urn:ietf:params:oauth:grant-type:jwt-bearer (RFC 7523)
        """
        form = await request.form()
        grant_type = form.get("grant_type")

        # Handle client_credentials grant
        if grant_type == "client_credentials":
            client_id = form.get("client_id")
            client_secret = form.get("client_secret")
            scope = form.get("scope", "")

            if not client_id or not isinstance(client_id, str):
                return JSONResponse({"error": "invalid_request", "error_description": "Missing client_id"}, status_code=400)

            # Get client
            client = await oauth_provider.get_client(client_id)
            if not client:
                return JSONResponse(
                    {"error": "invalid_client", "error_description": "Unknown client"}, status_code=401
                )

            # Validate client_secret
            if client.client_secret != client_secret:
                return JSONResponse(
                    {"error": "invalid_client", "error_description": "Invalid client credentials"}, status_code=401
                )

            # Parse scopes
            scopes = scope.split() if scope else []

            try:
                token = await oauth_provider.exchange_client_credentials(client, scopes)
                return JSONResponse(
                    {
                        "access_token": token.access_token,
                        "token_type": token.token_type,
                        "expires_in": token.expires_in,
                        "scope": token.scope,
                    }
                )
            except ValueError as e:
                return JSONResponse({"error": "invalid_scope", "error_description": str(e)}, status_code=400)

        # Handle JWT Bearer grant
        elif grant_type == "urn:ietf:params:oauth:grant-type:jwt-bearer":
            assertion = form.get("assertion")
            scope = form.get("scope", "")

            if not assertion or not isinstance(assertion, str):
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "Missing assertion"}, status_code=400
                )

            # Parse scopes
            scopes = scope.split() if scope else []

            try:
                token = await oauth_provider.exchange_jwt_bearer(assertion, scopes)
                return JSONResponse(
                    {
                        "access_token": token.access_token,
                        "token_type": token.token_type,
                        "expires_in": token.expires_in,
                        "scope": token.scope,
                    }
                )
            except ValueError as e:
                logger.error(f"JWT Bearer grant error: {e}")
                return JSONResponse({"error": "invalid_grant", "error_description": str(e)}, status_code=400)
            except Exception as e:
                logger.error(f"Unexpected JWT Bearer grant error: {e}", exc_info=True)
                return JSONResponse({"error": "invalid_grant", "error_description": str(e)}, status_code=400)

        else:
            # For other grant types (like authorization_code), return error
            # The MCP SDK's token endpoint will handle authorization_code separately
            return JSONResponse(
                {
                    "error": "unsupported_grant_type",
                    "error_description": f"Grant type {grant_type} not supported by this endpoint. Use /token for authorization_code.",
                },
                status_code=400,
            )

    # Add the custom token endpoint for new grant types
    routes.append(
        Route(
            "/token/custom",
            endpoint=cors_middleware(custom_token_handler, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        )
    )

    # Add custom registration endpoint for service accounts (client_credentials and JWT bearer)
    async def register_service_account_handler(request: Request) -> Response:
        """
        Register a service account client that can use client_credentials or JWT bearer grants.

        POST /register/service_account
        {
          "client_name": "My Service Account",
          "grant_types": ["client_credentials"] or ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
          "scope": "user"
        }

        Note: token_endpoint_auth_method is automatically set based on grant type:
        - JWT bearer grants use "none" (auth via JWT assertion)
        - Client credentials use "client_secret_post"
        """
        try:
            data = await request.json()
            client_name = data.get("client_name")
            grant_types = data.get("grant_types", [])
            scope = data.get("scope", "")
            token_endpoint_auth_method = data.get("token_endpoint_auth_method", "client_secret_post")

            if not client_name:
                return JSONResponse({"error": "Missing client_name"}, status_code=400)

            # Validate grant types
            valid_grant_types = ["client_credentials", "urn:ietf:params:oauth:grant-type:jwt-bearer"]
            if not grant_types or not all(gt in valid_grant_types for gt in grant_types):
                return JSONResponse(
                    {"error": f"Invalid grant_types. Must be one of: {valid_grant_types}"},
                    status_code=400
                )

            # Determine auth method - JWT bearer uses 'none' since auth is via JWT assertion
            # Only 'none' and 'client_secret_post' are supported by MCP SDK
            if "urn:ietf:params:oauth:grant-type:jwt-bearer" in grant_types:
                auth_method = "none"
            else:
                auth_method = "client_secret_post"

            # Generate client credentials
            client_id = secrets.token_urlsafe(16)
            client_secret = secrets.token_urlsafe(32) if auth_method == "client_secret_post" else None

            # Create OAuthClientInformationFull object
            client_info = OAuthClientInformationFull(
                client_id=client_id,
                client_secret=client_secret,
                client_name=client_name,
                redirect_uris=["http://localhost"],  # Required by schema but unused for service accounts
                grant_types=grant_types,
                response_types=["code"] if "authorization_code" in grant_types else [],
                scope=scope,
                token_endpoint_auth_method=auth_method,
                client_id_issued_at=int(time.time()),
                client_secret_expires_at=0,  # Never expires
            )

            # Register the client
            await oauth_provider.register_client(client_info)

            response_data = {
                "client_id": client_info.client_id,
                "client_name": client_info.client_name,
                "grant_types": client_info.grant_types,
                "scope": scope,
            }

            # Include client_secret for client_credentials flow
            if "client_credentials" in grant_types:
                response_data["client_secret"] = client_info.client_secret

            return JSONResponse(response_data)

        except Exception as e:
            logger.error(f"Error registering service account: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    routes.append(Route("/register/service_account", endpoint=register_service_account_handler, methods=["POST"]))

    # Add endpoint for registering client public keys (for JWT Bearer Grant)
    async def register_public_key_handler(request: Request) -> Response:
        """
        Register a public key for a client (for JWT Bearer Grant validation).

        POST /register_public_key
        {
          "client_id": "my-service",
          "public_key": "-----BEGIN PUBLIC KEY-----\\n..."
        }
        """
        try:
            data = await request.json()
            client_id = data.get("client_id")
            public_key = data.get("public_key")

            if not client_id or not public_key:
                return JSONResponse({"error": "Missing client_id or public_key"}, status_code=400)

            # Verify client exists
            client = await oauth_provider.get_client(client_id)
            if not client:
                return JSONResponse({"error": "Unknown client"}, status_code=404)

            await oauth_provider.register_client_public_key(client_id, public_key)

            return JSONResponse({"status": "success", "message": f"Public key registered for {client_id}"})

        except Exception as e:
            logger.error(f"Error registering public key: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    routes.append(Route("/register_public_key", endpoint=register_public_key_handler, methods=["POST"]))

    # Add health check endpoint for Cloud Run
    async def health_check_handler(request: Request) -> Response:
        """Health check endpoint for Cloud Run and other platforms."""
        return JSONResponse({"status": "healthy"})

    routes.append(Route("/health", endpoint=health_check_handler, methods=["GET"]))

    # Add cleanup endpoint for expired data (optional manual trigger)
    async def cleanup_handler(request: Request) -> Response:
        """Manually trigger cleanup of expired tokens and auth codes."""
        results = await oauth_provider.cleanup_expired_data()
        return JSONResponse(
            {
                "status": "success",
                "cleaned_up": results,
            }
        )

    routes.append(Route("/cleanup", endpoint=cleanup_handler, methods=["POST"]))

    return Starlette(routes=routes)


async def run_server(server_settings: AuthServerSettings, auth_settings: SimpleAuthSettings, use_firestore: bool = True):
    """Run the Authorization Server."""
    auth_server = create_authorization_server(server_settings, auth_settings, use_firestore)

    config = Config(
        auth_server,
        host=server_settings.host,
        port=server_settings.port,
        log_level="info",
    )
    server = Server(config)

    logger.info(f"🚀 MCP Authorization Server running on {server_settings.server_url}")

    await server.serve()


@click.command()
@click.option("--port", default=9000, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option("--issuer-url", default=None, help="Public issuer URL (required for HTTPS)")
@click.option("--no-firestore", is_flag=True, help="Disable Firestore persistence (use in-memory storage)")
def main(port: int, host: str, issuer_url: str | None, no_firestore: bool) -> int:
    """
    Run the MCP Authorization Server.

    This server handles OAuth flows and can be used by multiple Resource Servers.

    Uses simple hardcoded credentials for demo purposes.
    """
    import os

    logging.basicConfig(level=logging.INFO)

    # Allow Cloud Run to override port via PORT env var
    port = int(os.environ.get("PORT", port))

    # Get issuer URL from env var or CLI option
    # For Cloud Run deployments, this should be the public HTTPS URL
    issuer_url = os.environ.get("ISSUER_URL", issuer_url)
    if not issuer_url:
        # Default to local development URL
        issuer_url = f"http://{host}:{port}"

    # Load simple auth settings
    auth_settings = SimpleAuthSettings()

    # Create server settings
    server_settings = AuthServerSettings(
        host=host,
        port=port,
        server_url=AnyHttpUrl(issuer_url),
        auth_callback_path=f"{issuer_url}/login",
    )

    # Determine if we should use Firestore
    use_firestore = not no_firestore

    asyncio.run(run_server(server_settings, auth_settings, use_firestore))
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]


