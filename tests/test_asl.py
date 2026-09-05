import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from omarchy_motion import asl, calibration, config
from omarchy_motion.backend import Hyprland
from omarchy_motion.chords import ChordEngine
from omarchy_motion.gestures import GestureEngine, Observation
from test_motion import hand


def vector(up=(), thumb=False, thumb_x=0.5, contacts=None):
    return ([1 if i in up else 0.2 for i in range(4)]
            + [1.5 if i in up else 0.8 for i in range(4)]
            + (contacts or [2] * 4) + [-0.5 if thumb else thumb_x, 2 if thumb else 0.8, 1, 1])


class RecognitionTest(unittest.TestCase):
    def test_rounded_o_is_zero_without_requiring_tightly_folded_fingers(self):
        rounded = [0.75] * 4 + [1.04] * 4 + [0.15, 0.4, 0.6, 0.75] + [0.3, 0.8, 0.7, 0.6]
        self.assertEqual(asl.Recognizer().predict(rounded, "Left").symbol, "0")
        self.assertIsNone(asl.Recognizer().predict(rounded, "Right").symbol)
        open_c = rounded.copy()
        open_c[8] = 0.6
        self.assertIsNone(asl.rule(open_c, "Left"))
        spread = rounded.copy()
        spread[-1] = 1.1
        self.assertIsNone(asl.rule(spread, "Left"))
        self.assertEqual(asl.rule(vector(range(4)), "Left"), "4")
        self.assertEqual(asl.rule(vector((1, 2, 3), contacts=[0.1, 2, 2, 2]), "Left"), "9")

    def test_o_and_zero_templates_are_one_class_not_ambiguous_competitors(self):
        v = vector()
        recognizer = asl.Recognizer({"Left": {"0": [v], "O": [v], "o": [v]}})
        self.assertEqual(recognizer.predict(v, "Left"), asl.Prediction("0", "calibrated"))
        recognizer.samples["Left"]["9"] = [v]
        self.assertIsNone(recognizer.predict(v, "Left").symbol)

    def test_command_rules(self):
        for symbol, v in (("W", vector((0, 1, 2))), ("M", vector(thumb_x=0.9)),
                          ("T", vector(thumb_x=0.2)), ("F", vector((1, 2, 3), contacts=[0.1, 2, 2, 2]))):
            with self.subTest(symbol=symbol):
                self.assertEqual(asl.Recognizer().predict(v, "Right").symbol, symbol)
        self.assertIsNone(asl.rule(vector(), "Right"))

    def test_digit_rules_and_hand_roles(self):
        zero = vector(contacts=[0.2] * 4)
        zero[-1] = 0.3
        values = [zero, vector((0,)), vector((0, 1)), vector((0, 1), thumb=True),
                  vector(range(4)), vector(range(4), thumb=True)]
        for touched in (3, 2, 1, 0):
            values.append(vector(tuple(i for i in range(4) if i != touched),
                                 contacts=[0.1 if i == touched else 2 for i in range(4)]))
        for n, v in enumerate(values):
            with self.subTest(digit=n):
                self.assertEqual(asl.rule(v, "Left"), str(n))
        self.assertIsNone(asl.rule(values[3], "Right"))
        self.assertEqual(asl.rule(values[9], "Right"), "F")

    def test_feature_invariance_and_invalid_landmarks(self):
        points = [(i * 0.03, (i % 4) * 0.07) for i in range(21)]
        expected = asl.features(points)
        for changed in ([(3 + y * 4, 2 - x * 4) for x, y in points], [(-x, y) for x, y in points]):
            for a, b in zip(expected, asl.features(changed)):
                self.assertAlmostEqual(a, b)
        for invalid in ([], [(0, 0)] * 21, [(float("nan"), 0)] * 21, [(0, 0, 0)] + [(1, 1)] * 20):
            self.assertIsNone(asl.features(invalid))

    def test_templates_override_rules_and_reject_ambiguous_or_distant_samples(self):
        v = vector(thumb_x=0.2)
        recognizer = asl.Recognizer({"Right": {"M": [v]}})
        self.assertEqual(recognizer.predict(v, "Right"), asl.Prediction("M", "calibrated"))
        recognizer.samples["Right"]["T"] = [v]
        self.assertIsNone(recognizer.predict(v, "Right").symbol)
        recognizer.samples = {"Right": {"T": [vector(range(4), thumb=True)]}}
        self.assertIsNone(recognizer.predict(v, "Right").symbol)
        self.assertIsNone(recognizer.predict(None, "Left").symbol)


class ChordTest(unittest.TestCase):
    def setUp(self):
        self.c = config.defaults()
        self.engine = ChordEngine(self.c)

    def hold(self, right="W", left="3", start=0):
        return [self.engine.step(right, left, True, start + i * 0.1) for i in range(7)]

    def test_zero_alias_changes_preserve_dwell_and_do_not_repeat(self):
        for right, expected in (("W", ("workspace", 10)), ("M", ("move_window", 10)),
                                ("F", ("fullscreen", 0)), ("T", ("floating", 0))):
            self.engine = ChordEngine(self.c)
            results = [self.engine.step(right, ("0", "O", "o")[i % 3], True, i * 0.1) for i in range(15)]
            self.assertEqual([e for r in results for e in r.events], [expected])

    def test_dwell_fires_once_and_requires_release_before_changed_digit(self):
        result = self.hold()
        self.assertTrue(all(r.suppress for r in result))
        self.assertEqual([e for r in result for e in r.events], [("workspace", 3)])
        self.assertIn("Hold", result[1].text)
        self.assertAlmostEqual(result[1].progress, 0.2)
        self.assertEqual([e for r in self.hold(left="4", start=0.7) for e in r.events], [])
        for i in range(5):
            self.engine.step(None, None, False, 1.4 + i * 0.1)
        self.assertEqual([e for r in self.hold("M", "4", 1.9) for e in r.events], [("move_window", 4)])

    def test_gaps_and_unknown_digits_reset_pending_hold(self):
        self.engine.step("W", "3", True, 0)
        self.assertFalse(self.engine.step("W", "3", True, 1).events)
        self.engine.step("W", None, True, 1.1)
        self.assertFalse(self.engine.step("W", "3", True, 1.2).events)
        self.assertFalse(self.engine.step("W", "3", False, 1.3).suppress)

    def test_brief_loss_and_unobserved_time_do_not_rearm(self):
        self.hold()
        self.engine.step(None, None, False, 0.7)
        self.engine.step(None, None, False, 2)
        self.assertEqual([e for r in self.hold(start=2.1) for e in r.events], [])

    def test_all_default_actions_zero_workspace_and_disabled_chords(self):
        for b in self.c["chords"]:
            self.engine = ChordEngine(self.c)
            events = [e for r in self.hold(b["right"], b["left"]) for e in r.events]
            self.assertEqual(events, [(b["action"], b["value"])])
        self.assertEqual(self.c["chords"][0]["value"], 10)
        for b in self.c["chords"]:
            b["enabled"] = False
        self.engine = ChordEngine(self.c)
        self.assertTrue(all(not r.suppress and not r.events for r in self.hold()))
        self.assertTrue(all(not r.suppress and not r.events for r in self.hold("3", "W", 1)))

    def test_chords_suppress_clicks_and_pointer_without_delayed_click(self):
        engine = GestureEngine(self.c)
        obs = Observation({"Right": hand(pinch=0.1), "Left": hand()}, [])
        with patch.object(engine.recognizer, "predict", side_effect=lambda v, h: asl.Prediction("W" if h == "Right" else "3")):
            self.assertEqual(engine.step(obs, 0), [])
            for i in range(1, 7):
                events = engine.step(obs, i * 0.1)
                self.assertNotIn("click", [a for a, _ in events])
        with patch.object(engine.recognizer, "predict", return_value=asl.Prediction()):
            for i in range(7, 13):
                self.assertEqual(engine.step(obs, i * 0.1), [])
            self.assertEqual(engine.step(Observation({"Right": hand()}, []), 1.3)[0][0], "cursor")
            self.assertEqual(engine.step(Observation({"Right": hand(pinch=0.1)}, []), 1.4), [("click", None)])


class ChordConfigTest(unittest.TestCase):
    def test_o_mapping_normalizes_without_mutating_input_and_duplicate_pair_rejected(self):
        c = config.defaults()
        c["chords"][0]["left"] = "O"
        normalized = config.validate(c)
        self.assertEqual(normalized["chords"][0]["left"], "0")
        self.assertEqual(c["chords"][0]["left"], "O")
        c["chords"].append(c["chords"][0] | {"name": "Duplicate zero", "left": "0"})
        with self.assertRaisesRegex(ValueError, "only one mapping"):
            config.validate(c)
        with self.assertRaises(ValueError):
            config.validate(config.defaults() | {"asl_samples": {"Right": {"O": [vector()]}}})

    def test_alias_calibration_profiles_merge_into_zero_and_roundtrip(self):
        first, second = vector(), vector(thumb=True)
        c = config.defaults() | {"asl_samples": {"Left": {"0": [first], "O": [first, second]}, "Right": {"M": [first, first]}}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            config.save(c, path)
            loaded = config.read(path)
        self.assertEqual(loaded["asl_samples"], {"Left": {"0": [first, second]}, "Right": {"M": [first, first]}})
        self.assertIn("O", c["asl_samples"]["Left"])

    def test_defaults_legacy_compatibility_and_invalid_data(self):
        c = config.defaults()
        self.assertEqual(len(c["chords"]), 24)
        self.assertFalse(any(b["gesture"].startswith("swipe") for b in c["bindings"]))
        old = {k: v for k, v in c.items() if not k.startswith("chord") and k != "asl_samples"}
        self.assertEqual(config.validate(old), c)
        invalid = [c | {"chord_hold": 0}, c | {"chords_enabled": 1}, c | {"chords": c["chords"] * 2},
                   c | {"chords": [c["chords"][0] | {"value": "3"}]},
                   c | {"chords": [c["chords"][-1] | {"value": 2}]},
                   c | {"asl_samples": {"Left": {"W": [vector()]}}},
                   c | {"asl_samples": {"Right": {"M": [[float("nan")] * 16]}}}]
        for candidate in invalid:
            with self.assertRaises(ValueError):
                config.validate(candidate)

    def test_settings_merge_preserves_external_tuning_and_samples(self):
        base = config.defaults()
        latest = copy.deepcopy(base)
        latest.update(swap_hands=True, dry_run=True, asl_samples={"Right": {"M": [vector()]}})
        edited = base | {"chord_hold": 0.8}
        merged = config.merge_edits(base, edited, latest)
        self.assertEqual(merged, latest | {"chord_hold": 0.8})
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            config.merge_edits(base, edited, latest | {"chord_hold": 1})


class CalibrationTest(unittest.TestCase):
    def test_o_capture_is_saved_as_zero_and_preserves_existing_sample(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_RUNTIME_DIR": d, "XDG_CONFIG_HOME": d}):
            c = config.defaults() | {"asl_samples": {"Left": {"0": [vector(thumb=True)]}}}
            config.save(c)
            calibration.request("Left", "o")
            self.assertEqual(json.loads(calibration.path("request").read_text())["symbol"], "0")
            recognizer, capture = asl.Recognizer(), calibration.Capture()
            for i in range(33):
                capture.step({"Left": vector()}, i * 0.1, c, recognizer)
            self.assertEqual(set(config.read()["asl_samples"]["Left"]), {"0"})
            self.assertEqual(len(config.read()["asl_samples"]["Left"]["0"]), 2)
            self.assertEqual(recognizer.predict(vector(), "Left").symbol, "0")
            with self.assertRaises(ValueError):
                calibration.request("Right", "O")

    def test_capture_countdown_save_and_live_recognizer_update(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_RUNTIME_DIR": d, "XDG_CONFIG_HOME": d}):
            calibration.request("Right", "M")
            c, recognizer, capture = config.defaults(), asl.Recognizer(), calibration.Capture()
            for i in range(33):
                blocked = capture.step({"Right": vector()}, i * 0.1, c, recognizer)
                if i < 30:
                    self.assertTrue(blocked)
            saved = config.read()
            self.assertEqual(len(saved["asl_samples"]["Right"]["M"]), 1)
            self.assertEqual(recognizer.samples, saved["asl_samples"])
            self.assertIn("Saved Right M", calibration.status())
            self.assertTrue(capture.step({"Right": vector()}, 4, c, recognizer))
            for i in range(5):
                blocked = capture.step({}, 4.1 + i * 0.1, c, recognizer)
            self.assertFalse(blocked)
            self.assertFalse(calibration.path("request").exists())

    def test_lost_tracking_and_motion_prevent_capture_and_request_expires(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"XDG_RUNTIME_DIR": d, "XDG_CONFIG_HOME": d}):
            with self.assertRaises(ValueError):
                calibration.request("Left", "M")
            calibration.write("request", {"hand": "Right", "symbol": "M", "created": 0})
            c, recognizer, capture = config.defaults(), asl.Recognizer(), calibration.Capture()
            self.assertFalse(capture.step({}, 0, c, recognizer))
            calibration.request("Right", "M")
            for i in range(1, 180):
                capture.step({"Right": vector()} if i % 2 else {}, i * 0.1, c, recognizer)
            self.assertEqual(config.read()["asl_samples"], {})
            self.assertIn("timed out", calibration.status())


class ChordBackendTest(unittest.TestCase):
    @patch("omarchy_motion.backend.VirtualPointer")
    @patch("omarchy_motion.backend.request")
    def test_lua_provider_syntax_rejection_retries_and_caches_protocol(self, request, pointer):
        request.return_value = json.dumps([{"name": "DP-1", "focused": True, "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1}])
        backend = Hyprland()
        request.side_effect = ["syntax error: dispatch in lua is a shorthand for hl.dispatch(...)", "ok"]
        self.assertTrue(backend.dispatch("workspace", 3))
        request.assert_called_with('dispatch hl.dsp.focus({ workspace = "3" })')
        request.side_effect = None
        request.return_value = "ok"
        for action, value, expected in (("move_window", 4, 'hl.dsp.window.move({ workspace = "4", follow = false })'),
                                       ("fullscreen", 1, 'hl.dsp.window.fullscreen_state({ internal = 2, client = 2, action = "set" })'),
                                       ("fullscreen", 0, 'hl.dsp.window.fullscreen_state({ internal = 0, client = 0, action = "set" })'),
                                       ("floating", 1, 'hl.dsp.window.float({ action = "enable" })'),
                                       ("floating", 0, 'hl.dsp.window.float({ action = "disable" })'),
                                       ("toggle_floating", None, 'hl.dsp.window.float({ action = "toggle" })')):
            self.assertTrue(backend.dispatch(action, value))
            request.assert_called_with("dispatch " + expected)
        request.reset_mock()
        request.return_value = "Window not found"
        with patch("builtins.print"):
            self.assertFalse(backend.dispatch("move_window", 4))
        self.assertEqual(request.call_count, 1)
        backend.close()

    @patch("omarchy_motion.backend.VirtualPointer")
    @patch("omarchy_motion.backend.request")
    def test_parameterized_dispatches(self, request, pointer):
        request.return_value = json.dumps([{"name": "DP-1", "focused": True, "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1}])
        backend = Hyprland()
        request.return_value = "ok"
        for action, value, expected in (("workspace", 3, "workspace 3"), ("move_window", 10, "movetoworkspacesilent 10"),
                                       ("fullscreen", 1, "fullscreenstate 2 2"), ("fullscreen", 0, "fullscreenstate 0 0"),
                                       ("floating", 1, "setfloating active"), ("floating", 0, "settiled active")):
            self.assertTrue(backend.dispatch(action, value))
            request.assert_called_with("dispatch " + expected)
        for action, value in (("workspace", "3"), ("workspace", 0), ("move_window", 11), ("fullscreen", 2), ("floating", True)):
            with self.assertRaises(ValueError):
                backend.dispatch(action, value)
        backend.close()
