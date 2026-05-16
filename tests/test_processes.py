"""Tests for the process listing module."""

import unittest
from unittest.mock import patch, MagicMock

from intruder.processes import list_processes


class ListProcessesTests(unittest.TestCase):
    @patch("intruder.processes.psutil")
    def test_returns_sorted_list(self, mock_psutil) -> None:
        p1 = MagicMock()
        p1.info = {"pid": 100, "name": "zeta.exe", "exe": "C:\\zeta.exe", "username": "user"}
        p2 = MagicMock()
        p2.info = {"pid": 200, "name": "alpha.exe", "exe": "C:\\alpha.exe", "username": "user"}
        mock_psutil.process_iter.return_value = [p1, p2]

        result = list_processes()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "alpha.exe")
        self.assertEqual(result[1]["name"], "zeta.exe")

    @patch("intruder.processes.psutil")
    def test_handles_access_denied(self, mock_psutil) -> None:
        import psutil as _ps
        p1 = MagicMock()
        p1.info.__getitem__ = MagicMock(side_effect=_ps.AccessDenied(123))
        type(p1).info = property(lambda self: (_ for _ in ()).throw(_ps.AccessDenied(123)))
        mock_psutil.process_iter.return_value = [p1]
        mock_psutil.AccessDenied = _ps.AccessDenied
        mock_psutil.NoSuchProcess = _ps.NoSuchProcess
        mock_psutil.ZombieProcess = _ps.ZombieProcess

        result = list_processes()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
