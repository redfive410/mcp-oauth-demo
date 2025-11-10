#!/usr/bin/env python3
"""
Test script for JWT Bearer Grant Flow (RFC 7523).

This script demonstrates how to:
1. Generate RSA key pair
2. Register a service account client
3. Register the client's public key with the auth server
4. Create and sign a JWT assertion
5. Exchange JWT for access token
6. Use the token to call a protected MCP resource

Usage:
    python test_jwt_bearer.py
"""

import asyncio
import time
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


async def test_jwt_bearer_flow():
    """Test the JWT Bearer Grant OAuth flow."""

    AUTH_SERVER = "http://localhost:9000"
    RESOURCE_SERVER = "http://localhost:8001"

    print("🔐 Testing JWT Bearer Grant Flow\n")

    # Step 1: Generate RSA key pair
    print("1️⃣  Generating RSA key pair...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Save keys to files for reference
    Path("test_private_key.pem").write_bytes(private_pem)
    Path("test_public_key.pem").write_bytes(public_pem)

    print(f"✅ RSA key pair generated:")
    print(f"   Private key saved to: test_private_key.pem")
    print(f"   Public key saved to: test_public_key.pem")
    print()

    # Step 2: Register a service account client
    print("2️⃣  Registering service account client...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/register/service_account",
            json={
                "client_name": "My JWT Service Account",
                "grant_types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
                "scope": "user",
            },
        )
        response.raise_for_status()
        client_info = response.json()

        client_id = client_info["client_id"]

        print(f"✅ Client registered:")
        print(f"   Client ID: {client_id}")
        print()

    # Step 3: Register public key with auth server
    print("3️⃣  Registering public key with auth server...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/register_public_key",
            json={
                "client_id": client_id,
                "public_key": public_pem.decode("utf-8"),
            },
        )
        response.raise_for_status()
        result = response.json()

        print(f"✅ Public key registered:")
        print(f"   {result['message']}")
        print()

    # Step 4: Create JWT assertion
    print("4️⃣  Creating JWT assertion...")
    now = int(time.time())
    claims = {
        "iss": client_id,  # Issuer (client ID)
        "sub": client_id,  # Subject (client ID for service accounts)
        "aud": AUTH_SERVER,  # Audience (auth server URL)
        "exp": now + 300,  # Expiration (5 minutes)
        "iat": now,  # Issued at
        "scope": "user",  # Requested scopes
    }

    # Sign JWT with private key
    assertion = jwt.encode(claims, private_pem, algorithm="RS256")
    print(assertion)

    print(f"✅ JWT assertion created:")
    print(f"   Token: {assertion[:50]}...")
    print(f"   Claims:")
    for key, value in claims.items():
        print(f"     {key}: {value}")
    print()

    # Step 5: Exchange JWT for access token
    print("5️⃣  Exchanging JWT assertion for access token...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVER}/token/custom",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
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

    # Step 6: Verify token via introspection
    print("6️⃣  Verifying token via introspection...")
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

    # Step 7: Use token to call MCP resource server
    print("7️⃣  Calling MCP resource server with token...")
    print("   (Note: Make sure the resource server is running on port 8001)")
    try:
        async with httpx.AsyncClient() as client:
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

    print("\n🎉 JWT Bearer Grant Flow test complete!")
    print("\n📝 Key files saved:")
    print("   - test_private_key.pem (keep this secret!)")
    print("   - test_public_key.pem (safe to share)")


if __name__ == "__main__":
    asyncio.run(test_jwt_bearer_flow())
