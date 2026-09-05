"""Hyprland IPC actions, restricted to a fixed set of dispatchers."""
import json
import subprocess


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=True)
    return result.stdout.strip()


def monitor_geometry(m):
    width, height = m["width"], m["height"]
    if m.get("transform", 0) % 2:
        width, height = height, width
    return m["x"], m["y"], width / m["scale"], height / m["scale"]


class Hyprland:
    def __init__(self, monitor="", dry_run=False):
        self.dry_run = dry_run
        self.geometry = None
        if not dry_run:
            monitors = json.loads(command("hyprctl", "-j", "monitors"))
            selected = next((m for m in monitors if m["name"] == monitor), None) if monitor else next((m for m in monitors if m.get("focused")), None)
            if selected is None:
                raise ValueError("Configured/focused monitor not found")
            self.geometry = monitor_geometry(selected)

    def dispatch(self, action, value):
        if self.dry_run:
            if action != "cursor":
                print(f"Gesture action: {action}", flush=True)
            return
        if action == "cursor":
            x, y, w, h = self.geometry
            dispatcher, argument = "movecursor", f"{round(x + value[0] * (w - 1))} {round(y + value[1] * (h - 1))}"
        else:
            dispatcher, argument = {
                "click": ("sendshortcut", ", mouse:272,"),
                "workspace_left": ("workspace", "r-1"),
                "workspace_right": ("workspace", "r+1"),
                "window_left": ("movetoworkspacesilent", "r-1"),
                "window_right": ("movetoworkspacesilent", "r+1"),
                "toggle_floating": ("togglefloating", "active"),
            }[action]
        response = command("hyprctl", "dispatch", dispatcher, argument)
        if response != "ok":
            raise RuntimeError(f"Hyprland rejected {dispatcher}: {response}")
