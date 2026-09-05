"""Pure landmark-to-action state machine; no camera or desktop dependencies."""
from collections import deque
from dataclasses import dataclass, field
from math import dist
from .asl import Recognizer, features
from .chords import ChordEngine, ChordResult


@dataclass
class Observation:
    hands: dict  # anatomical hand name -> 21 (x, y) landmarks
    pose: list  # 33 (x, y, visibility) landmarks, or []
    shapes: dict = field(default_factory=dict)  # aspect-correct image landmarks for ASL


class GestureEngine:
    def __init__(self, config):
        self.c = config
        self.pinched = {}
        self.history = {}
        self.previous = set()
        self.last_fire = {}
        self.cursor = None
        self.recognizer = Recognizer(config["asl_samples"])
        self.chords = ChordEngine(config)
        self.chord_status = ChordResult()
        self.symbols = {}

    def step(self, obs, now):
        events = self._legacy_step(obs, now)
        self.symbols = {hand: self.recognizer.predict(features(points), hand)
                        for hand, points in (obs.shapes or obs.hands).items()}
        if not self.c["chords_enabled"]:
            self.chord_status = ChordResult()
            return events
        self.chord_status = self.chords.step(
            self.symbols.get("Right").symbol if "Right" in self.symbols else None,
            self.symbols.get("Left").symbol if "Left" in self.symbols else None,
            "Left" in obs.hands, now)
        if self.chord_status.suppress:
            self.cursor = None
            return self.chord_status.events
        return events

    def _legacy_step(self, obs, now):
        active, positions = set(), {}
        for hand in ("Left", "Right"):
            p = obs.hands.get(hand)
            if p is None:
                self.pinched.pop(hand, None)
                self.history.pop(hand, None)
                continue
            scale = max(dist(p[0], p[9]), 0.001)
            pinch = dist(p[4], p[12]) / scale
            threshold = self.c["pinch_release"] if self.pinched.get(hand) else self.c["pinch_threshold"]
            self.pinched[hand] = pinch < threshold
            if self.pinched[hand]:
                active.add((hand, "pinch"))
            extended = lambda tip, pip: dist(p[tip], p[0]) > dist(p[pip], p[0]) * 1.15
            pointing = extended(8, 6) and not extended(16, 14) and not extended(20, 18)
            if pointing and not self.pinched[hand]:
                active.add((hand, "point"))
                positions[hand] = p[8]
            # Require an open hand for swipes so normal pointing/pinching won't move windows.
            open_hand = all(extended(t, t - 2) for t in (8, 12, 16, 20)) and not self.pinched[hand]
            history = self.history.setdefault(hand, deque())
            if not open_hand:
                history.clear()
            else:
                while history and now - history[0][0] > self.c["swipe_seconds"]:
                    history.popleft()
                history.append((now, p[0]))
                start = history[0][1]
                dx, dy = p[0][0] - start[0], p[0][1] - start[1]
                if abs(dx) >= self.c["swipe_distance"] and abs(dx) > 2 * abs(dy):
                    active.add((hand, "swipe_right" if dx > 0 else "swipe_left"))
                    history.clear()
        if obs.pose:
            for hand, wrist, shoulder in (("Left", 15, 11), ("Right", 16, 12)):
                w, s = obs.pose[wrist], obs.pose[shoulder]
                if min(w[2], s[2]) >= self.c["confidence"] and w[1] < s[1] - 0.08:
                    active.add((hand, "hand_raised"))
        events = []
        pointing_now = False
        for b in self.c["bindings"]:
            key = (b["hand"], b["gesture"])
            if not b["enabled"] or key not in active:
                continue
            if b["action"] == "cursor":
                pointing_now = True
                margin = self.c["cursor_margin"]
                xy = tuple(max(0, min(1, (v - margin) / (1 - 2 * margin))) for v in positions[b["hand"]])
                a = self.c["smoothing"]
                self.cursor = xy if self.cursor is None else tuple(a * v + (1 - a) * old for v, old in zip(xy, self.cursor))
                events.append(("cursor", self.cursor))
            elif key not in self.previous and now - self.last_fire.get(b["name"], -float("inf")) >= b["cooldown"]:
                self.last_fire[b["name"]] = now
                events.append((b["action"], None))
        if not pointing_now:
            self.cursor = None
        self.previous = active
        return events
