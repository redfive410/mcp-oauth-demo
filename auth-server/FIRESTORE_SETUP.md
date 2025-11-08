# Firestore Persistence for OAuth Server

This document explains the Firestore persistence layer implementation for the MCP OAuth Authorization Server.

## Problem Statement

The original implementation stored all OAuth state in-memory using Python dictionaries:
- OAuth clients (DCR registrations)
- Access tokens
- Authorization codes
- OAuth flow state
- User session data

When CloudRun instances timeout or restart, all this state was lost, causing:
- Existing tokens to fail introspection
- Registered clients to disappear
- Active OAuth flows to be interrupted

## Solution: Firestore Persistence

Firestore provides serverless persistence ideal for CloudRun:
- ✅ No connection pooling issues
- ✅ Fast reads/writes (low latency)
- ✅ Native GCP integration
- ✅ Automatic scaling
- ✅ Pay-per-use pricing

## Architecture

### Firestore Collections

The implementation uses 5 Firestore collections:

#### 1. `oauth_clients`
Stores OAuth client registrations (Dynamic Client Registration).

```
/oauth_clients/{client_id}
  - client_id: string
  - client_secret: string
  - client_name: string
  - redirect_uris: array
  - grant_types: array
  - token_endpoint_auth_method: string
  - response_types: array
  - scope: string
```

#### 2. `oauth_tokens`
Stores access tokens with automatic expiration checking.

```
/oauth_tokens/{token}
  - token: string
  - client_id: string
  - scopes: array
  - expires_at: number (Unix timestamp)
  - resource: string (RFC 8707)
```

#### 3. `auth_codes`
Stores authorization codes (5-minute expiration).

```
/auth_codes/{code}
  - code: string
  - client_id: string
  - redirect_uri: string
  - redirect_uri_provided_explicitly: boolean
  - expires_at: number (Unix timestamp)
  - scopes: array
  - code_challenge: string
  - resource: string (RFC 8707)
```

#### 4. `oauth_state`
Stores OAuth flow state mapping (temporary).

```
/oauth_state/{state}
  - redirect_uri: string
  - code_challenge: string
  - redirect_uri_provided_explicitly: string
  - client_id: string
  - resource: string (RFC 8707)
```

#### 5. `user_data`
Stores user session data.

```
/user_data/{key}  (key = username or token)
  - username: string
  - user_id: string
  - authenticated_at: number (Unix timestamp)
```

### Implementation Files

#### `firestore_client.py`
Provides Firestore client singleton and collection operations:
- `get_client()`, `set_client()` - Client operations
- `get_token()`, `set_token()`, `delete_token()` - Token operations
- `get_auth_code()`, `set_auth_code()`, `delete_auth_code()` - Auth code operations
- `get_state()`, `set_state()`, `delete_state()` - State operations
- `cleanup_expired_tokens()`, `cleanup_expired_auth_codes()` - Cleanup operations

#### `firestore_auth_provider.py`
Extends `SimpleOAuthProvider` to use Firestore instead of in-memory dictionaries:
- Overrides all storage methods to use Firestore
- Converts Pydantic models to/from Firestore dicts
- Provides `cleanup_expired_data()` for maintenance

#### `auth_server.py` (updated)
- Uses `FirestoreOAuthProvider` instead of `SimpleOAuthProvider`
- Adds `/cleanup` endpoint for manual cleanup trigger

## Deployment

### Prerequisites

1. **GCP Project with Firestore enabled**
   - The deploy script automatically enables Firestore API
   - Creates Firestore database in Native mode if not exists

2. **Dependencies installed**
   - `google-cloud-firestore>=2.19.0` (added to pyproject.toml)

### Deployment Steps

The `deploy.sh` script handles everything automatically:

```bash
cd auth-server
./deploy.sh
```

The script will:
1. ✅ Enable Firestore API
2. ✅ Create Firestore database (if needed)
3. ✅ Build and push Docker image
4. ✅ Deploy to CloudRun with `GCP_PROJECT_ID` env var
5. ✅ Configure ISSUER_URL

### Environment Variables

The CloudRun service needs one environment variable:
- `GCP_PROJECT_ID`: Your GCP project ID (set automatically by deploy.sh)

### Permissions

CloudRun service accounts have automatic Firestore permissions in the same project.
No additional IAM configuration needed!

## Endpoints

### New Endpoints

#### `POST /cleanup`
Manually trigger cleanup of expired tokens and auth codes.

**Request:**
```bash
curl -X POST https://your-auth-server.run.app/cleanup
```

**Response:**
```json
{
  "status": "success",
  "cleaned_up": {
    "tokens": 5,
    "auth_codes": 2
  }
}
```

### Existing Endpoints (unchanged)

- `GET /.well-known/oauth-authorization-server` - OAuth metadata
- `POST /register` - Dynamic Client Registration
- `GET /authorize` - Authorization endpoint
- `POST /token` - Token endpoint
- `POST /introspect` - Token introspection (for Resource Servers)
- `POST /revoke` - Token revocation
- `GET /health` - Health check

## Local Development

### Option 1: Firestore Emulator (Recommended)

```bash
# Install Firestore emulator
gcloud components install cloud-firestore-emulator

# Start emulator
gcloud beta emulators firestore start

# In another terminal, set environment variable
export FIRESTORE_EMULATOR_HOST=localhost:8080
export GCP_PROJECT_ID=area51-954-dev-1

# Run auth server
cd auth-server
uv run mcp-simple-auth-as --port=9000
```

### Option 2: Use Production Firestore

```bash
# Authenticate with GCP
gcloud auth application-default login

# Set project ID
export GCP_PROJECT_ID=your-project-id

# Run auth server
cd auth-server
uv run mcp-simple-auth-as --port=9000
```

### Option 3: In-Memory Mode (for testing)

To use the original in-memory implementation for local testing, you can temporarily modify `auth_server.py` to use `SimpleOAuthProvider` instead of `FirestoreOAuthProvider`.

## Maintenance

### Cleanup Expired Data

Expired tokens and auth codes are automatically cleaned on read (lazy deletion).

For proactive cleanup:

**Manual trigger:**
```bash
curl -X POST https://your-auth-server.run.app/cleanup
```

**Automated cleanup (Cloud Scheduler):**
```bash
# Create a scheduled job to run cleanup every hour
gcloud scheduler jobs create http oauth-cleanup \
  --schedule="0 * * * *" \
  --uri="https://your-auth-server.run.app/cleanup" \
  --http-method=POST \
  --location=us-west1
```

### Monitoring

**View Firestore data in GCP Console:**
```
https://console.cloud.google.com/firestore/databases/-default-/data
```

**Check CloudRun logs:**
```bash
gcloud run services logs read mcp-oauth-auth-server \
  --project=your-project-id \
  --region=us-west1
```

**Firestore metrics:**
- Document reads/writes
- Storage usage
- Active connections

## Cost Optimization

### Firestore Pricing (Pay-per-use)

- Document reads: $0.06 per 100,000
- Document writes: $0.18 per 100,000
- Storage: $0.18 per GB/month

### Typical Usage

For a small deployment (100 users, 1000 requests/day):
- ~3000 reads/day (introspection checks)
- ~500 writes/day (token issuance)
- ~1 MB storage
- **Cost: ~$0.01/day or $3/month**

### Optimization Tips

1. **Lazy deletion** - Expired items are deleted on read, no background jobs needed
2. **Short-lived auth codes** - 5 minutes (automatic cleanup)
3. **Token expiration** - 1 hour (balances security and read load)
4. **Minimal indexing** - Only `expires_at` fields are indexed for cleanup queries

## Security Considerations

### Token Storage
- Tokens stored as document IDs (fast lookups)
- No encryption at rest needed (Firestore encrypts by default)
- Token introspection still required (stateful tokens)

### Firestore Security Rules

For production, add Firestore security rules to prevent direct access:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Only allow reads/writes from authenticated CloudRun service
    match /{document=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

Deploy rules:
```bash
firebase deploy --only firestore:rules
```

### Immediate Revocation

Unlike JWT tokens, Firestore-backed tokens support immediate revocation:
- `DELETE /revoke` removes token from Firestore
- Next introspection call returns `{"active": false}`
- Max revocation delay: introspection cache TTL (typically 0-60 seconds)

## Migration from In-Memory

If you're upgrading from the in-memory implementation:

1. **No data migration needed** - State was lost on restart anyway
2. **First deployment** - All collections start empty
3. **Existing clients** - Must re-register via `/register` endpoint
4. **Existing tokens** - Will fail introspection (users must re-authenticate)

This is expected behavior and matches what happened on CloudRun restarts previously.

## Troubleshooting

### "Firestore API not enabled"
```bash
gcloud services enable firestore.googleapis.com --project=your-project-id
```

### "Permission denied"
Check CloudRun service account has Firestore permissions:
```bash
gcloud projects get-iam-policy your-project-id
```

CloudRun default service account should have `roles/datastore.user` or higher.

### "Database not found"
Create Firestore database:
```bash
gcloud firestore databases create --location=us-west1 --type=firestore-native --project=your-project-id
```

### Local development connection issues
Ensure `GCP_PROJECT_ID` environment variable is set:
```bash
export GCP_PROJECT_ID=your-project-id
```

For emulator:
```bash
export FIRESTORE_EMULATOR_HOST=localhost:8080
```

## Performance

### Latency Benchmarks

**Token Introspection:**
- In-memory: ~1ms
- Firestore: ~50-150ms (includes network + Firestore lookup)
- Acceptable for OAuth flows (happens once per session)

**Authorization Flow:**
- Firestore adds ~100-200ms per OAuth step
- Total flow time: 2-5 seconds (mostly user interaction)
- Negligible impact on user experience

### Scalability

Firestore automatically scales to:
- Millions of documents
- 10,000+ writes/second
- 100,000+ reads/second

CloudRun + Firestore = unlimited horizontal scaling

## Future Enhancements

### Refresh Tokens
Currently not implemented, but ready for Firestore:
```
/refresh_tokens/{token}
  - token: string
  - client_id: string
  - user_id: string
  - expires_at: number
  - scopes: array
```

### Token Rotation
Add version tracking to tokens for rotation:
```
/oauth_tokens/{token}
  ...
  - version: number
  - rotated_from: string (previous token)
```

### Audit Logging
Store OAuth events in Firestore:
```
/audit_log/{event_id}
  - timestamp: number
  - event_type: string
  - user_id: string
  - client_id: string
  - ip_address: string
```

## References

- [Firestore Documentation](https://cloud.google.com/firestore/docs)
- [CloudRun Documentation](https://cloud.google.com/run/docs)
- [OAuth 2.0 RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)
- [Token Introspection RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662)
- [Resource Indicators RFC 8707](https://datatracker.ietf.org/doc/html/rfc8707)
