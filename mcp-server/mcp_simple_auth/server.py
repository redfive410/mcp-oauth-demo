"""
MCP Resource Server with Token Introspection.

This server validates tokens via Authorization Server introspection and serves MCP resources.
Demonstrates RFC 9728 Protected Resource Metadata for AS/RS separation.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.
"""

import datetime
import logging
import random
from typing import Any, Literal

import click
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP

from .token_verifier import IntrospectionTokenVerifier

logger = logging.getLogger(__name__)


class ResourceServerSettings(BaseSettings):
    """Settings for the MCP Resource Server."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESOURCE_")

    # Server settings
    host: str = "localhost"
    port: int = 8001
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001/mcp")

    # Authorization Server settings
    auth_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_server_introspection_endpoint: str = "http://localhost:9000/introspect"
    # No user endpoint needed - we get user data from token introspection

    # MCP settings
    mcp_scope: str = "user"

    # RFC 8707 resource validation
    oauth_strict: bool = False

    # TODO(Marcelo): Is this even needed? I didn't have time to check.
    def __init__(self, **data: Any):
        """Initialize settings with values from environment variables."""
        super().__init__(**data)


def create_resource_server(settings: ResourceServerSettings) -> FastMCP:
    """
    Create MCP Resource Server with token introspection.

    This server:
    1. Provides protected resource metadata (RFC 9728)
    2. Validates tokens via Authorization Server introspection
    3. Serves MCP tools and resources
    """
    # Create token verifier for introspection with RFC 8707 resource validation
    token_verifier = IntrospectionTokenVerifier(
        introspection_endpoint=settings.auth_server_introspection_endpoint,
        server_url=str(settings.server_url),
        validate_resource=settings.oauth_strict,  # Only validate when --oauth-strict is set
    )

    # Create FastMCP server as a Resource Server
    app = FastMCP(
        name="MCP Resource Server",
        instructions="Resource Server that validates tokens via Authorization Server introspection",
        host=settings.host,
        port=settings.port,
        debug=True,
        # Auth configuration for RS mode
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=settings.auth_server_url,
            required_scopes=[settings.mcp_scope],
            resource_server_url=settings.server_url,
        ),
    )

    @app.tool()
    async def get_time() -> dict[str, Any]:
        """
        Get the current server time.

        This tool demonstrates that system information can be protected
        by OAuth authentication. User must be authenticated to access it.
        """

        now = datetime.datetime.now()

        return {
            "current_time": now.isoformat(),
            "timezone": "UTC",  # Simplified for demo
            "timestamp": now.timestamp(),
            "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @app.tool()
    async def get_dinner_idea(user_context: str = "") -> dict[str, Any]:
        """
        Gets a dinner idea based on context.

        This tool demonstrates that system information can be protected
        by OAuth authentication. User must be authenticated to access it.

        Args:
            user_context: Optional context about user preferences, income, etc.
        """
        dinner = random.choice(['Pizza', 'Sandwich', 'Tacos'])

        return {
            "prediction": dinner,
            "user_context": user_context,
        }

    return app

@click.command()
@click.option("--port", default=8001, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option("--auth-server", default="http://localhost:9000", help="Authorization Server URL")
@click.option("--server-url", default=None, help="Public server URL (required for HTTPS)")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
@click.option(
    "--oauth-strict",
    is_flag=True,
    help="Enable RFC 8707 resource validation",
)
def main(port: int, host: str, auth_server: str, server_url: str | None, transport: Literal["sse", "streamable-http"], oauth_strict: bool) -> int:
    """
    Run the MCP Resource Server.

    This server:
    - Provides RFC 9728 Protected Resource Metadata
    - Validates tokens via Authorization Server introspection
    - Serves MCP tools requiring authentication

    Must be used with a running Authorization Server.
    """
    import os

    logging.basicConfig(level=logging.INFO)

    # Allow Cloud Run to override port via PORT env var
    port = int(os.environ.get("PORT", port))

    # Get server URL from env var or CLI option
    # For Cloud Run deployments, this should be the public HTTPS URL
    server_url = os.environ.get("MCP_RESOURCE_SERVER_URL", server_url)
    if not server_url:
        # Default to local development URL
        server_url = f"http://{host}:{port}/mcp"

    # Get auth server URL from env var or CLI option
    auth_server = os.environ.get("MCP_RESOURCE_AUTH_SERVER_URL", auth_server)

    try:
        # Parse auth server URL
        auth_server_url = AnyHttpUrl(auth_server)

        # Create settings
        settings = ResourceServerSettings(
            host=host,
            port=port,
            server_url=AnyHttpUrl(server_url),
            auth_server_url=auth_server_url,
            auth_server_introspection_endpoint=f"{auth_server}/introspect",
            oauth_strict=oauth_strict,
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Make sure to provide a valid Authorization Server URL")
        return 1

    try:
        mcp_server = create_resource_server(settings)

        logger.info(f"🚀 MCP Resource Server running on {settings.server_url}")
        logger.info(f"🔑 Using Authorization Server: {settings.auth_server_url}")

        # Run the server - this should block and keep running
        mcp_server.run(transport=transport)
        logger.info("Server stopped")
        return 0
    except Exception:
        logger.exception("Server error")
        return 1


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
