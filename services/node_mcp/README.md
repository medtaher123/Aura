# Node MCP sidecars for agent-server
#
# Packages listed in servers.json are started with Supergateway and exposed as
# Streamable HTTP at http://<host>:<port>/mcp
#
# Agent wiring:
#   - NODE_MCP_URL in agent_server .env (host only, e.g. http://localhost or http://node-mcp)
#   - port in config/tool_platform_seed.yaml under runner: node
#   - resolved URL = {NODE_MCP_URL}:{port}
#
# Current servers:
#   immo-france → port 8101
#
# Add another Node MCP:
#   1. Add dependency in package.json
#   2. Add entry in servers.json with a free port
#   3. Map the port in docker-compose.yml
#   4. Register in agent_server config/tool_platform_seed.yaml with runner: node + port
