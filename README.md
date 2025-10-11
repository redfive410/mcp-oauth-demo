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
