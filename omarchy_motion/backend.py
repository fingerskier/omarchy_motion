"""Virtual-pointer input and Hyprland IPC workspace/window actions.

Pointer events use a persistent Wayland connection; desktop actions use the
Hyprland control socket. Neither spawns a process per frame. A rejected desktop
dispatcher is logged, not fatal: an empty workspace is a normal state.
"""
import json
import os
from pathlib import Path
import socket
import sys
from .pointer import VirtualPointer

DISPATCHERS = {
    "workspace_left": ("workspace", "r-1"),
    "workspace_right": ("workspace", "r+1"),
    "window_left": ("movetoworkspacesilent", "r-1"),
    "window_right": ("movetoworkspacesilent", "r+1"),
    "toggle_floating": ("togglefloating", "active"),
}


def lua_dispatcher(dispatcher, argument):
    """Translate our fixed action vocabulary for Hyprland's Lua config provider."""
    if dispatcher == "workspace":
        return f"hl.dsp.focus({{ workspace = {json.dumps(argument)} }})"
    if dispatcher == "movetoworkspacesilent":
        return f"hl.dsp.window.move({{ workspace = {json.dumps(argument)}, follow = false }})"
    if dispatcher == "fullscreenstate":
        internal, client = map(int, argument.split())
        return f'hl.dsp.window.fullscreen_state({{ internal = {internal}, client = {client}, action = "set" }})'
    action = {"setfloating": "enable", "settiled": "disable", "togglefloating": "toggle"}[dispatcher]
    return f'hl.dsp.window.float({{ action = "{action}" }})'


def alive(path):
    """A socket entry can outlive its compositor; only a connectable one counts."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.connect(str(path))
        except OSError:
            return False
    return True


def socket_path():
    roots = [Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr", Path("/tmp/hypr")]
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if signature:
        for path in (root / signature / ".socket.sock" for root in roots):
            if path.exists():
                return path
        raise RuntimeError("Hyprland control socket not found; start from a Hyprland session")
    # Started outside the session (for example a terminal without the signature): accept a sole live instance.
    live = [p for root in roots if root.is_dir() for p in sorted(root.glob("*/.socket.sock")) if alive(p)]
    if len(live) > 1:
        raise RuntimeError("Several Hyprland instances found; set HYPRLAND_INSTANCE_SIGNATURE")
    if not live:
        raise RuntimeError("Hyprland control socket not found; start from a Hyprland session")
    return live[0]


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
        self.pointer = None
        self.lua = False
        if not dry_run:
            monitors = json.loads(request("j/monitors"))
            selected = next((m for m in monitors if m["name"] == monitor), None) if monitor else next((m for m in monitors if m.get("focused")), None)
            if selected is None:
                raise ValueError("Configured/focused monitor not found")
            self.geometry = monitor_geometry(selected)
            self.pointer = VirtualPointer(selected["name"], *self.geometry[2:])

    def close(self):
        if self.pointer is not None:
            self.pointer.close()

    def dispatch(self, action, value):
        """Returns True when Hyprland accepted the dispatcher. Rejections are logged once per distinct message."""
        if self.dry_run:
            if action != "cursor":
                print(f"Gesture action: {action}" + (f" {value}" if value is not None else ""), flush=True)
            return True
        if action == "cursor":
            self.pointer.move(value)
            return True
        if action == "click":
            self.pointer.click()
            return True
        if action in ("workspace", "move_window", "fullscreen", "floating"):
            limit = 10 if action in ("workspace", "move_window") else 1
            if type(value) is not int or not (1 if limit == 10 else 0) <= value <= limit:
                raise ValueError("Invalid chord action value")
            dispatcher, argument = {
                "workspace": ("workspace", str(value)),
                "move_window": ("movetoworkspacesilent", str(value)),
                "fullscreen": ("fullscreenstate", "2 2" if value else "0 0"),
                "floating": ("setfloating" if value else "settiled", "active"),
            }[action]
        else:
            dispatcher, argument = DISPATCHERS[action]
        response = request("dispatch " + (lua_dispatcher(dispatcher, argument) if self.lua else f"{dispatcher} {argument}"))
        # Only retry an explicit syntax rejection; never retry a possibly executed action.
        if not self.lua and "dispatch in lua is a shorthand" in response:
            self.lua = True
            response = request("dispatch " + lua_dispatcher(dispatcher, argument))
        elif self.lua and response == "Invalid dispatcher":
            self.lua = False
            response = request(f"dispatch {dispatcher} {argument}")
        if response == "ok":
            self.last_warning = None
            return True
        warning = f"Hyprland rejected {dispatcher}: {response}"
        if warning != self.last_warning:
            print(warning, file=sys.stderr, flush=True)
            self.last_warning = warning
        return False
