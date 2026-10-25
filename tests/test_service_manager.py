"""Service state regressions; never start/stop a real Windows service."""
import ctypes
import unittest
from unittest.mock import Mock, patch

from core import service_manager as sm


class ServiceStateTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.OpenSCManagerW.return_value = 0x100000001
        self.api.OpenServiceW.return_value = 0x100000002
        self.state = 1

        def query(handle, pointer):
            pointer._obj.current_state = self.state
            return True

        self.api.QueryServiceStatus.side_effect = query
        for name, value in (("IS_WINDOWS", True),):
            patcher = patch.object(sm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(ctypes, "WinDLL", return_value=self.api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_states_do_not_read_service_configuration(self):
        for number, expected in enumerate(("stopped", "start_pending", "stop_pending",
                                            "running", "continue_pending", "pause_pending", "paused"), 1):
            with self.subTest(number=number):
                self.state = number
                self.assertEqual(sm.get_service_status_details(), (expected, ""))
        self.api.QueryServiceConfigW.assert_not_called()
        self.api.OpenServiceW.assert_called_with(0x100000001, "zapret", 4)
        self.assertIs(self.api.OpenServiceW.restype, ctypes.wintypes.HANDLE)
        self.assertEqual(self.api.CloseServiceHandle.call_count, 14)

    def test_missing_service_is_not_an_unknown_state(self):
        self.api.OpenServiceW.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=1060):
            self.assertEqual(sm.get_service_status_details(), ("not_installed", ""))
        self.api.CloseServiceHandle.assert_called_once_with(0x100000001)

    def test_access_denied_is_not_treated_as_absent_or_pending(self):
        self.api.OpenServiceW.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=5):
            status, error = sm.get_service_status_details()
        self.assertEqual(status, "unknown")
        self.assertIn("код 5", error)

    def test_query_failure_closes_both_handles(self):
        self.api.QueryServiceStatus.side_effect = None
        self.api.QueryServiceStatus.return_value = False
        with patch.object(ctypes, "get_last_error", return_value=6):
            status, error = sm.get_service_status_details()
        self.assertEqual(status, "unknown")
        self.assertTrue(error)
        self.assertEqual([c.args[0] for c in self.api.CloseServiceHandle.call_args_list],
                         [0x100000002, 0x100000001])

    def test_manager_failure_does_not_use_invalid_handle(self):
        self.api.OpenSCManagerW.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=5):
            self.assertEqual(sm.get_service_status(), "unknown")
        self.api.OpenServiceW.assert_not_called()
        self.api.CloseServiceHandle.assert_not_called()

    def test_unknown_numeric_state_is_reported(self):
        self.state = 99
        status, error = sm.get_service_status_details()
        self.assertEqual(status, "unknown")
        self.assertIn("99", error)

    def test_stop_waits_for_stopped_state(self):
        with patch.object(sm, "service_belongs_to_install", return_value=True), \
             patch.object(sm, "get_service_status_details", side_effect=[("running", ""), ("stop_pending", ""), ("stopped", "")]), \
             patch.object(sm.subprocess, "run", return_value=Mock(returncode=0)) as command, \
             patch.object(sm.time, "sleep"):
            sm.set_owned_service_running(False)
        self.assertEqual(command.call_args.args[0], ["sc", "stop", "zapret"])

    def test_stopped_service_does_not_receive_stop_command(self):
        with patch.object(sm, "service_belongs_to_install", return_value=True), \
             patch.object(sm.subprocess, "run") as command:
            sm.set_owned_service_running(False)
        command.assert_not_called()

    def test_foreign_service_is_not_changed(self):
        with patch.object(sm, "service_belongs_to_install", return_value=False), \
             patch.object(sm.subprocess, "run") as command:
            with self.assertRaises(sm.ServiceError):
                sm.set_owned_service_running(False)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
