import argparse
import json
import subprocess
import sys

from . import config, service


def main():
    parser = argparse.ArgumentParser(description="Offline gesture control for Omarchy")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("on", "off", "toggle", "status", "settings", "models", "worker", "init", "list", "panel"):
        sub.add_parser(cmd)
    from .panel import QUICK_SETTINGS
    setting = sub.add_parser("set", help="Update one quick setting without replacing other configuration")
    setting.add_argument("key", choices=QUICK_SETTINGS)
    setting.add_argument("value", choices=("true", "false"))
    calibrate = sub.add_parser("calibrate", help="Capture a local ASL handshape sample through the service")
    calibrate.add_argument("--hand", choices=("Left", "Right"), required=True)
    calibrate.add_argument("--symbol", required=True)
    add = sub.add_parser("add", help="Build a gesture/action mapping")
    add.add_argument("name")
    add.add_argument("--hand", choices=("Left", "Right"), required=True)
    add.add_argument("--gesture", choices=config.GESTURES, required=True)
    add.add_argument("--action", choices=config.ACTIONS, required=True)
    add.add_argument("--cooldown", type=float, default=0.8)
    for cmd in ("enable", "disable", "remove"):
        sub.add_parser(cmd).add_argument("name")
    args = parser.parse_args()
    try:
        if args.command in ("on", "off", "toggle"):
            service.control(args.command)
        elif args.command == "status":
            state = service.state()
            print(json.dumps({"enabled": state == "active", "state": state}))
        elif args.command == "settings":
            from .ui import launch
            launch()
        elif args.command == "panel":
            from .panel import stream
            stream()
        elif args.command == "set":
            from .panel import set_setting
            set_setting(args.key, args.value == "true")
            if service.state() == "active":
                service.control("restart")
        elif args.command == "calibrate":
            from .calibration import request
            request(args.hand, args.symbol.upper())
            service.control("on")
            print("Watch the preview: two-second countdown, then hold the sign still. Only numeric features are saved.")
        else:
            c = config.read()
            if args.command == "worker":
                from .runtime import run
                run(c)
            elif args.command == "models":
                from .models import download
                download(c)
            elif args.command == "list":
                print(json.dumps(c["bindings"], indent=2))
            elif args.command == "init":
                if config.config_path().exists():
                    print(f"Already present: {config.config_path()}")
                else:
                    config.save(c)
                    print(config.config_path())
            else:
                if args.command == "add":
                    c["bindings"].append({"name": args.name, "hand": args.hand, "gesture": args.gesture,
                                          "action": args.action, "cooldown": args.cooldown, "enabled": True})
                else:
                    b = next((b for b in c["bindings"] if b["name"] == args.name), None)
                    if b is None:
                        raise ValueError(f"Unknown binding: {args.name}")
                    if args.command == "remove":
                        c["bindings"].remove(b)
                    else:
                        b["enabled"] = args.command == "enable"
                config.save(c)
                if service.state() == "active":
                    service.control("restart")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        print(f"omarchy-motion: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
