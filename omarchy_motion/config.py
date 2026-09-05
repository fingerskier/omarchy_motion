"""Validated, atomically saved user configuration."""
import json
import math
import os
from pathlib import Path
import tempfile

GESTURES = ("point", "pinch", "swipe_left", "swipe_right", "hand_raised")
ACTIONS = ("cursor", "click", "workspace_left", "workspace_right",
           "window_left", "window_right", "toggle_floating")


def config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy-motion/config.json"


def model_dir():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "omarchy-motion/models"


def defaults():
    return {
        "camera": 0, "mirror": True, "swap_hands": False, "preview": False, "dry_run": False, "fps": 24,
        "width": 640, "height": 480, "monitor": "",
        "hand_model": str(model_dir() / "hand_landmarker.task"),
        "pose_model": str(model_dir() / "pose_landmarker_lite.task"),
        "confidence": 0.65, "smoothing": 0.3, "cursor_margin": 0.1,
        "pinch_threshold": 0.3, "pinch_release": 0.45,
        "swipe_distance": 0.22, "swipe_seconds": 0.5,
        "bindings": [
            {"name": "Pointer", "hand": "Right", "gesture": "point", "action": "cursor", "enabled": True, "cooldown": 0},
            {"name": "Click", "hand": "Right", "gesture": "pinch", "action": "click", "enabled": True, "cooldown": 0.4},
            *[{"name": f"{hand} swipe {direction}", "hand": hand,
               "gesture": f"swipe_{direction}", "action": f"{action}_{direction}",
               "enabled": True, "cooldown": 0.8}
              for hand, action in (("Left", "workspace"), ("Right", "window"))
              for direction in ("left", "right")],
        ],
    }


def number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a number between {low} and {high}")


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    unknown = config.keys() - defaults().keys()
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    c = defaults() | config
    for key in ("mirror", "swap_hands", "preview", "dry_run"):
        if type(c[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    for key, low, high in (("fps", 1, 60), ("width", 160, 3840), ("height", 120, 2160), ("camera", 0, 32)):
        number(c[key], key, low, high)
        if type(c[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for key, low, high in (("confidence", 0.1, 1), ("smoothing", 0.01, 1),
                           ("cursor_margin", 0, 0.4), ("pinch_threshold", 0.05, 1),
                           ("pinch_release", 0.05, 2), ("swipe_distance", 0.05, 0.8),
                           ("swipe_seconds", 0.1, 2)):
        number(c[key], key, low, high)
    if c["pinch_release"] <= c["pinch_threshold"]:
        raise ValueError("pinch_release must exceed pinch_threshold")
    for key in ("hand_model", "pose_model", "monitor"):
        if not isinstance(c[key], str) or (key != "monitor" and not c[key]):
            raise ValueError(f"{key} must be a string")
    if not isinstance(c["bindings"], list):
        raise ValueError("bindings must be a list")
    names = set()
    for b in c["bindings"]:
        if not isinstance(b, dict) or set(b) != {"name", "hand", "gesture", "action", "enabled", "cooldown"}:
            raise ValueError("Each binding needs name, hand, gesture, action, enabled, cooldown")
        if not isinstance(b["name"], str) or not b["name"].strip() or b["name"] in names:
            raise ValueError("Binding names must be nonempty and unique")
        names.add(b["name"])
        if b["hand"] not in ("Left", "Right") or b["gesture"] not in GESTURES or b["action"] not in ACTIONS:
            raise ValueError(f"Invalid hand, gesture or action in {b['name']}")
        if (b["gesture"] == "point") != (b["action"] == "cursor"):
            raise ValueError("Point must map to cursor; discrete gestures must map to discrete actions")
        if type(b["enabled"]) is not bool:
            raise ValueError("Binding enabled must be true or false")
        number(b["cooldown"], "cooldown", 0, 30)
    return c


def parse_field(key, text):
    """Coerce settings-window text using the setting's canonical type, not whatever the file happens to hold."""
    kind = type(defaults()[key])
    if kind is str:
        return text
    try:
        return kind(text)
    except ValueError:
        raise ValueError(f"{key} must be {'an integer' if kind is int else 'a number'}") from None


def read(path=None):
    path = Path(path or config_path())
    return validate(json.loads(path.read_text())) if path.exists() else defaults()


def save(config, path=None):
    config = validate(config)
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(config, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
