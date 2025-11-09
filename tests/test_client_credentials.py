#!/usr/bin/env python3
"""
Test script for Client Credentials Flow.

This script demonstrates how to:
1. Register a service account client
2. Authenticate using client_id + client_secret
3. Get an access token
4. Use the token to call a protected MCP resource

Usage:
    python test_client_credentials.py
"""

import asyncio
import httpx


async def test_client_credentials_flow():
    """Test the client credentials OAuth flow."""

    AUTH_SERVER = "http://localhost:9000"
    RESOURCE_SERVER = "http://localhost:8001"

    print("🔐 Testing Client Credentials Flow\n")

    # Step 1: Register a service account client
    print("1️⃣  Registering service account client...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/register/service_account",
            json={
                "client_name": "My Service Account",
                "grant_types": ["client_credentials"],
                "scope": "user",  # Request 'user' scope
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        response.raise_for_status()
        client_info = response.json()

        client_id = client_info["client_id"]
        client_secret = client_info["client_secret"]

        print(f"✅ Client registered:")
        print(f"   Client ID: {client_id}")
        print(f"   Client Secret: {client_secret[:20]}...")
        print()

    # Step 2: Exchange client credentials for access token
    print("2️⃣  Exchanging client credentials for access token...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/token/custom",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "user",
            },
        )
        response.raise_for_status()
        token_response = response.json()

        access_token = token_response["access_token"]

        print(f"✅ Access token received:")
        print(f"   Token: {access_token[:30]}...")
        print(f"   Type: {token_response['token_type']}")
        print(f"   Expires in: {token_response['expires_in']} seconds")
        print(f"   Scope: {token_response['scope']}")
        print()

    # Step 3: Verify token via introspection
    print("3️⃣  Verifying token via introspection...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/introspect",
            data={"token": access_token},
        )
        response.raise_for_status()
        introspection = response.json()

        print(f"✅ Token introspection:")
        print(f"   Active: {introspection['active']}")
        print(f"   Client ID: {introspection['client_id']}")
        print(f"   Scope: {introspection['scope']}")
        print()

    # Step 4: Use token to call MCP resource server
    print("4️⃣  Calling MCP resource server with token...")
    print("   (Note: Make sure the resource server is running on port 8001)")
    try:
        async with httpx.AsyncClient() as client:
            # Call a hypothetical MCP tool endpoint
            # This is just for demonstration - actual MCP protocol is different
            response = await client.get(
                f"{RESOURCE_SERVER}/health",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code == 200:
                print(f"✅ Resource server responded successfully!")
                print(f"   Response: {response.json()}")
            else:
                print(f"⚠️  Resource server returned status {response.status_code}")
    except httpx.ConnectError:
        print("⚠️  Could not connect to resource server (is it running?)")

    print("\n🎉 Client Credentials Flow test complete!")


if __name__ == "__main__":
    asyncio.run(test_client_credentials_flow())
