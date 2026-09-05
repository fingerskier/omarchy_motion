"""Camera lifetime is the service lifetime. All inference stays on this machine."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import signal
import socket
import time

from .backend import Hyprland
from .gestures import GestureEngine, Observation


def notify_ready():
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(b"READY=1")


def run(c):
    for key in ("hand_model", "pose_model"):
        if not Path(c[key]).is_file():
            raise ValueError(f"Missing {key}: {c[key]}. Run omarchy-motion models first.")
    import cv2
    import mediapipe as mp

    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    with ExitStack() as stack:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous = signal.signal(sig, stop)
            stack.callback(signal.signal, sig, previous)
        lock_path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "omarchy-motion.lock"
        lock = stack.enter_context(lock_path.open("w"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Omarchy Motion is already running") from None
        backend = Hyprland(c["monitor"], c["dry_run"])
        base, vision = mp.tasks.BaseOptions, mp.tasks.vision
        hands = stack.enter_context(vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=base(model_asset_path=c["hand_model"]),
            running_mode=vision.RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=c["confidence"],
            min_hand_presence_confidence=c["confidence"], min_tracking_confidence=c["confidence"])))
        pose = stack.enter_context(vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=base(model_asset_path=c["pose_model"]),
            running_mode=vision.RunningMode.VIDEO, num_poses=1,
            min_pose_detection_confidence=c["confidence"], min_pose_presence_confidence=c["confidence"],
            min_tracking_confidence=c["confidence"])))
        cap = cv2.VideoCapture(c["camera"], cv2.CAP_V4L2)
        stack.callback(cap.release)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {c['camera']}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if c["preview"]:
            stack.callback(cv2.destroyAllWindows)
        engine, timestamp, ready = GestureEngine(c), -1, False
        while not stopped:
            started = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Camera disconnected or returned an empty frame")
            if stopped:
                break
            pose_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if c["mirror"]:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp = max(timestamp + 1, int(started * 1000))
            hand_result = hands.detect_for_video(image, timestamp)
            # Keep the pose input unmirrored so its labels remain anatomical.
            pose_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=pose_rgb)
            pose_result = pose.detect_for_video(pose_image, timestamp)
            points = {}
            for categories, landmarks in zip(hand_result.handedness, hand_result.hand_landmarks):
                if categories[0].score < c["confidence"]:
                    continue
                label = categories[0].category_name
                # Hand model labels assume a mirrored selfie image.
                if (not c["mirror"]) != c["swap_hands"]:
                    label = "Left" if label == "Right" else "Right"
                points[label] = [(p.x, p.y) for p in landmarks]
            body = [(p.x, p.y, p.visibility) for p in pose_result.pose_landmarks[0]] if pose_result.pose_landmarks else []
            if body and c["mirror"]:
                body = [(1 - x, y, visibility) for x, y, visibility in body]
            if body and c["swap_hands"]:
                for left in range(11, 33, 2):
                    body[left], body[left + 1] = body[left + 1], body[left]
            events = engine.step(Observation(points, body), started)
            for action, value in events:
                if stopped:
                    break
                backend.dispatch(action, value)
            if not ready and not stopped:
                notify_ready()
                ready = True
            if c["preview"] and not stopped:
                for label, landmarks in points.items():
                    wrist = landmarks[0]
                    cv2.putText(frame, label, (int(wrist[0] * frame.shape[1]), int(wrist[1] * frame.shape[0])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 240, 100), 2)
                for group in [*points.values(), body]:
                    for p in group:
                        cv2.circle(frame, (int(p[0] * frame.shape[1]), int(p[1] * frame.shape[0])), 3, (80, 240, 100), -1)
                cv2.putText(frame, "TEST MODE" if c["dry_run"] else "CONTROL ON", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 240, 100), 2)
                cv2.imshow("Omarchy Motion - Esc to switch off", frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")) or cv2.getWindowProperty("Omarchy Motion - Esc to switch off", cv2.WND_PROP_VISIBLE) < 1:
                    stopped = True
            delay = 1 / c["fps"] - (time.monotonic() - started)
            if delay > 0 and not stopped:
                time.sleep(delay)
