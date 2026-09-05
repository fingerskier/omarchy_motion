import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from types import SimpleNamespace
import signal

from omarchy_motion import backend, config, service
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

    def test_parse_field_uses_canonical_types(self):
        self.assertEqual(config.parse_field("smoothing", "0.3"), 0.3)
        self.assertEqual(config.parse_field("fps", "30"), 30)
        self.assertEqual(config.parse_field("monitor", "DP-1"), "DP-1")
        for key, text in (("fps", "24.5"), ("confidence", "high")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                config.parse_field(key, text)


class BackendTest(unittest.TestCase):
    def test_monitor_scale_rotation_and_offset(self):
        self.assertEqual(monitor_geometry({"x": -1080, "y": 50, "width": 3840, "height": 2160, "scale": 2, "transform": 1}), (-1080, 50, 1080, 1920))

    @patch("omarchy_motion.backend.request")
    def test_dispatch_coordinates_and_actions(self, request):
        request.return_value = json.dumps([{"name": "DP-1", "focused": True, "x": -960, "y": 0, "width": 1920, "height": 1080, "scale": 2}])
        hypr = Hyprland()
        request.assert_called_with("j/monitors")
        request.return_value = "ok"
        self.assertTrue(hypr.dispatch("cursor", (0, 1)))
        request.assert_called_with("dispatch movecursor -960 539")
        hypr.dispatch("click", None)
        request.assert_called_with("dispatch sendshortcut , mouse:272,")
        hypr.dispatch("window_left", None)
        request.assert_called_with("dispatch movetoworkspacesilent r-1")

    @patch("omarchy_motion.backend.request")
    def test_rejected_dispatch_is_logged_once_not_fatal(self, request):
        request.return_value = json.dumps([{"name": "DP-1", "focused": True, "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1}])
        hypr = Hyprland()
        request.return_value = "Window not found"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertFalse(hypr.dispatch("window_left", None))
            self.assertFalse(hypr.dispatch("window_left", None))
            request.return_value = "ok"
            self.assertTrue(hypr.dispatch("click", None))
            request.return_value = "Window not found"
            self.assertFalse(hypr.dispatch("toggle_floating", None))
        self.assertEqual(err.getvalue().count("Window not found"), 2)
        self.assertIn("rejected movetoworkspacesilent", err.getvalue())

    @patch("omarchy_motion.backend.request")
    def test_dry_run_never_contacts_desktop(self, request):
        hypr = Hyprland(dry_run=True)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            hypr.dispatch("cursor", (1, 1))
            hypr.dispatch("click", None)
        request.assert_not_called()
        self.assertEqual(out.getvalue(), "Gesture action: click\n")

    def test_socket_request_and_instance_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hypr/abc/.socket.sock"
            path.parent.mkdir(parents=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            server.listen(1)
            seen = []

            def serve():
                conn, _ = server.accept()
                with conn:
                    seen.append(conn.recv(1024))
                    conn.sendall(b"ok\n")

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            with patch.dict("os.environ", {"XDG_RUNTIME_DIR": d, "HYPRLAND_INSTANCE_SIGNATURE": "abc"}):
                self.assertEqual(backend.request("dispatch movecursor 1 2"), "ok")
            thread.join(2)
            server.close()
            self.assertEqual(seen, [b"dispatch movecursor 1 2"])
            with patch.dict("os.environ", {"XDG_RUNTIME_DIR": d}, clear=True):
                self.assertEqual(backend.socket_path(), path)
                (path.parent.parent / "def").mkdir()
                (path.parent.parent / "def/.socket.sock").touch()
                with self.assertRaisesRegex(RuntimeError, "Several"):
                    backend.socket_path()
            with patch.dict("os.environ", {"XDG_RUNTIME_DIR": d, "HYPRLAND_INSTANCE_SIGNATURE": "missing"}):
                with self.assertRaisesRegex(RuntimeError, "not found"):
                    backend.socket_path()

    @patch("omarchy_motion.service.subprocess.run")
    def test_toggle_during_startup_stops(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "activating\n", "")
        service.control("toggle")
        self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "stop", service.UNIT])


class RuntimeTest(unittest.TestCase):
    def exercise(self, stop_during_read=False, bindings=None, hand_frames=None):
        from omarchy_motion import runtime
        cv = MagicMock()
        mp = MagicMock()
        cap = cv.VideoCapture.return_value
        cap.isOpened.return_value = True
        handlers = {}
        frames = list(hand_frames or [])

        def install_handler(sig, fn):
            handlers[sig] = fn
            return signal.SIG_DFL

        def capture():
            if frames:
                return True, MagicMock()
            if stop_during_read:
                handlers[signal.SIGTERM]()
                return True, MagicMock()
            return False, None

        cap.read.side_effect = capture
        hand_detector = mp.tasks.vision.HandLandmarker.create_from_options.return_value.__enter__.return_value

        def detect(image, timestamp):
            if frames:
                return frames.pop(0)
            return SimpleNamespace(handedness=[], hand_landmarks=[])

        hand_detector.detect_for_video.side_effect = detect
        pose_detector = mp.tasks.vision.PoseLandmarker.create_from_options.return_value.__enter__.return_value
        pose_detector.detect_for_video.return_value = SimpleNamespace(pose_landmarks=[])
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "model.task"
            model.touch()
            c = config.defaults() | {"hand_model": str(model), "pose_model": str(model)}
            if bindings is not None:
                c["bindings"] = bindings
            observations = []

            def step(self, obs, now):
                observations.append(obs)
                return [("click", None)]

            with patch.dict("sys.modules", {"cv2": cv, "mediapipe": mp}), \
                 patch.dict("os.environ", {"XDG_RUNTIME_DIR": d}), \
                 patch.object(runtime.signal, "signal", side_effect=install_handler), \
                 patch.object(runtime, "Hyprland") as hypr, \
                 patch.object(runtime, "notify_ready") as ready, \
                 patch.object(runtime.GestureEngine, "step", step):
                if stop_during_read:
                    runtime.run(c)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Camera disconnected"):
                        runtime.run(c)
                if not hand_frames:
                    hypr.return_value.dispatch.assert_not_called()
                    ready.assert_not_called()
        cap.release.assert_called_once()
        mp.tasks.vision.HandLandmarker.create_from_options.return_value.__exit__.assert_called_once()
        return mp, observations

    def test_capture_failure_releases_camera_and_models(self):
        mp, _ = self.exercise()
        mp.tasks.vision.PoseLandmarker.create_from_options.assert_not_called()

    def test_stop_signal_prevents_actions_and_releases_camera(self):
        self.exercise(stop_during_read=True)

    def test_pose_model_only_loads_for_body_bindings(self):
        raise_hand = {"name": "Raise", "hand": "Left", "gesture": "hand_raised", "action": "toggle_floating", "cooldown": 1, "enabled": True}
        mp, _ = self.exercise(bindings=[raise_hand])
        mp.tasks.vision.PoseLandmarker.create_from_options.return_value.__exit__.assert_called_once()
        mp, _ = self.exercise(bindings=[raise_hand | {"enabled": False}])
        mp.tasks.vision.PoseLandmarker.create_from_options.assert_not_called()

    def test_duplicate_hand_labels_keep_the_confident_one(self):
        both_right = SimpleNamespace(
            handedness=[[SimpleNamespace(category_name="Right", score=0.7)], [SimpleNamespace(category_name="Right", score=0.9)]],
            hand_landmarks=[[SimpleNamespace(x=0.7, y=0.5)] * 21, [SimpleNamespace(x=0.9, y=0.5)] * 21])
        _, observations = self.exercise(hand_frames=[both_right])
        self.assertEqual(len(observations), 1)
        self.assertEqual(set(observations[0].hands), {"Right"})
        self.assertEqual(observations[0].hands["Right"][0], (0.9, 0.5))


if __name__ == "__main__":
    unittest.main()
