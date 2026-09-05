"""Camera lifetime is the service lifetime. All inference stays on this machine."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import signal
import socket
import time

from .backend import Hyprland
from .asl import features
from .calibration import Capture
from .gestures import GestureEngine, Observation
from .panel import Publisher, settings_state


def notify_ready():
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(b"READY=1")


def needs_pose(c):
    """Body tracking costs a second model per frame; only pay for it when a mapping uses it."""
    return any(b["enabled"] and b["gesture"] == "hand_raised" for b in c["bindings"])


def run(c):
    for key in ("hand_model", "pose_model") if needs_pose(c) else ("hand_model",):
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
        publisher = Publisher()
        stack.callback(publisher.close)
        backend = Hyprland(c["monitor"], c["dry_run"])
        stack.callback(backend.close)
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
            min_tracking_confidence=c["confidence"]))) if needs_pose(c) else None
        cap = cv2.VideoCapture(c["camera"], cv2.CAP_V4L2)
        stack.callback(cap.release)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {c['camera']}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        stack.callback(cv2.destroyAllWindows)
        calibration, preview_visible = Capture(), False
        engine, timestamp, ready = GestureEngine(c), -1, False
        while not stopped:
            started = time.monotonic()
            ok, frame = cap.read()
            if stopped:
                break
            if not ok:
                raise RuntimeError("Camera disconnected or returned an empty frame")
            # One colour conversion per frame. The hand model wants a mirrored selfie view;
            # the pose model stays unmirrored so its labels remain anatomical.
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hand_rgb = cv2.flip(rgb, 1) if c["mirror"] else rgb
            timestamp = max(timestamp + 1, int(started * 1000))
            hand_result = hands.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=hand_rgb), timestamp)
            pose_result = pose.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp) if pose else None
            points, scores, shapes = {}, {}, {}
            aspect = frame.shape[1] / frame.shape[0]
            for categories, landmarks in zip(hand_result.handedness, hand_result.hand_landmarks):
                score = categories[0].score
                if score < c["confidence"]:
                    continue
                label = categories[0].category_name
                # Hand model labels assume a mirrored selfie image.
                if (not c["mirror"]) != c["swap_hands"]:
                    label = "Left" if label == "Right" else "Right"
                # Two hands can share a label; keep the one the model is surer about.
                if score > scores.get(label, -1):
                    points[label], scores[label] = [(p.x, p.y) for p in landmarks], score
                    shapes[label] = [(p.x * aspect, p.y) for p in landmarks]
            body = [(p.x, p.y, p.visibility) for p in pose_result.pose_landmarks[0]] if pose_result and pose_result.pose_landmarks else []
            if body and c["mirror"]:
                body = [(1 - x, y, visibility) for x, y, visibility in body]
            if body and c["swap_hands"]:
                for left in range(11, 33, 2):
                    body[left], body[left + 1] = body[left + 1], body[left]
            calibrating = calibration.step({hand: features(p) for hand, p in shapes.items()}, started, c, engine.recognizer)
            events = engine.step(Observation(points, body, shapes), started)
            if calibrating:
                events = []
                if calibration.completed:
                    engine = GestureEngine(c)
                    engine.chords.latched = True
            for action, value in events:
                if stopped:
                    break
                accepted = backend.dispatch(action, value)
                if action in ("workspace", "move_window", "fullscreen", "floating"):
                    print(f"ASL: {action} {value} ({'test' if c['dry_run'] else 'sent' if accepted else 'rejected'})", flush=True)
                    if not accepted:
                        engine.chord_status.text = "Desktop rejected command (see service log)"
            if not ready and not stopped:
                notify_ready()
                ready = True
            panel_due = publisher.due(started)
            panel_wanted = publisher.wanted(started)
            # When calibration is driven from the dropdown, keep its camera
            # view there. CLI calibration still opens a window if no panel reads.
            show_preview = c["preview"] or ((calibrating or bool(calibration.text)) and not panel_wanted)
            if (show_preview or (panel_due and panel_wanted)) and not stopped:
                if c["mirror"]:
                    frame = cv2.flip(frame, 1)
                for label, landmarks in points.items():
                    wrist = landmarks[0]
                    prediction = engine.symbols.get(label)
                    caption = f"{label}: {prediction.symbol or '?'} ({prediction.source})" if prediction else label
                    cv2.putText(frame, caption, (int(wrist[0] * frame.shape[1]), int(wrist[1] * frame.shape[0])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 240, 100), 2)
                for group in [*points.values(), body]:
                    for p in group:
                        cv2.circle(frame, (int(p[0] * frame.shape[1]), int(p[1] * frame.shape[0])), 3, (80, 240, 100), -1)
                cv2.putText(frame, "TEST MODE" if c["dry_run"] else "CONTROL ON", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 240, 100), 2)
                cv2.putText(frame, calibration.text or engine.chord_status.text, (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 240, 100), 1)
                cv2.rectangle(frame, (12, 64), (12 + int((frame.shape[1] - 24) * engine.chord_status.progress), 70), (80, 240, 100), -1)
            if panel_due and not stopped:
                jpeg = None
                if panel_wanted:
                    view = cv2.resize(frame, (480, max(1, int(480 / aspect))))
                    encoded, data = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if encoded:
                        jpeg = data.tobytes()
                publisher.publish({
                    "settings": settings_state(c), "camera": c["camera"],
                    "symbols": {hand: p.symbol or "?" for hand, p in engine.symbols.items()},
                    "status": calibration.text or engine.chord_status.text,
                    "progress": engine.chord_status.progress,
                    "calibrating": calibrating,
                }, started, jpeg)
            if show_preview and not stopped:
                preview_visible = True
                cv2.imshow("Omarchy Motion - Esc to switch off", frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")) or cv2.getWindowProperty("Omarchy Motion - Esc to switch off", cv2.WND_PROP_VISIBLE) < 1:
                    stopped = True
            elif preview_visible:
                cv2.destroyAllWindows()
                preview_visible = False
            delay = 1 / c["fps"] - (time.monotonic() - started)
            if delay > 0 and not stopped:
                time.sleep(delay)
