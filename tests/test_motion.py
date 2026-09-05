import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from types import SimpleNamespace
import signal

from omarchy_motion import config, service
from omarchy_motion.backend import Hyprland, monitor_geometry
from omarchy_motion.gestures import GestureEngine, Observation


def hand(shape="point", x=0.5, pinch=1):
    p = [(x, 0.7)] * 21
    p[0], p[9] = (x, 0.9), (x, 0.6)
    for tip in (8, 12, 16, 20):
        p[tip - 2] = (x, 0.6)
        p[tip] = (x, 0.2 if shape == "open" or tip == 8 else 0.7)
    p[4] = (p[12][0] + pinch * 0.3, p[12][1])
    return p


class GesturesTest(unittest.TestCase):
    def setUp(self):
        self.c = config.defaults()
        self.engine = GestureEngine(self.c)

    def step(self, points, time, side="Right", pose=None):
        return self.engine.step(Observation({side: points} if points else {}, pose or []), time)

    def test_pinch_hysteresis_and_one_click_per_hold(self):
        self.assertEqual(self.step(hand(pinch=0.2), 0), [("click", None)])
        self.assertEqual(self.step(hand(pinch=0.35), 1), [])
        self.assertEqual(self.step(hand(pinch=0.2), 2), [])
        self.step(hand(pinch=0.6), 3)
        self.assertEqual(self.step(hand(pinch=0.2), 4), [("click", None)])

    def test_cooldown_blocks_fast_click(self):
        self.step(hand(pinch=0.2), 0)
        self.step(hand(), 0.1)
        self.assertEqual(self.step(hand(pinch=0.2), 0.2), [])

    def test_disabled_binding_never_fires(self):
        self.c["bindings"][1]["enabled"] = False
        self.assertEqual(self.step(hand(pinch=0.1), 0), [])

    def test_pointing_smooths_and_clamps(self):
        a = self.step(hand(x=0.1), 0)[0][1]
        b = self.step(hand(x=0.9), 0.1)[0][1]
        self.assertEqual(a[0], 0)
        self.assertAlmostEqual(b[0], 0.3)
        self.step(None, 0.2)
        self.assertEqual(self.step(hand(x=1.2), 0.3)[0][1][0], 1)

    def test_swipes_use_hand_and_direction(self):
        for side, action in (("Left", "workspace"), ("Right", "window")):
            self.engine = GestureEngine(self.c)
            self.step(hand("open", x=0.8), 0, side)
            self.assertEqual(self.step(hand("open", x=0.4), 0.2, side), [(f"{action}_left", None)])

    def test_slow_movement_and_pointing_do_not_swipe(self):
        self.step(hand("open", x=0.8), 0)
        self.assertEqual(self.step(hand("open", x=0.3), 1), [])
        self.step(hand(x=0.8), 2)
        self.assertEqual([a for a, _ in self.step(hand(x=0.3), 2.1)], ["cursor"])

    def test_tracking_loss_clears_swipe_history(self):
        self.step(hand("open", x=0.8), 0)
        self.step(None, 0.1)
        self.assertEqual(self.step(hand("open", x=0.2), 0.2), [])

    def test_pose_requires_visibility_and_fires_on_rising_edge(self):
        self.c["bindings"] = [{"name": "Raise", "hand": "Left", "gesture": "hand_raised", "action": "toggle_floating", "cooldown": 1, "enabled": True}]
        pose = [(0.5, 0.5, 1)] * 33
        pose[15] = (0.5, 0.1, 0.2)
        self.assertEqual(self.step(None, 0, pose=pose), [])
        pose[15] = (0.5, 0.1, 1)
        self.assertEqual(self.step(None, 1, pose=pose), [("toggle_floating", None)])
        self.assertEqual(self.step(None, 3, pose=pose), [])


class ConfigTest(unittest.TestCase):
    def test_roundtrip_and_preserves_file_on_invalid_save(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            c = config.defaults()
            config.save(c, path)
            self.assertEqual(config.read(path), c)
            c["confidence"] = float("nan")
            with self.assertRaises(ValueError):
                config.save(c, path)
            self.assertEqual(config.read(path), config.defaults())

    def test_invalid_configurations(self):
        for key, value in (("fps", 0), ("mirror", "false"), ("camera", True), ("smoothing", float("inf")), ("pinch_release", 0.1), ("bindings", None), ("typo", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.validate(config.defaults() | {key: value})
        c = config.defaults()
        c["bindings"].append(copy.deepcopy(c["bindings"][0]))
        with self.assertRaises(ValueError):
            config.validate(c)
        c = config.defaults()
        c["bindings"][0]["action"] = "click"
        with self.assertRaises(ValueError):
            config.validate(c)


class BackendTest(unittest.TestCase):
    def test_monitor_scale_rotation_and_offset(self):
        self.assertEqual(monitor_geometry({"x": -1080, "y": 50, "width": 3840, "height": 2160, "scale": 2, "transform": 1}), (-1080, 50, 1080, 1920))

    @patch("omarchy_motion.backend.command")
    def test_dispatch_coordinates_and_actions(self, command):
        command.return_value = json.dumps([{"name": "DP-1", "focused": True, "x": -960, "y": 0, "width": 1920, "height": 1080, "scale": 2}])
        backend = Hyprland()
        command.return_value = "ok"
        backend.dispatch("cursor", (0, 1))
        command.assert_called_with("hyprctl", "dispatch", "movecursor", "-960 539")
        backend.dispatch("click", None)
        command.assert_called_with("hyprctl", "dispatch", "sendshortcut", ", mouse:272,")
        backend.dispatch("window_left", None)
        command.assert_called_with("hyprctl", "dispatch", "movetoworkspacesilent", "r-1")
        command.return_value = "Invalid dispatcher"
        with self.assertRaises(RuntimeError):
            backend.dispatch("click", None)

    @patch("omarchy_motion.backend.command")
    def test_dry_run_never_contacts_desktop(self, command):
        backend = Hyprland(dry_run=True)
        backend.dispatch("cursor", (1, 1))
        backend.dispatch("click", None)
        command.assert_not_called()

    @patch("omarchy_motion.service.subprocess.run")
    def test_toggle_during_startup_stops(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "activating\n", "")
        service.control("toggle")
        self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "stop", service.UNIT])


class RuntimeTest(unittest.TestCase):
    def exercise(self, stop_during_read=False):
        from omarchy_motion import runtime
        cv = MagicMock()
        mp = MagicMock()
        cap = cv.VideoCapture.return_value
        cap.isOpened.return_value = True
        handlers = {}

        def install_handler(sig, fn):
            handlers[sig] = fn
            return signal.SIG_DFL

        def capture():
            if stop_during_read:
                handlers[signal.SIGTERM]()
                return True, MagicMock()
            return False, None

        cap.read.side_effect = capture
        hand_detector = mp.tasks.vision.HandLandmarker.create_from_options.return_value.__enter__.return_value
        hand_detector.detect_for_video.return_value = SimpleNamespace(handedness=[], hand_landmarks=[])
        pose_detector = mp.tasks.vision.PoseLandmarker.create_from_options.return_value.__enter__.return_value
        pose_detector.detect_for_video.return_value = SimpleNamespace(pose_landmarks=[])
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "model.task"
            model.touch()
            c = config.defaults() | {"hand_model": str(model), "pose_model": str(model)}
            with patch.dict("sys.modules", {"cv2": cv, "mediapipe": mp}), \
                 patch.dict("os.environ", {"XDG_RUNTIME_DIR": d}), \
                 patch.object(runtime.signal, "signal", side_effect=install_handler), \
                 patch.object(runtime, "Hyprland") as backend, \
                 patch.object(runtime, "notify_ready") as ready, \
                 patch.object(runtime.GestureEngine, "step", return_value=[("click", None)]):
                if stop_during_read:
                    runtime.run(c)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Camera disconnected"):
                        runtime.run(c)
                backend.return_value.dispatch.assert_not_called()
                ready.assert_not_called()
        cap.release.assert_called_once()
        mp.tasks.vision.HandLandmarker.create_from_options.return_value.__exit__.assert_called_once()
        mp.tasks.vision.PoseLandmarker.create_from_options.return_value.__exit__.assert_called_once()

    def test_capture_failure_releases_camera_and_models(self):
        self.exercise()

    def test_stop_signal_prevents_actions_and_releases_camera(self):
        self.exercise(stop_during_read=True)


if __name__ == "__main__":
    unittest.main()
