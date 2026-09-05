"""Private, memory-only preview snapshots for the status-bar panel.

The worker owns the camera. A short-lived CLI bridge reads its Unix socket while
the dropdown is open; no HTTP listener, frame files, or extra camera capture.
"""
import base64
import json
import os
from pathlib import Path
import signal
import socket
import threading
import time

from . import config

QUICK_SETTINGS = ("dry_run", "chords_enabled", "mirror", "swap_hands", "preview")


def socket_path():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "omarchy-motion-panel.sock"


class Publisher:
    def __init__(self):
        self.path = socket_path()
        self.requested = 0
        self.updated = 0
        self.packet = b'{"connected":true}\n'
        self.stopped = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            # The worker's exclusive flock has already been acquired.
            self.path.unlink(missing_ok=True)
            self.listener.bind(str(self.path))
            self.path.chmod(0o600)
            self.listener.listen(4)
            self.listener.settimeout(0.2)
        except BaseException:
            self.listener.close()
            raise
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stopped.is_set():
            try:
                conn, _ = self.listener.accept()
                with conn:
                    conn.settimeout(0.2)
                    if conn.recv(32) == b"snapshot\n":
                        self.requested = time.monotonic()
                        # Do not present a frozen frame if the camera loop stalls.
                        packet = self.packet if time.monotonic() - self.updated < 2 else b'{"connected":false}\n'
                        conn.sendall(packet)
            except (OSError, TimeoutError):
                continue

    def wanted(self, now):
        return self.requested > 0 and now - self.requested < 0.5

    def due(self, now):
        return now - self.updated >= 0.1

    def publish(self, state, now, jpeg=None):
        packet = state | {"connected": True}
        if jpeg is not None:
            packet["image"] = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        self.packet = (json.dumps(packet, separators=(",", ":")) + "\n").encode()
        self.updated = now

    def close(self):
        self.stopped.set()
        self.listener.close()
        self.thread.join(timeout=0.5)
        self.path.unlink(missing_ok=True)
        self.packet = b""


def snapshot():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        sock.connect(str(socket_path()))
        sock.sendall(b"snapshot\n")
        chunks, size = [], 0
        while chunk := sock.recv(65536):
            size += len(chunk)
            if size > 2_000_000:
                raise ValueError("Preview packet exceeds limit")
            chunks.append(chunk)
        return json.loads(b"".join(chunks))


def settings_state(c):
    return {key: c[key] for key in QUICK_SETTINGS}


def stream():
    """One helper per open panel; closing the QML Process terminates it."""
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        while not stopped:
            try:
                packet = snapshot()
            except (OSError, ValueError):
                packet = {"connected": False}
            if not packet.get("connected"):
                try:
                    packet["settings"] = settings_state(config.read())
                except (OSError, ValueError) as e:
                    packet["error"] = str(e)
            try:
                print(json.dumps(packet, separators=(",", ":")), flush=True)
            except BrokenPipeError:
                break
            time.sleep(0.1 if packet.get("connected") else 0.5)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def set_setting(key, value):
    if key not in QUICK_SETTINGS or type(value) is not bool:
        raise ValueError("Invalid panel setting")
    c = config.read()
    c[key] = value
    config.save(c)
