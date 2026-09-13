"""Explicit model provisioning. The runtime never downloads anything.

Security properties (marketplace review):
- Downloads only from pinned HTTPS URLs on an allowlisted host, with a
  closed redirect policy (same host, HTTPS, bounded hops).
- Strict transfer cap enforced while streaming (cap+1 rejection) plus a
  Content-Length pre-check when the server sends one.
- Streaming SHA-256 computed during download; digest compared before the
  file is installed.
- Bounded archive validation: member count, per-member and total
  uncompressed sizes, no absolute/traversal/symlink entries, required
  .tflite payload, CRC check.
- Existing files are never trusted by presence: they are opened no-follow
  and verified for type (regular file), owner (current uid),
  non-world-writable mode, size, exact digest, and archive shape before use.
"""
import hashlib
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener
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

ALLOWED_HOSTS = frozenset({"storage.googleapis.com"})
# Largest bundle is ~7.8 MB; 32 MiB leaves headroom while bounding disk/memory.
MAX_MODEL_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 64
MAX_REDIRECTS = 3
CHUNK_BYTES = 1024 * 1024
TIMEOUT = 60


def _check_url(url):
    """Refuse anything outside the closed HTTPS allowlist before connecting."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing download outside allowlisted hosts: {url}")
    return parsed


class _RestrictedRedirectHandler(HTTPRedirectHandler):
    """Follow only bounded, same-host HTTPS redirects."""

    def __init__(self):
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirects += 1
        if self.redirects > MAX_REDIRECTS:
            raise ValueError(f"Too many redirects (>{MAX_REDIRECTS}) for {req.full_url}")
        resolved = urljoin(req.full_url, newurl)
        parsed = urlparse(resolved)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Refusing redirect outside allowlisted hosts: {resolved}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_source(url):
    """Open a download URL under the closed redirect/host policy."""
    _check_url(url)
    handler = _RestrictedRedirectHandler()
    opener = build_opener(handler)
    response = opener.open(Request(url, headers={"User-Agent": "omarchy-motion/1"}), timeout=TIMEOUT)
    final = response.geturl()
    parsed = urlparse(final)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        response.close()
        raise ValueError(f"Refusing final URL outside allowlisted hosts: {final}")
    length = response.getheader("Content-Length")
    if length is not None:
        try:
            expected = int(length)
        except ValueError:
            response.close()
            raise ValueError(f"Invalid Content-Length for {url}: {length!r}")
        if expected <= 0 or expected > MAX_MODEL_BYTES:
            response.close()
            raise ValueError(
                f"Refusing {url}: Content-Length {expected} outside 1..{MAX_MODEL_BYTES}"
            )
    return response


def _stat_no_follow(path):
    """lstat checks: regular file, owned by us, not world-writable, bounded size."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Refusing symlink model file: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Refusing non-regular model file: {path}")
    if st.st_uid != os.getuid():
        raise ValueError(f"Refusing model file not owned by current user: {path}")
    if st.st_mode & stat.S_IWOTH:
        raise ValueError(f"Refusing world-writable model file: {path}")
    if st.st_size <= 0 or st.st_size > MAX_MODEL_BYTES:
        raise ValueError(
            f"Refusing model file with size {st.st_size} outside 1..{MAX_MODEL_BYTES}: {path}"
        )
    return st


def _hash_fd(fd, cap=MAX_MODEL_BYTES):
    """Streaming SHA-256 over an open fd with cap+1 rejection. Returns (hexdigest, total)."""
    hasher = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise ValueError(f"Refusing file exceeding {cap} bytes during streaming hash")
        hasher.update(chunk)
    return hasher.hexdigest(), total


def _check_archive(fileobj, url):
    """Bounded ZIP validation on an open binary file object. Requires a .tflite payload."""
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise ValueError(f"Invalid model bundle (not a ZIP): {url}")
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"Invalid model bundle member count for {url}: {len(infos)}")
        total_uncompressed = 0
        has_tflite = False
        for info in infos:
            name = info.filename
            if (
                not name
                or "\\" in name
                or name.startswith("/")
                or len(name) > 1024
                or ".." in Path(name).parts
                or (len(name) >= 2 and name[1] == ":")
            ):
                raise ValueError(f"Invalid model bundle entry for {url}: {name!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Refusing symlink entry in model bundle for {url}: {name!r}")
            if info.is_dir():
                continue
            if info.file_size > MAX_MEMBER_BYTES or info.compress_size > MAX_MODEL_BYTES:
                raise ValueError(f"Oversize model bundle entry for {url}: {name!r}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ValueError(f"Model bundle uncompressed size exceeds cap for {url}")
            if name.endswith(".tflite"):
                has_tflite = True
        if not has_tflite:
            raise ValueError(f"Invalid model bundle (no .tflite payload): {url}")
        if archive.testzip() is not None:
            raise ValueError(f"Invalid model bundle (CRC failure): {url}")


def verify(path, url, digest):
    """Refuse a bundle that is not the pinned, well-formed file.

    Opens no-follow once and checks type, owner, mode, size, exact digest,
    then bounded archive shape on the same descriptor. Raises ValueError/OSError
    on failure.
    """
    _stat_no_follow(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    owned = True
    try:
        actual, _ = _hash_fd(fd)
        if actual != digest:
            raise ValueError(f"Checksum mismatch for {url}: expected {digest}, got {actual}")
        os.lseek(fd, 0, os.SEEK_SET)
        fileobj = os.fdopen(fd, "rb")
        owned = False
        try:
            _check_archive(fileobj, url)
        finally:
            fileobj.close()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError(f"Invalid model bundle for {url}: {exc}") from exc
    finally:
        if owned:
            os.close(fd)


def download(config):
    for key, (url, digest) in MODELS.items():
        path = Path(config[key])
        if os.path.lexists(path):
            try:
                verify(path, url, digest)
            except (ValueError, OSError) as exc:
                print(f"Replacing invalid existing file {path}: {exc}")
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                except OSError as unlink_exc:
                    raise ValueError(f"Cannot remove invalid model file {path}: {unlink_exc}")
            else:
                print(f"Already verified: {path}")
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=".tmp-") as target:
                name = target.name
                try:
                    os.chmod(name, 0o600)
                except OSError:
                    pass
                hasher = hashlib.sha256()
                total = 0
                expected_length = None
                with _open_source(url) as source:
                    raw_length = source.getheader("Content-Length")
                    if raw_length is not None:
                        expected_length = int(raw_length)
                    while True:
                        chunk = source.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_MODEL_BYTES:
                            raise ValueError(
                                f"Refusing {url}: transfer exceeds {MAX_MODEL_BYTES} bytes"
                            )
                        hasher.update(chunk)
                        target.write(chunk)
                if expected_length is not None and total != expected_length:
                    raise ValueError(
                        f"Refusing {url}: received {total} bytes, Content-Length said {expected_length}"
                    )
                if hasher.hexdigest() != digest:
                    raise ValueError(
                        f"Checksum mismatch for {url}: expected {digest}, got {hasher.hexdigest()}"
                    )
            verify(name, url, digest)
            os.replace(name, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            print(f"Downloaded: {path}")
        finally:
            if name and os.path.lexists(name):
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass
