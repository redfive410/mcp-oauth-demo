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
