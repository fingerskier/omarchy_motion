"""Offline tests for hardened model provisioning (no network)."""
import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from omarchy_motion import models


def make_bundle(payload=b"fake-tflite-bytes"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.tflite", payload)
        archive.writestr("meta.txt", b"meta")
    return buf.getvalue()


def digest_of(data):
    return hashlib.sha256(data).hexdigest()


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write_file(self, name, data, mode=0o600):
        path = self.dir / name
        path.write_bytes(data)
        os.chmod(path, mode)
        return str(path)

    def test_valid_bundle_verifies(self):
        data = make_bundle()
        path = self.write_file("hand.task", data)
        models.verify(path, "https://example.invalid/hand", digest_of(data))

    def test_digest_mismatch_rejected(self):
        data = make_bundle()
        path = self.write_file("hand.task", data)
        with self.assertRaises(ValueError):
            models.verify(path, "https://example.invalid/hand", "0" * 64)

    def test_missing_tflite_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("readme.txt", b"no model here")
        data = buf.getvalue()
        path = self.write_file("hand.task", data)
        with self.assertRaises(ValueError):
            models.verify(path, "https://example.invalid/hand", digest_of(data))

    def test_symlink_rejected(self):
        data = make_bundle()
        real = self.write_file("real.task", data)
        link = self.dir / "link.task"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            models.verify(str(link), "https://example.invalid/hand", digest_of(data))

    def test_world_writable_rejected(self):
        data = make_bundle()
        path = self.write_file("hand.task", data, mode=0o666)
        with self.assertRaises(ValueError):
            models.verify(path, "https://example.invalid/hand", digest_of(data))

    def test_traversal_entry_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("../evil.tflite", b"x")
        data = buf.getvalue()
        path = self.write_file("hand.task", data)
        with self.assertRaises(ValueError):
            models.verify(path, "https://example.invalid/hand", digest_of(data))

    def test_size_cap_enforced(self):
        data = make_bundle(os.urandom(2048))
        path = self.write_file("hand.task", data)
        with patch.object(models, "MAX_MODEL_BYTES", 1024):
            with self.assertRaises(ValueError):
                models.verify(path, "https://example.invalid/hand", digest_of(data))

    def test_closed_url_policy(self):
        with self.assertRaises(ValueError):
            models._check_url("http://storage.googleapis.com/x.task")
        with self.assertRaises(ValueError):
            models._check_url("https://evil.example.com/x.task")
        models._check_url("https://storage.googleapis.com/x.task")

    def test_redirect_policy_rejects_cross_host(self):
        from http.client import HTTPMessage
        handler = models._RestrictedRedirectHandler()
        req = models.Request("https://storage.googleapis.com/x.task")
        fp, headers = io.BytesIO(b""), HTTPMessage()
        with self.assertRaises(ValueError):
            handler.redirect_request(req, fp, 302, "Found", headers, "https://evil.example.com/y")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            handler.redirect_request(req, fp, 302, "Found", headers, "http://storage.googleapis.com/y")  # type: ignore[arg-type]

    def fake_source(self, data, content_length=None):
        class FakeSource:
            def __init__(self, payload):
                self.buf = io.BytesIO(payload)
                self.url = "https://storage.googleapis.com/x.task"

            def getheader(self, name):
                if name == "Content-Length" and content_length is not None:
                    return str(content_length)
                return None

            def geturl(self):
                return self.url

            def read(self, n=-1):
                return self.buf.read(n)

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeSource(data)

    def test_download_replaces_invalid_existing(self):
        good = make_bundle(b"good-payload")
        digest = digest_of(good)
        dest = self.dir / "hand.task"
        dest.write_bytes(b"corrupted")
        os.chmod(dest, 0o600)
        config = {"hand_model": str(dest), "pose_model": str(dest)}
        with patch.dict(models.MODELS, {"hand_model": ("https://storage.googleapis.com/x.task", digest),
                                        "pose_model": ("https://storage.googleapis.com/x.task", digest)}):
            with patch.object(models, "_open_source", side_effect=lambda url: self.fake_source(good, len(good))):
                models.download({"hand_model": str(dest), "pose_model": str(self.dir / "pose.task")})
        models.verify(str(dest), "https://storage.googleapis.com/x.task", digest)

    def test_download_rejects_oversize_stream(self):
        big = make_bundle(b"z" * 4096)
        digest = digest_of(big)
        dest = self.dir / "hand.task"
        config = {"hand_model": str(dest)}
        with patch.object(models, "MAX_MODEL_BYTES", 1024):
            with patch.object(models, "_open_source", side_effect=lambda url: self.fake_source(big)):
                with self.assertRaises(ValueError):
                    models.download(config)
        self.assertFalse(dest.exists())
        leftovers = [p for p in self.dir.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_runtime_refuses_invalid_model(self):
        from omarchy_motion import config, runtime
        bad = self.dir / "hand.task"
        bad.write_bytes(b"corrupted")
        os.chmod(bad, 0o600)
        c = config.defaults() | {"hand_model": str(bad), "pose_model": str(bad)}
        with self.assertRaisesRegex(ValueError, "Invalid hand_model"):
            runtime.run(c)


if __name__ == "__main__":
    unittest.main()
