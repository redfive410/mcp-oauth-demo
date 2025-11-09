# OAuth 2.0 Flows Documentation

This MCP OAuth demo now supports **three OAuth 2.0 grant types** for different use cases:

## 1. Authorization Code Flow (Interactive User Login)

**Use case:** Web applications, interactive user authentication

**How it works:**
1. User is redirected to login page
2. User enters credentials (demo_user/demo_password)
3. Auth server issues authorization code
4. Client exchanges code for access token

**Endpoints:**
- `GET /authorize` - Start OAuth flow
- `GET /login` - Login page
- `POST /login/callback` - Handle login
- `POST /token` - Exchange authorization code

**Example:**
```bash
# Already implemented in MCP Inspector
# User clicks "Connect" → Login page → Token received
```

---

## 2. Client Credentials Flow (Machine-to-Machine)

**Use case:** Service accounts, backend services, automated workflows

**How it works:**
1. Client authenticates with `client_id` + `client_secret`
2. Auth server validates credentials
3. Auth server issues access token directly (no user involved)

**Security:** Uses shared secret (like password for services)

**Endpoints:**
- `POST /register` - Register service account client
- `POST /token/custom` - Exchange credentials for token

**Example:**
```bash
# 1. Register service account
curl -X POST http://localhost:9000/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "My Service Account",
    "grant_types": ["client_credentials"],
    "scope": "user",
    "token_endpoint_auth_method": "client_secret_post"
  }'

# Response: {"client_id": "...", "client_secret": "..."}

# 2. Get access token
curl -X POST http://localhost:9000/token/custom \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "scope=user"

# Response: {"access_token": "...", "token_type": "Bearer", ...}
```

**Test script:**
```bash
python test_client_credentials.py
```

---

## 3. JWT Bearer Grant (Cryptographic Service Authentication)

**Use case:** Enterprise service accounts, Google Cloud, AWS, Kubernetes

**How it works:**
1. Client generates RSA key pair (public/private keys)
2. Client registers with auth server and uploads public key
3. Client creates JWT assertion signed with private key
4. Auth server validates JWT signature with public key
5. Auth server issues access token

**Security:**
- Private key never leaves client
- No shared secrets to leak
- JWTs are short-lived (minutes)
- Industry standard for cloud platforms

**Endpoints:**
- `POST /register` - Register service account client
- `POST /register_public_key` - Upload public key
- `POST /token/custom` - Exchange JWT for token

**Example:**
```bash
# 1. Generate RSA key pair
openssl genrsa -out private_key.pem 2048
openssl rsa -in private_key.pem -pubout -out public_key.pem

# 2. Register service account
curl -X POST http://localhost:9000/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "My JWT Service Account",
    "grant_types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
    "scope": "user",
    "token_endpoint_auth_method": "private_key_jwt"
  }'

# Response: {"client_id": "..."}

# 3. Register public key
curl -X POST http://localhost:9000/register_public_key \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "public_key": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
  }'

# 4. Create JWT assertion (using Python/libraries)
# See test_jwt_bearer.py for full example

# 5. Exchange JWT for token
curl -X POST http://localhost:9000/token/custom \
  -d "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" \
  -d "assertion=YOUR_SIGNED_JWT" \
  -d "scope=user"

# Response: {"access_token": "...", "token_type": "Bearer", ...}
```

**Test script:**
```bash
python test_jwt_bearer.py
```

---

## Comparison

| Feature | Authorization Code | Client Credentials | JWT Bearer |
|---------|-------------------|-------------------|------------|
| **User involvement** | ✅ Yes (interactive) | ❌ No (service) | ❌ No (service) |
| **Authentication** | Username + Password | client_id + client_secret | Signed JWT |
| **Security model** | Session-based | Shared secret | Asymmetric crypto |
| **Best for** | Web apps | Simple automation | Enterprise services |
| **Token represents** | User permissions | Service permissions | Service permissions |
| **Secret storage** | None (PKCE) | client_secret | Private key |
| **Compromise risk** | Low (no secrets) | Medium (secret leak) | Low (keys separate) |

---

## Token Introspection

All three flows produce tokens that can be validated the same way:

```bash
curl -X POST http://localhost:9000/introspect \
  -d "token=YOUR_ACCESS_TOKEN"

# Response:
{
  "active": true,
  "client_id": "...",
  "scope": "user",
  "exp": 1234567890,
  "token_type": "Bearer"
}
```

---

## Architecture Notes

### Resource Server (MCP Server)

The **Resource Server doesn't care** which flow was used! It just validates tokens:

```python
# In your MCP server
@app.tool()
async def get_time() -> dict[str, Any]:
    """This works with tokens from ANY flow"""
    # Token could be from:
    # - User login (authorization code)
    # - Service with secret (client credentials)
    # - Service with JWT (jwt bearer)

    # Resource server introspects and authorizes
    return {"time": datetime.now().isoformat()}
```

### Firestore Persistence

All OAuth state is persisted in Firestore:
- `oauth_clients` - Client registrations
- `oauth_tokens` - Access tokens
- `auth_codes` - Authorization codes
- `oauth_state` - OAuth flow state
- `user_data` - User/service account data
- `client_public_keys` - Public keys for JWT validation

This allows the auth server to survive restarts and scale across multiple instances.

---

## Running Tests

1. **Start the auth server:**
   ```bash
   cd auth-server
   uv run python -m mcp_simple_auth.auth_server
   ```

2. **Test client credentials flow:**
   ```bash
   python test_client_credentials.py
   ```

3. **Test JWT bearer flow:**
   ```bash
   python test_jwt_bearer.py
   ```

---

## Dependencies

The implementation uses:
- `pyjwt[crypto]>=2.8.0` - JWT creation and validation
- `cryptography` - RSA key generation (for tests)
- Standard OAuth libraries from MCP SDK

Install with:
```bash
cd auth-server
uv sync
```

---

## Security Considerations

### Client Credentials Flow
- ✅ Simple to implement
- ⚠️ Shared secret must be stored securely
- ⚠️ Secret rotation requires updating all clients
- 💡 Good for internal services with secure storage

### JWT Bearer Grant
- ✅ No shared secrets
- ✅ Private key never transmitted
- ✅ Standard for cloud platforms (GCP, AWS, K8s)
- ⚠️ More complex to implement
- 💡 Best for production service accounts

### Authorization Code Flow
- ✅ Most secure for user authentication
- ✅ No client secrets (with PKCE)
- ✅ User consent
- 💡 Best for interactive applications

---

## References

- **RFC 6749** - OAuth 2.0 Authorization Framework
- **RFC 6749 Section 4.4** - Client Credentials Grant
- **RFC 7523** - JSON Web Token (JWT) Profile for OAuth 2.0
- **RFC 7662** - OAuth 2.0 Token Introspection
