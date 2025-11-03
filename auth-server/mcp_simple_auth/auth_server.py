"""
Authorization Server for MCP Split Demo.

This server handles OAuth flows, client registration, and token issuance.
Can be replaced with enterprise authorization servers like Auth0, Entra ID, etc.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.

"""

import asyncio
import logging
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

from .firestore_auth_provider import FirestoreOAuthProvider
from .simple_auth_provider import SimpleAuthSettings

logger = logging.getLogger(__name__)


class AuthServerSettings(BaseModel):
    """Settings for the Authorization Server."""

    # Server settings
    host: str = "localhost"
    port: int = 9000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_callback_path: str = "http://localhost:9000/login/callback"


class SimpleAuthProvider(FirestoreOAuthProvider):
    """
    Authorization Server provider with Firestore persistence.

    This provider:
    1. Issues MCP tokens after simple credential authentication
    2. Stores token state in Firestore for persistence across restarts
    3. Provides introspection endpoint for Resource Servers
    """

    def __init__(self, auth_settings: SimpleAuthSettings, auth_callback_path: str, server_url: str):
        super().__init__(auth_settings, auth_callback_path, server_url)


def create_authorization_server(server_settings: AuthServerSettings, auth_settings: SimpleAuthSettings) -> Starlette:
    """Create the Authorization Server application."""
    oauth_provider = SimpleAuthProvider(
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


async def run_server(server_settings: AuthServerSettings, auth_settings: SimpleAuthSettings):
    """Run the Authorization Server."""
    auth_server = create_authorization_server(server_settings, auth_settings)

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
def main(port: int, host: str, issuer_url: str | None) -> int:
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

    asyncio.run(run_server(server_settings, auth_settings))
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]


