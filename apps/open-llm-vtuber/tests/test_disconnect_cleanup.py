"""Disconnect cleanup regression; no model or service startup required."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, "E:/AI/LocalVoiceAgent/apps/open-llm-vtuber")
sys.path.insert(0, "E:/AI/LocalVoiceAgent/apps/open-llm-vtuber/src")
from open_llm_vtuber.websocket_handler import WebSocketHandler


class DisconnectCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_closes_context_once_and_removes_client(self):
        context = SimpleNamespace(close=AsyncMock())
        handler = WebSocketHandler.__new__(WebSocketHandler)
        handler.chat_group_manager = Mock()
        handler.chat_group_manager.get_client_group.return_value = None
        handler.client_connections = {"client": Mock()}
        handler.client_contexts = {"client": context}
        handler.received_data_buffers = {"client": []}
        handler.current_conversation_tasks = {}
        handler.send_group_update = AsyncMock()

        with patch(
            "open_llm_vtuber.websocket_handler.handle_client_disconnect",
            new_callable=AsyncMock,
        ), patch("open_llm_vtuber.websocket_handler.message_handler"):
            await handler.handle_disconnect("client")
            await handler.handle_disconnect("client")

        context.close.assert_awaited_once()
        self.assertNotIn("client", handler.client_contexts)
        self.assertNotIn("client", handler.client_connections)
        self.assertNotIn("client", handler.received_data_buffers)


if __name__ == "__main__":
    unittest.main()
