"""Explicit model provisioning. The runtime never downloads anything."""
from pathlib import Path
import os
import tempfile
from urllib.request import urlopen
import zipfile

URLS = {
    "hand_model": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    "pose_model": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
}


def download(config):
    for key, url in URLS.items():
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
            with zipfile.ZipFile(name) as archive:
                if archive.testzip() is not None or not any(n.endswith(".tflite") for n in archive.namelist()):
                    raise ValueError(f"Invalid model bundle: {url}")
            os.replace(name, path)
            print(f"Downloaded: {path}")
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
