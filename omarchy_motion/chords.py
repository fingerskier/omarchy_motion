"""Stable two-hand commands with dwell, continuous tracking and release gating."""
from dataclasses import dataclass, field
from .asl import canonical_symbol


def description(binding):
    action, value = binding["action"], binding["value"]
    if action == "workspace":
        return f"Workspace {value}"
    if action == "move_window":
        return f"Move window to {value}"
    if action == "fullscreen":
        return "Fullscreen" if value else "Restore fullscreen"
    return "Floating" if value else "Tiled"


@dataclass
class ChordResult:
    suppress: bool = False
    events: list = field(default_factory=list)
    text: str = ""
    progress: float = 0


class ChordEngine:
    def __init__(self, config):
        self.c = config
        self.candidate = None
        self.since = None
        self.last = None
        self.latched = False
        self.released = None

    def step(self, right, left, left_present, now):
        left = canonical_symbol(left)
        gap = self.last is not None and now - self.last > self.c["chord_gap"]
        self.last = now
        binding = next((b for b in self.c["chords"] if left_present and b["enabled"] and b["right"] == right and canonical_symbol(b["left"]) == left), None)
        command = any(b["enabled"] and b["right"] == right for b in self.c["chords"])
        engaged = command and left_present
        text = f"R: {right or '?'}  L: {left or '?'}"
        if self.latched:
            if not engaged:
                self.released = now if self.released is None or gap else self.released
                if now - self.released >= self.c["chord_release"]:
                    self.latched = False
                    self.candidate = None
                    self.since = None
                    return ChordResult(text=text)
            else:
                self.released = None
            return ChordResult(True, text=text + " | Release command hand to rearm")
        if not binding:
            self.candidate, self.since = None, None
            return ChordResult(engaged, text=text + (" | Show a mapped number" if engaged else ""))
        key = (right, left)
        if gap or key != self.candidate:
            self.candidate, self.since = key, now
        progress = min(1, (now - self.since) / self.c["chord_hold"])
        text += " -> " + description(binding)
        if progress >= 1:
            self.latched, self.released = True, None
            return ChordResult(True, [(binding["action"], binding["value"])], text + " | Sent", 1)
        return ChordResult(True, text=text + " | Hold", progress=progress)
