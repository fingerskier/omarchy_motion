#!/usr/bin/env python3
"""Test virtual-pointer delivery to controlled layer surfaces on live Hyprland.

Opens two temporary Quickshell targets, clicks only their reported rectangles,
checks press/release/click delivery, then closes them and restores the cursor.
No webcam, user application, or launcher action is used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from omarchy_motion.backend import Hyprland, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", default="", help="Output name; defaults to focused output")
    args = parser.parse_args()
    monitors = json.loads(request("j/monitors"))
    monitor = next(m for m in monitors if m["name"] == args.monitor) if args.monitor else next(m for m in monitors if m["focused"])
    original = json.loads(request("j/cursorpos"))
    namespace = {"bar": "motion-test-bar", "launcher": "motion-test-launcher"}
    backend = Hyprland(monitor["name"])
    process = None
    try:
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen(["quickshell", "-p", str(Path(__file__).with_name("pointer_targets.qml"))],
                                       env=os.environ | {"MOTION_TEST_OUTPUT": monitor["name"]}, stdout=log, stderr=log)
            deadline = time.monotonic() + 10
            targets = {}
            while time.monotonic() < deadline and process.poll() is None:
                layers = json.loads(request("j/layers")).get(monitor["name"], {}).get("levels", {})
                targets = {layer["namespace"]: layer for level in layers.values() for layer in level
                           if layer["namespace"] in namespace.values() and layer["pid"] == process.pid}
                if len(targets) == 2:
                    break
                time.sleep(0.1)
            if len(targets) != 2:
                log.seek(0)
                raise RuntimeError("Test surfaces did not appear: " + log.read())
            x, y, w, h = backend.geometry
            for label, name in namespace.items():
                target = targets[name]
                backend.dispatch("cursor", ((target["x"] + target["w"] / 2 - x) / (w - 1),
                                            (target["y"] + target["h"] / 2 - y) / (h - 1)))
                time.sleep(0.15)
                backend.dispatch("click", None)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    log.seek(0)
                    received = log.read()
                    if all(f"MOTION_{label.upper()}_{event}" in received for event in ("PRESS", "RELEASE", "CLICK")):
                        print(f"PASS: {monitor['name']} {label} layer received press, release, and click")
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError(f"No complete {label} click delivery: {received}")
    finally:
        backend.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        request(f"dispatch movecursor {original['x']} {original['y']}")


if __name__ == "__main__":
    main()
