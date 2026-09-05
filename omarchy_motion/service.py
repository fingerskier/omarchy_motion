import subprocess

UNIT = "omarchy-motion.service"


def state():
    result = subprocess.run(["systemctl", "--user", "show", UNIT, "--property=ActiveState", "--value"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Cannot reach the user service manager")
    return result.stdout.strip() or "inactive"


def control(action):
    if action == "toggle":
        action = "off" if state() in ("active", "activating", "reloading") else "on"
    if action == "on":
        subprocess.run(["systemctl", "--user", "import-environment", "WAYLAND_DISPLAY", "DISPLAY",
                        "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP"], check=True, timeout=5)
    result = subprocess.run(["systemctl", "--user", {"on": "start", "off": "stop", "restart": "restart"}[action], UNIT],
                            capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() + "\nSee journalctl --user -u omarchy-motion -n 40")
