import unittest

from mcp.server.mcpserver import MCPServer

from openedge_schema_mcp.server import mcp


class ServerTests(unittest.TestCase):
    def test_uses_mcp_v2_server(self) -> None:
        self.assertIsInstance(mcp, MCPServer)