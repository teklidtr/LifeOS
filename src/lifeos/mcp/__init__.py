"""Local STDIO MCP adapter for LifeOS."""

from lifeos.mcp import server as _server
from lifeos.mcp.coherent_server import create_mcp_server

# Keep direct ``lifeos.mcp.server.create_mcp_server`` imports on the coherence-aware surface.
setattr(_server, "create_mcp_server", create_mcp_server)
