import threading
import time
import unittest

from intruder.models import Direction, InterceptedMessage, ResolveAction
from intruder.pending import PendingStore


class PendingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PendingStore()
        self.store._auto_forward_timeout_ms = 500

    def _make_msg(self, msg_id: str = "test-1") -> InterceptedMessage:
        return InterceptedMessage(
            id=msg_id,
            session_id="sess-1",
            pid=1234,
            direction=Direction.SEND,
            data=b"hello world",
            metadata={"m": "test"},
        )

    def test_resolve_forward(self) -> None:
        msg = self._make_msg()
        result: tuple | None = None

        def enqueue():
            nonlocal result
            result = self.store.enqueue(msg)

        t = threading.Thread(target=enqueue)
        t.start()
        time.sleep(0.05)

        ok = self.store.resolve("test-1", ResolveAction.FORWARD)
        t.join(timeout=2)
        self.assertTrue(ok)
        self.assertIsNotNone(result)
        action, data = result
        self.assertEqual(action, ResolveAction.FORWARD)
        self.assertIsNone(data)

    def test_resolve_replace(self) -> None:
        import base64
        msg = self._make_msg("test-replace")
        result: tuple | None = None

        def enqueue():
            nonlocal result
            result = self.store.enqueue(msg)

        t = threading.Thread(target=enqueue)
        t.start()
        time.sleep(0.05)

        replacement = base64.b64encode(b"replaced").decode()
        ok = self.store.resolve("test-replace", ResolveAction.REPLACE, replacement)
        t.join(timeout=2)
        self.assertTrue(ok)
        action, data = result
        self.assertEqual(action, ResolveAction.REPLACE)
        self.assertEqual(data, b"replaced")

    def test_resolve_drop(self) -> None:
        msg = self._make_msg("test-drop")
        result: tuple | None = None

        def enqueue():
            nonlocal result
            result = self.store.enqueue(msg)

        t = threading.Thread(target=enqueue)
        t.start()
        time.sleep(0.05)

        ok = self.store.resolve("test-drop", ResolveAction.DROP)
        t.join(timeout=2)
        self.assertTrue(ok)
        action, _ = result
        self.assertEqual(action, ResolveAction.DROP)

    def test_resolve_nonexistent_returns_false(self) -> None:
        ok = self.store.resolve("nonexistent", ResolveAction.FORWARD)
        self.assertFalse(ok)

    def test_list_pending(self) -> None:
        msg = self._make_msg("test-list")
        started = threading.Event()

        def enqueue():
            started.set()
            self.store.enqueue(msg)

        t = threading.Thread(target=enqueue)
        t.start()
        started.wait()
        time.sleep(0.05)

        pending = self.store.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], "test-list")
        self.assertEqual(pending[0]["direction"], "send")
        self.assertEqual(pending[0]["pid"], 1234)

        self.store.resolve("test-list", ResolveAction.FORWARD)
        t.join(timeout=2)

    def test_auto_forward_on_timeout(self) -> None:
        """Messages auto-forward when the timeout fires."""
        from intruder.config import settings
        original = settings.auto_forward_timeout_ms
        settings.auto_forward_timeout_ms = 200
        try:
            msg = self._make_msg("test-timeout")
            action, _ = self.store.enqueue(msg)
            self.assertEqual(action, ResolveAction.FORWARD)
        finally:
            settings.auto_forward_timeout_ms = original


if __name__ == "__main__":
    unittest.main()
