import errno
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

from omarchy_motion.pointer import VirtualPointer


class PointerTest(unittest.TestCase):
    def pointer(self):
        p = VirtualPointer.__new__(VirtualPointer)
        p.pointer, p.display = MagicMock(), MagicMock()
        p.width, p.height = 960, 540
        p.closed, p.failure = False, None
        p._sync = MagicMock()
        return p

    def test_click_queues_complete_press_release_before_sync(self):
        p = self.pointer()
        with patch.object(p, "timestamp", return_value=42):
            p.click()
        self.assertEqual(p.pointer.mock_calls, [call.button(42, 272, 1), call.frame(), call.button(42, 272, 0), call.frame()])
        p._sync.assert_called_once()
        # If acknowledgement fails, both states have already been queued.
        p._sync.side_effect = TimeoutError("stalled")
        with self.assertRaises(TimeoutError):
            p.click()
        self.assertEqual(p.pointer.button.call_args.args[2], 0)

    def test_normalized_motion_maps_to_output_and_clamps_edges(self):
        p = self.pointer()
        with patch.object(p, "timestamp", return_value=42):
            p.move((-1, 2))
        p.pointer.motion_absolute.assert_called_once_with(42, 0, 539, 960, 540)
        with self.assertRaises(ValueError):
            p.move((float("nan"), 0))

    def test_close_is_idempotent_and_disallows_more_input(self):
        p = self.pointer()
        p.close()
        p.close()
        p.display.disconnect.assert_called_once()
        with self.assertRaises(RuntimeError):
            p.click()
        with self.assertRaises(RuntimeError):
            p.move((0, 0))

    def test_timestamp_wraps_to_protocol_uint32(self):
        with patch("omarchy_motion.pointer.time.monotonic", return_value=(2**32 + 5) / 1000):
            self.assertEqual(VirtualPointer.timestamp(), 5)

    def test_registry_binds_selected_output_and_missing_protocol_cleans_up(self):
        for advertised, output in ((True, "DP-1"), (False, "DP-1"), (True, "missing")):
            with self.subTest(advertised=advertised, output=output):
                display = MagicMock()
                registry = display.get_registry.return_value
                registry.dispatcher = {}
                manager, monitor = MagicMock(), MagicMock()
                monitor.dispatcher = {}
                registry.bind.side_effect = lambda name, iface, version: manager if name == 10 else monitor
                interfaces = SimpleNamespace(WlOutput=SimpleNamespace(name="wl_output"))
                extension = SimpleNamespace(ZwlrVirtualPointerManagerV1=SimpleNamespace(name="zwlr_virtual_pointer_manager_v1"))

                def sync(p):
                    if not p.outputs:
                        if advertised:
                            registry.dispatcher["global"](registry, 10, extension.ZwlrVirtualPointerManagerV1.name, 2)
                        registry.dispatcher["global"](registry, 20, "wl_output", 4)
                        monitor.dispatcher["name"](monitor, "DP-1")

                with patch.dict(sys.modules, {"pywayland.client": SimpleNamespace(Display=lambda: display),
                                              "pywayland.protocol.wayland": interfaces,
                                              "omarchy_motion.protocols.wlr_virtual_pointer_unstable_v1": extension}), \
                     patch.object(VirtualPointer, "_sync", sync):
                    if not advertised or output == "missing":
                        with self.assertRaises(RuntimeError):
                            VirtualPointer(output, 1920, 1080)
                        display.disconnect.assert_called_once()
                        manager.create_virtual_pointer_with_output.assert_not_called()
                    else:
                        p = VirtualPointer(output, 1920, 1080)
                        manager.create_virtual_pointer_with_output.assert_called_once_with(None, monitor)
                        registry.dispatcher["global_remove"](registry, 20)
                        self.assertIn("removed", p.failure)
                        p.close()

    def test_roundtrip_is_bounded_and_destroys_callback(self):
        p = self.pointer()
        del p._sync
        p._flush = MagicMock()
        callback = p.display.sync.return_value
        callback.dispatcher = {}
        with patch("omarchy_motion.pointer.select.select", return_value=([], [], [])):
            with self.assertRaises(TimeoutError):
                p._sync()
        callback.destroy.assert_called_once()

    def test_backpressure_timeout_is_reported(self):
        p = self.pointer()
        p.display.flush.return_value = -1
        with patch.dict(sys.modules, {"pywayland": SimpleNamespace(ffi=SimpleNamespace(errno=errno.EAGAIN))}), \
             patch("omarchy_motion.pointer.select.select", return_value=([], [], [])):
            with self.assertRaises(TimeoutError):
                p._flush(0)
