#!/usr/bin/env python3
"""Stop and remove Motion's user runtime; preserve the plugin and user data."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


SERVICE = "omarchy-motion.service"


def stop_worker():
    """Fail closed: do not remove files if systemd cannot confirm the worker stopped."""
    def property_value(name):
        return subprocess.run(
            ["systemctl", "--user", "show", SERVICE, f"--property={name}", "--value"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    # A previously removed unit is safe to skip, but still check ActiveState:
    # a loaded process can outlive deletion of its unit file.
    if property_value("LoadState") != "not-found":
        subprocess.run(["systemctl", "--user", "stop", SERVICE], check=True)
    if property_value("ActiveState") not in {"inactive", "failed"}:
        raise RuntimeError("Motion has not stopped; installation files were preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, help="Remove staged files in a fake HOME without calling systemctl")
    parser.add_argument("--remove-venv", action="store_true", help="Also delete the standard dedicated external Python environment")
    args = parser.parse_args()
    home = args.prefix or Path.home()
    config = home / ".config" if args.prefix else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data = home / ".local/share" if args.prefix else Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    venv = data / "omarchy-motion/venv"
    if args.remove_venv and venv.is_symlink():
        sys.exit("Refusing to remove a symlinked environment; omit --remove-venv and manage it separately.")
    if args.remove_venv and venv.exists() and not (venv / "pyvenv.cfg").is_file():
        sys.exit("Refusing to remove a directory without pyvenv.cfg; omit --remove-venv and inspect it separately.")
    if not args.prefix:
        stop_worker()
    for path in (
        config / "systemd/user/omarchy-motion.service",
        home / ".local/bin/omarchy-motion",
        data / "applications/omarchy-motion.desktop",
    ):
        path.unlink(missing_ok=True)
    if not args.prefix:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    if args.remove_venv and venv.exists():
        shutil.rmtree(venv)
    print("Removed Motion runtime integration. Settings, calibration, models, and plugin source are preserved.")
    print("Now remove the widget: omarchy plugin remove fingerskier.motion")
    if not args.remove_venv:
        print(f"Python environment preserved: {venv}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Uninstall stopped: {exc}")
