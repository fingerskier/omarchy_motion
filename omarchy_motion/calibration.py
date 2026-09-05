"""Service-owned calibration: short stable captures, numeric features only."""
import json
import os
from pathlib import Path
import tempfile
import time

from . import config
from .asl import COMMANDS, DIGITS, canonical_symbol, feature_distance


def path(kind):
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / f"omarchy-motion-calibration-{kind}.json"


def write(kind, data):
    target = path(kind)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as f:
            name = f.name
            json.dump(data, f)
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def request(hand, symbol):
    symbol = canonical_symbol(symbol) if hand == "Left" else symbol
    if hand not in ("Left", "Right") or symbol not in (COMMANDS if hand == "Right" else DIGITS):
        raise ValueError("Choose W/M/F/T for Right or 0–9 (O = zero) for Left")
    write("request", {"hand": hand, "symbol": symbol, "created": time.time()})
    write("status", {"text": f"Waiting to calibrate {hand} {symbol}…"})


def status():
    try:
        return json.loads(path("status").read_text()).get("text", "")
    except (OSError, ValueError):
        return ""


class Capture:
    def __init__(self):
        self.active = None
        self.started = 0
        self.last_poll = -1
        self.samples = []
        self.text = ""
        self.until = 0
        self.completed = False
        self.releasing = False
        self.release_since = None
        self.last_frame = None

    def message(self, text):
        if self.text != text:
            self.text = text
            write("status", {"text": text})

    def step(self, vectors, now, c, recognizer):
        """Return True while desktop actions must be suppressed."""
        self.completed = False
        gap = self.last_frame is not None and now - self.last_frame > c["chord_gap"]
        self.last_frame = now
        if now - self.last_poll >= 0.25:
            self.last_poll = now
            try:
                data = json.loads(path("request").read_text())
                path("request").unlink()
                hand, symbol = data["hand"], data["symbol"]
                symbol = canonical_symbol(symbol) if hand == "Left" else symbol
                if (0 <= time.time() - data["created"] < 30 and hand in ("Left", "Right")
                        and symbol in (COMMANDS if hand == "Right" else DIGITS)):
                    self.active, self.started, self.samples = (hand, symbol), now, []
                    self.releasing, self.release_since = False, None
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if not self.active:
            if self.releasing:
                if vectors:
                    self.release_since = None
                else:
                    self.release_since = now if self.release_since is None or gap else self.release_since
                    if now - self.release_since >= c["chord_release"]:
                        self.releasing = False
                if self.releasing:
                    return True
            if now > self.until:
                self.text = ""
            return False
        hand, symbol = self.active
        elapsed = now - self.started
        if elapsed < 2:
            self.message(f"Calibration: show {hand} {symbol} in {2 - int(elapsed)}s")
        elif elapsed > 15:
            self.message("Calibration timed out. Lower both hands, then try again.")
            self.active, self.until, self.completed = None, now + 4, True
            self.releasing = True
        else:
            vector = vectors.get(hand)
            if vector is None or (self.samples and (now - self.samples[-1][0] > c["chord_gap"]
                                                    or feature_distance(vector, self.samples[0][1]) > 0.06)):
                self.samples = []
            if vector is not None:
                self.samples.append((now, vector))
            self.message(f"Calibration: hold {hand} {symbol} still for one second")
            if len(self.samples) >= 8 and now - self.samples[0][0] >= 1:
                average = [sum(v[i] for _, v in self.samples) / len(self.samples) for i in range(len(vector))]
                try:
                    latest = config.read()
                    samples = latest["asl_samples"].setdefault(hand, {}).setdefault(symbol, [])
                    samples.append(average)
                    del samples[:-5]
                    config.save(latest)
                    c["asl_samples"] = latest["asl_samples"]
                    recognizer.samples = latest["asl_samples"]
                    self.message(f"Saved {hand} {symbol}. Lower both hands out of view to resume control.")
                except (OSError, ValueError) as e:
                    self.message(f"Calibration could not save: {e}")
                self.active, self.until, self.completed = None, now + 4, True
                self.releasing = True
        return True
