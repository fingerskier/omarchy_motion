#!/usr/bin/env python3
"""Install this checkout's runtime and widget into user-owned directories."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, help="Stage files in a fake HOME without calling systemctl")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    home = args.prefix or Path.home()
    config_home = home / ".config" if args.prefix else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    executable = repo / ".venv/bin/omarchy-motion"
    if not args.prefix and not executable.is_file():
        sys.exit("Run uv sync --python 3.12 first")
    launcher = home / ".local/bin/omarchy-motion"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(str(executable)) + ' "$@"\n')
    launcher.chmod(0o755)
    unit = config_home / "systemd/user/omarchy-motion.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    # systemd has its own quoting and specifier expansion, separate from shell quoting.
    command = str(executable).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    unit.write_text(f'''[Unit]
Description=Omarchy offline webcam gesture controls
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=notify
ExecStart="{command}" worker
Restart=no
TimeoutStartSec=35
TimeoutStopSec=5
KillMode=control-group
UMask=0077
''')
    plugin = config_home / "omarchy/plugins/fingerskier.motion"
    plugin.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "BarWidget.qml"):
        shutil.copy2(repo / "plugin" / name, plugin / name)
    desktop = home / ".local/share/applications/omarchy-motion.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop_exec = str(launcher).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=Omarchy Motion
Comment=Configure offline webcam gesture controls
Exec="{desktop_exec}" settings
Icon=camera-web
Terminal=false
Categories=Settings;Accessibility;
''')
    if not args.prefix:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"Installed launcher, service, settings entry, and widget under {home}")
    print("Add the widget: omarchy bar put fingerskier.motion --section right")
    print("Motion remains off until switched on.")


if __name__ == "__main__":
    main()
