from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from omarchy_motion import config, panel


class PanelTest(unittest.TestCase):
    def test_private_snapshot_demand_expiry_and_shutdown(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_RUNTIME_DIR": d}):
            publisher = panel.Publisher()
            try:
                self.assertEqual(publisher.path.stat().st_mode & 0o777, 0o600)
                self.assertFalse(publisher.wanted(time.monotonic()))
                publisher.publish({"status": "Ready"}, time.monotonic(), b"jpeg-bytes")
                packet = panel.snapshot()
                self.assertTrue(packet["connected"])
                self.assertEqual(packet["status"], "Ready")
                self.assertEqual(packet["image"], "data:image/jpeg;base64,anBlZy1ieXRlcw==")
                self.assertTrue(publisher.wanted(time.monotonic()))
                self.assertFalse(publisher.wanted(publisher.requested + 0.6))
                self.assertEqual([p.name for p in Path(d).iterdir()], [publisher.path.name])
                # An idle/stalled worker must never supply its previous camera image.
                publisher.updated = time.monotonic() - 3
                self.assertEqual(panel.snapshot(), {"connected": False})
                publisher.publish({"status": "Hidden"}, time.monotonic())
                self.assertNotIn("image", panel.snapshot())
            finally:
                publisher.close()
            self.assertFalse(publisher.path.exists())
            self.assertFalse(publisher.thread.is_alive())
            self.assertEqual(publisher.packet, b"")
            with self.assertRaises(OSError):
                panel.snapshot()

    def test_invalid_request_does_not_subscribe_or_kill_server(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_RUNTIME_DIR": d}):
            publisher = panel.Publisher()
            try:
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(1)
                    sock.connect(str(panel.socket_path()))
                    sock.sendall(b"exec anything\n")
                    self.assertEqual(sock.recv(32), b"")
                self.assertEqual(publisher.requested, 0)
                publisher.publish({}, time.monotonic())
                self.assertTrue(panel.snapshot()["connected"])
            finally:
                publisher.close()

    def test_quick_setting_preserves_mappings_calibration_and_other_tuning(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_CONFIG_HOME": d}):
            original = config.defaults()
            original["swap_hands"] = True
            original["chords"][0]["enabled"] = False
            original["asl_samples"] = {"Left": {"0": [[0.5] * 16]}}
            config.save(original)
            panel.set_setting("dry_run", True)
            self.assertEqual(config.read(), original | {"dry_run": True})
            for key, value in (("camera", True), ("preview", "false"), ("chords", [])):
                with self.assertRaises(ValueError):
                    panel.set_setting(key, value)
            self.assertEqual(config.read(), original | {"dry_run": True})

    def test_cli_set_restarts_only_active_service(self):
        from omarchy_motion.cli import main
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_CONFIG_HOME": d}), \
                patch("sys.argv", ["omarchy-motion", "set", "chords_enabled", "false"]), \
                patch("omarchy_motion.service.state", return_value="active") as state, \
                patch("omarchy_motion.service.control") as control:
            self.assertEqual(main(), 0)
            self.assertFalse(config.read()["chords_enabled"])
            control.assert_called_once_with("restart")
            state.return_value = "inactive"
            control.reset_mock()
            self.assertEqual(main(), 0)
            control.assert_not_called()
