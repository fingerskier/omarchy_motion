"""Explicit model provisioning. The runtime never downloads anything."""
import hashlib
from pathlib import Path
import os
import tempfile
from urllib.request import urlopen
import zipfile

# Google's version-1 float16 task bundles. The digests pin exactly what was validated;
# a re-upload that changes bytes is refused rather than silently trusted.
MODELS = {
    "hand_model": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
    ),
    "pose_model": (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    ),
}
URLS = {key: url for key, (url, _) in MODELS.items()}


def verify(path, url, digest):
    """Refuse a bundle that is not the pinned, well-formed ZIP."""
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != digest:
        raise ValueError(f"Checksum mismatch for {url}: expected {digest}, got {actual}")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or not any(n.endswith(".tflite") for n in archive.namelist()):
            raise ValueError(f"Invalid model bundle: {url}")


def download(config):
    for key, (url, digest) in MODELS.items():
        path = Path(config[key])
        if path.is_file():
            print(f"Already present: {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
                name = target.name
                with urlopen(url, timeout=60) as source:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
            verify(name, url, digest)
            os.replace(name, path)
            print(f"Downloaded: {path}")
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
