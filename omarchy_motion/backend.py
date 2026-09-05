"""Hyprland IPC actions, restricted to a fixed set of dispatchers.

Requests go straight to Hyprland's control socket; no subprocess is spawned per
cursor frame. A dispatcher that Hyprland rejects is logged, not fatal: an empty
workspace with no focused window is a normal state, not a reason to drop the camera.
"""
import json
import os
from pathlib import Path
import socket
import sys

DISPATCHERS = {
    "click": ("sendshortcut", ", mouse:272,"),
    "workspace_left": ("workspace", "r-1"),
    "workspace_right": ("workspace", "r+1"),
    "window_left": ("movetoworkspacesilent", "r-1"),
    "window_right": ("movetoworkspacesilent", "r+1"),
    "toggle_floating": ("togglefloating", "active"),
}


def socket_path():
    roots = [Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr", Path("/tmp/hypr")]
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if signature:
        candidates = [root / signature / ".socket.sock" for root in roots]
    else:
        # Started outside the session (for example a terminal without the signature): accept a sole instance.
        candidates = [p for root in roots if root.is_dir() for p in sorted(root.glob("*/.socket.sock"))]
        if len(candidates) > 1:
            raise RuntimeError("Several Hyprland instances found; set HYPRLAND_INSTANCE_SIGNATURE")
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("Hyprland control socket not found; start from a Hyprland session")


def request(text, path=None):
    """One request per connection, as Hyprland's socket expects. Returns the reply text."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3)
        sock.connect(str(path or socket_path()))
        sock.sendall(text.encode())
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks).decode(errors="replace").strip()


def monitor_geometry(m):
    width, height = m["width"], m["height"]
    if m.get("transform", 0) % 2:
        width, height = height, width
    return m["x"], m["y"], width / m["scale"], height / m["scale"]


class Hyprland:
    def __init__(self, monitor="", dry_run=False):
        self.dry_run = dry_run
        self.geometry = None
        self.last_warning = None
        if not dry_run:
            monitors = json.loads(request("j/monitors"))
            selected = next((m for m in monitors if m["name"] == monitor), None) if monitor else next((m for m in monitors if m.get("focused")), None)
            if selected is None:
                raise ValueError("Configured/focused monitor not found")
            self.geometry = monitor_geometry(selected)

    def dispatch(self, action, value):
        """Returns True when Hyprland accepted the dispatcher. Rejections are logged once per distinct message."""
        if self.dry_run:
            if action != "cursor":
                print(f"Gesture action: {action}", flush=True)
            return True
        if action == "cursor":
            x, y, w, h = self.geometry
            dispatcher, argument = "movecursor", f"{round(x + value[0] * (w - 1))} {round(y + value[1] * (h - 1))}"
        else:
            dispatcher, argument = DISPATCHERS[action]
        response = request(f"dispatch {dispatcher} {argument}")
        if response == "ok":
            self.last_warning = None
            return True
        warning = f"Hyprland rejected {dispatcher}: {response}"
        if warning != self.last_warning:
            print(warning, file=sys.stderr, flush=True)
            self.last_warning = warning
        return False
