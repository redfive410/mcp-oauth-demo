# OAuth Flow Tests

This directory contains integration tests for the OAuth flows supported by the auth server.

## Running Tests

From the `tests` directory, install dependencies with uv:

```bash
cd tests
uv sync --no-install-project
```

Run the tests:

```bash
# Test Client Credentials Flow
uv run --no-project test_client_credentials.py

# Test JWT Bearer Grant Flow
uv run --no-project test_jwt_bearer.py
```

## Prerequisites

Make sure the auth server is running before running these tests:

```bash
# From the auth-server directory
lsof -i :9000 #check if port is open

cd ../auth-server
uv run mcp-simple-auth-as --no-firestore
```

The `--no-firestore` flag uses in-memory storage instead of Firestore, which is suitable for local testing.

Optionally, you can also run the resource server on port 8001 to test the full flow with protected resources.

## Test Flows

### Client Credentials Flow
Tests the OAuth 2.0 Client Credentials grant type, which is used for machine-to-machine authentication.

### JWT Bearer Grant Flow
Tests the RFC 7523 JWT Bearer Grant flow, which uses signed JWTs for authentication.

## TODO
Fix Security Implications

  1. Open registration: Anyone can create service accounts
  2. No rate limiting visible: Could lead to credential exhaustion attacks
  3. No approval workflow: Immediately returns credentials

  This setup is common for:
  - Development/testing environments (like this demo)
  - Internal networks with perimeter security
  - Systems with external authorization (e.g., API gateway handles auth)

  For production, you'd typically want:
  - Admin authentication (OAuth scope like client:register)
  - Approval workflows
  - Rate limiting
  - Audit logging
  - Initial token or registration secret

  RFC 7591 (DCR) allows both authenticated and unauthenticated registration, but recommends authentication for production systems.
