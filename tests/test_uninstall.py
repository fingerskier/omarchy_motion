import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("motion_uninstaller", REPO / "scripts/uninstall.py")
uninstaller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uninstaller)


class UninstallTest(unittest.TestCase):
    def invoke(self, home, *options):
        with patch("sys.argv", ["uninstall.py", "--prefix", str(home), *options]), \
             contextlib.redirect_stdout(io.StringIO()):
            uninstaller.main()

    def test_install_update_remove_preserves_source_and_user_data(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for _ in range(2):
                subprocess.run([sys.executable, str(REPO / "scripts/install.py"), "--prefix", d],
                               check=True, capture_output=True)
            preserved = [home / ".config/omarchy-motion/config.json",
                         home / ".local/share/omarchy-motion/models/hand.task"]
            for path in preserved:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("user data")
            venv = home / ".local/share/omarchy-motion/venv"
            venv.mkdir()
            (venv / "pyvenv.cfg").write_text("home = /usr/bin")
            # Default removal leaves the environment; a repeated removal can delete it.
            self.invoke(home)
            self.assertTrue(venv.exists())
            self.invoke(home, "--remove-venv")
            self.invoke(home, "--remove-venv")
            self.assertFalse(venv.exists())
            self.assertTrue((home / ".config/omarchy/plugins/fingerskier.motion/manifest.json").exists())
            for path in preserved:
                self.assertEqual(path.read_text(), "user data")
            for path in [".local/bin/omarchy-motion", ".config/systemd/user/omarchy-motion.service",
                         ".local/share/applications/omarchy-motion.desktop"]:
                self.assertFalse((home / path).exists())

    def test_stop_failure_preserves_installation_and_xdg_paths(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            config, data = home / "config", home / "data"
            unit = config / "systemd/user/omarchy-motion.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("service")
            desktop = data / "applications/omarchy-motion.desktop"
            desktop.parent.mkdir(parents=True)
            desktop.write_text("launcher")
            calls = []

            def systemctl(command, **kwargs):
                calls.append(command)
                if "stop" in command:
                    self.assertTrue(unit.exists())
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0, stdout="loaded\n")

            with patch.object(Path, "home", return_value=home), \
                 patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(data)}), \
                 patch("sys.argv", ["uninstall.py"]), \
                 patch.object(uninstaller.subprocess, "run", side_effect=systemctl):
                with self.assertRaises(subprocess.CalledProcessError):
                    uninstaller.main()
            self.assertEqual(unit.read_text(), "service")
            self.assertEqual(desktop.read_text(), "launcher")
            self.assertFalse(any("daemon-reload" in c for c in calls))

    def test_service_must_be_confirmed_inactive(self):
        for load, active, expected_stop in [("loaded", "inactive", True),
                                            ("not-found", "inactive", False),
                                            ("not-found", "active", False),
                                            ("loaded", "deactivating", True)]:
            with self.subTest(load=load, active=active):
                def systemctl(command, **kwargs):
                    value = load if "--property=LoadState" in command else active
                    return subprocess.CompletedProcess(command, 0, stdout=value)
                with patch.object(uninstaller.subprocess, "run", side_effect=systemctl) as run:
                    if active == "inactive":
                        uninstaller.stop_worker()
                    else:
                        with self.assertRaises(RuntimeError):
                            uninstaller.stop_worker()
                    self.assertEqual(any("stop" in c.args[0] for c in run.call_args_list), expected_stop)

    def test_live_mode_honors_xdg_and_reloads_after_removing_files(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            config, data = home / "custom-config", home / "custom-data"
            files = [config / "systemd/user/omarchy-motion.service",
                     data / "applications/omarchy-motion.desktop",
                     home / ".local/bin/omarchy-motion"]
            for path in files:
                path.parent.mkdir(parents=True)
                path.write_text("installed")

            def systemctl(command, **kwargs):
                if "daemon-reload" in command:
                    self.assertTrue(all(not p.exists() for p in files))
                else:
                    self.assertTrue(all(p.exists() for p in files))
                value = "loaded" if "--property=LoadState" in command else "inactive"
                return subprocess.CompletedProcess(command, 0, stdout=value)

            with patch.object(Path, "home", return_value=home), \
                 patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(data)}), \
                 patch("sys.argv", ["uninstall.py"]), \
                 patch.object(uninstaller.subprocess, "run", side_effect=systemctl) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                uninstaller.main()
            self.assertEqual(run.call_args_list[-1].args[0], ["systemctl", "--user", "daemon-reload"])

    def test_refuses_symlink_or_unrecognized_environment(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            venv = home / ".local/share/omarchy-motion/venv"
            venv.parent.mkdir(parents=True)
            other = home / "other"
            other.mkdir()
            (other / "keep").write_text("keep")
            venv.symlink_to(other, target_is_directory=True)
            with self.assertRaisesRegex(SystemExit, "symlinked"):
                self.invoke(home, "--remove-venv")
            venv.unlink()
            venv.mkdir()
            with self.assertRaisesRegex(SystemExit, "pyvenv.cfg"):
                self.invoke(home, "--remove-venv")
            self.assertEqual((other / "keep").read_text(), "keep")
