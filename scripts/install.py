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
    parser.add_argument("--runtime", type=Path, help="Override the omarchy-motion executable (development checkouts)")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    home = args.prefix or Path.home()
    config_home = home / ".config" if args.prefix else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data_home = home / ".local/share" if args.prefix else Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    executable = (args.runtime or data_home / "omarchy-motion/venv/bin/omarchy-motion").absolute()
    plugin = config_home / "omarchy/plugins/fingerskier.motion"
    managed = plugin.resolve() == repo
    if not managed and (plugin / ".git").exists():
        sys.exit(f"Refusing to overwrite a managed checkout. Run its installer instead: {plugin / 'scripts/install.py'}")
    if not args.prefix and not executable.is_file():
        sys.exit("Runtime not found. Follow the external-venv setup in README.md, or pass --runtime PATH.")
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
    if not managed:
        (plugin / "plugin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / "manifest.json", plugin / "manifest.json")
        shutil.copy2(repo / "LICENSE", plugin / "LICENSE")
        shutil.copy2(repo / "NOTICE", plugin / "NOTICE")
        for source in (repo / "plugin").glob("*.qml"):
            shutil.copy2(source, plugin / "plugin" / source.name)
    desktop = data_home / "applications/omarchy-motion.desktop"
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
    if not managed:
        print("Development widget copy installed; use 'omarchy plugin add' for git-managed updates.")


if __name__ == "__main__":
    main()
