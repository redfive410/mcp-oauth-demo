```
# Terminal 1 - Run auth server
cd auth-server
uv run mcp-simple-auth-as --port=9000

# Terminal 2 - Run resource server
cd mcp-server
uv run mcp-simple-auth-rs --port=8001 --auth-server=http://localhost:9000  --transport=streamable-http --oauth-strict

# Terminal 3 - Local tests
curl http://localhost:9000/.well-known/oauth-authorization-server | jq

# Terminal 3 - Run MCP Inspector
npx @modelcontextprotocol/inspector
```
1. Open OAuth Settings to configure access token
2. Use Quick Oauth Flow to get access token
3. Sign-In to demo Identity login web page
4. Save access token
5. Use access token as Bearer token to authenicate with the MCP server
6. Connect to MCP server

========

```
cd auth-server
./deploy.sh
```

```
# Run resource server using remote auth server

uv run mcp-simple-auth-rs --port=8001 --auth-server=https://mcp-oauth-auth-server-323998774564.us-west1.run.app  --transport=streamable-http --oauth-strict
```

```
curl http://localhost:8001/.well-known/oauth-protected-resource/mcp | jq

curl -X POST https://mcp-oauth-auth-server-323998774564.us-west1.run.app/register \
      -H "Content-Type: application/json" \
      -d '{
        "client_name": "My MCP Client",
        "redirect_uris": ["http://localhost:3000/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "user"
      }'
```

OAuthClient library builds authorization URL. (ex: https://mcp-oauth-auth-server-4vohcegqpq-uw.a.run.app/authorize?response_type=code&client_id=25bfad56-c6db-400f-acff-7d39f5b1f697&redirect_uri=http%3A%2F%2Flocalhost%3A3030%2Fcallback&state=CQyV5QwPWLk_KT3SBugeiRkYWXlome-RtJ44hJSyC34&code_challenge=JCnljrfkS0wdOHwUicDJ-Sgf5heVaZgbBkQhE-GbQek&code_challenge_method=S256&resource=http%3A%2F%2Flocalhost%3A8001&scope=user)

Authorization code is exchanged for Bearer token.

Bearer token is passed as header for Auth to MCP server.

==========

## Firestore Persistence

The OAuth Authorization Server now uses **Firestore** for persistent storage, solving CloudRun instance timeout issues.

### What's Stored in Firestore

All OAuth state persists across CloudRun restarts:
- OAuth clients (DCR registrations) → `oauth_clients` collection
- Access tokens → `oauth_tokens` collection
- Authorization codes → `auth_codes` collection
- OAuth flow state → `oauth_state` collection
- User session data → `user_data` collection

### Benefits

✅ **No state loss** - Tokens survive CloudRun instance restarts
✅ **Serverless-friendly** - No connection pooling issues
✅ **Auto-scaling** - Firestore scales with your traffic
✅ **Fast** - 50-150ms latency for token introspection
✅ **Cost-effective** - Pay-per-use (~$3/month for typical usage)

### Deployment

The `deploy.sh` script automatically:
1. Enables Firestore API
2. Creates Firestore database (Native mode)
3. Configures CloudRun with `GCP_PROJECT_ID` environment variable
4. Grants automatic Firestore permissions

```bash
cd auth-server
./deploy.sh
```

### New Endpoints

**Manual cleanup of expired data:**
```bash
curl -X POST https://your-auth-server.run.app/cleanup
```

**Health check:**
```bash
curl https://your-auth-server.run.app/health
```

### Documentation

See [auth-server/FIRESTORE_SETUP.md](auth-server/FIRESTORE_SETUP.md) for:
- Architecture details
- Firestore collections schema
- Local development setup (with emulator)
- Monitoring and maintenance
- Cost optimization
- Security considerations
- Troubleshooting guide

### Migration Notes

No data migration needed! When you first deploy:
- Firestore collections start empty
- Existing clients must re-register via `/register`
- Users must re-authenticate to get new tokens

This matches the previous behavior when CloudRun instances restarted.
