import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from intruder.models import Direction, ResolveAction
from intruder.router import MessageRouter




class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = MessageRouter()

    def test_ignores_non_send_messages(self) -> None:
        script = MagicMock()
        self.router.on_message("s1", 100, script, {"type": "error", "description": "oops"}, None)
        script.post.assert_not_called()

    def test_ignores_unknown_direction(self) -> None:
        script = MagicMock()
        msg = {"type": "send", "payload": {"id": "m1", "type": "x"}}
        self.router.on_message("s1", 100, script, msg, None)
        script.post.assert_not_called()

    def test_close_message_does_not_post(self) -> None:
        script = MagicMock()
        msg = {"type": "send", "payload": {"id": "m1", "type": "c", "m": "test"}}
        self.router.on_message("s1", 100, script, msg, None)
        script.post.assert_not_called()

    @patch("intruder.router.intercept_state")
    @patch("intruder.router.pending_store")
    def test_send_message_enqueues_and_posts_response(self, mock_store, mock_intercept) -> None:
        mock_intercept.enabled = True
        mock_store.enqueue.return_value = (ResolveAction.FORWARD, None)

        script = MagicMock()
        msg = {"type": "send", "payload": {"id": "m1", "type": "s", "m": "wsock"}}
        data = b"hello"

        self.router.on_message("s1", 100, script, msg, data)

        mock_store.enqueue.assert_called_once()
        intercepted = mock_store.enqueue.call_args[0][0]
        self.assertEqual(intercepted.id, "m1")
        self.assertEqual(intercepted.direction, Direction.SEND)
        self.assertEqual(intercepted.data, b"hello")

        script.post.assert_called_once()
        posted = script.post.call_args[0][0]
        self.assertEqual(posted["type"], "m1")
        self.assertEqual(posted["data"], list(b"hello"))

    @patch("intruder.router.intercept_state")
    @patch("intruder.router.pending_store")
    def test_replace_action_posts_replacement(self, mock_store, mock_intercept) -> None:
        mock_intercept.enabled = True
        mock_store.enqueue.return_value = (ResolveAction.REPLACE, b"modified")

        script = MagicMock()
        msg = {"type": "send", "payload": {"id": "m2", "type": "r"}}
        data = b"original"

        self.router.on_message("s1", 100, script, msg, data)

        posted = script.post.call_args[0][0]
        self.assertEqual(posted["data"], list(b"modified"))

    @patch("intruder.router.intercept_state")
    @patch("intruder.router.pending_store")
    def test_drop_action_posts_empty(self, mock_store, mock_intercept) -> None:
        mock_intercept.enabled = True
        mock_store.enqueue.return_value = (ResolveAction.DROP, None)

        script = MagicMock()
        msg = {"type": "send", "payload": {"id": "m3", "type": "s"}}
        data = b"secret"

        self.router.on_message("s1", 100, script, msg, data)

        posted = script.post.call_args[0][0]
        self.assertEqual(posted["data"], [])


if __name__ == "__main__":
    unittest.main()
