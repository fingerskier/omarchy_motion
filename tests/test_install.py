import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("motion_installer", REPO / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTest(unittest.TestCase):
    def invoke(self, home, repo=REPO):
        with patch.object(installer, "__file__", str(repo / "scripts/install.py")), \
             patch("sys.argv", ["install.py", "--prefix", str(home)]), \
             contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def test_staged_snapshot_has_valid_root_entry_and_external_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.invoke(home)
            plugin = home / ".config/omarchy/plugins/fingerskier.motion"
            manifest = json.loads((plugin / "manifest.json").read_text())
            self.assertEqual(manifest["entryPoints"]["barWidget"], "plugin/BarWidget.qml")
            self.assertTrue((plugin / manifest["entryPoints"]["barWidget"]).is_file())
            self.assertTrue((plugin / "LICENSE").is_file())
            launcher = (home / ".local/bin/omarchy-motion").read_text()
            self.assertIn("/.local/share/omarchy-motion/venv/bin/omarchy-motion", launcher)

    def test_managed_checkout_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            repo = home / ".config/omarchy/plugins/fingerskier.motion"
            (repo / ".git").mkdir(parents=True)
            (repo / "plugin").mkdir()
            (repo / "manifest.json").write_text((REPO / "manifest.json").read_text())
            (repo / "plugin/BarWidget.qml").write_text("managed widget")
            before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
            self.invoke(home, repo)
            after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertTrue((home / ".config/systemd/user/omarchy-motion.service").is_file())
            self.assertFalse((repo / ".venv").exists())

    def test_other_managed_checkout_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".config/omarchy/plugins/fingerskier.motion/.git").mkdir(parents=True)
            with self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                self.invoke(home)
            self.assertFalse((home / ".local/bin/omarchy-motion").exists())
