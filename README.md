# Omarchy Motion

Control Omarchy with hand and body movements captured by your webcam. MediaPipe
Hand Landmarker and Pose Landmarker run locally. The application does not send,
record, or save camera frames. Model downloads are an explicit setup step;
normal operation works offline.

## Controls

| Gesture | Default action |
| --- | --- |
| Right index finger extended, ring and little fingers folded | Move cursor |
| Right middle finger pinched to thumb | Left click, once per pinch |
| Left open palm swiped left / right | Previous / next workspace |
| Right open palm swiped left / right | Move focused window to previous / next workspace without following it |
| Hand raised above shoulder | Available in the builder; unassigned by default |

The settings window builds named mappings from gesture, hand, action, and
cooldown. Each mapping can be enabled, disabled, edited, or removed. Available
actions also include toggling the focused window's floating state. This version
composes built-in gesture primitives; it does not train new gestures from video.

The global switch starts/stops a user service. **Off releases the webcam and
stops all actions.** It starts off, does not automatically enable at login, and
stops when the graphical session ends. Camera/model/desktop errors stop the
service and appear in its journal. The bar shows starting, active, failed, or off
state. It reports active only after the first successful inference frame.

## Install

Requires Omarchy with its Quickshell plugin host, Hyprland, a webcam, `uv`, and
Python 3.11–3.13. Python 3.12 is recommended for the MediaPipe wheels. Tkinter is
needed for the settings window; the CLI works without it. The standard Python
runtime downloaded by uv includes Tk on supported Linux builds.

From this checkout:

```sh
uv sync --python 3.12
.venv/bin/python -c 'import tkinter, mediapipe, cv2'
python scripts/install.py
~/.local/bin/omarchy-motion init
~/.local/bin/omarchy-motion models
omarchy bar put fingerskier.motion --section right
```

The installer creates a launcher, desktop settings entry, systemd user service,
and `fingerskier.motion` shell widget. It does not start the camera. Keep this
checkout and its `.venv` in place: the installed launcher/service refer to them.
Installing again updates these application-owned files. User configuration is
preserved. For a packaging preview, use `python scripts/install.py --prefix /tmp/motion-stage`.

Model files live in `$XDG_DATA_HOME/omarchy-motion/models` (normally
`~/.local/share/omarchy-motion/models`). Setup downloads Google's version-1 hand
and pose-lite task bundles over HTTPS and validates their ZIP contents. For an
air-gapped computer, copy the model files and a preprovisioned Python environment
onto it. There is no network access or automatic download in the tracking loop.
Model files are distributed by Google under their own terms, separately from this repository.

## Use and calibrate

Left-click the **Motion** bar widget to toggle, or right-click to open settings.
The application launcher also offers **Omarchy Motion**.

```sh
omarchy-motion settings
omarchy-motion on
omarchy-motion off
omarchy-motion toggle
omarchy-motion status
```

Start by selecting **Test mode** and **Live preview**, saving, then switching on.
The preview displays tracked landmarks. Detected discrete actions appear in
`journalctl --user -u omarchy-motion -f`; test mode sends no desktop commands.
Press Escape or Q in the preview to stop, or use the global switch. Turn off
test mode and save when ready to control the desktop.

Use even lighting with both hands visible. Hand names mean your anatomical left
and right. If camera mirroring makes them appear reversed, use **Swap hand labels**.
Swipes follow the horizontal direction in the preview and require an open palm.
Pinch thresholds are measured relative to palm length. `pinch_release` must be
larger than `pinch_threshold` to prevent repeated clicks from small movements.

The cursor maps to the monitor focused at startup, or the output name entered
in **Monitor** (for example `DP-1`). Coordinates account for monitor scaling,
rotation, and offsets. Restart after changing display layout. Smoothing ranges
from 0.01 (slow/smooth) to 1 (immediate); cursor margin reduces the camera area
needed to reach screen edges. Camera number selects `/dev/videoN`.

Mappings and tuning live in `~/.config/omarchy-motion/config.json` (respects
`XDG_CONFIG_HOME`). Settings and CLI mapping changes restart an active service;
direct JSON edits require an off/on cycle. The builder restricts pointing to
cursor movement and discrete gestures to discrete actions.

```sh
omarchy-motion add 'Raise left hand' --hand Left --gesture hand_raised --action toggle_floating --cooldown 1
omarchy-motion disable 'Right swipe left'
omarchy-motion enable 'Right swipe left'
omarchy-motion list
omarchy-motion remove 'Raise left hand'
```

To turn off without the widget: `systemctl --user stop omarchy-motion.service`.
If startup fails, inspect `journalctl --user -u omarchy-motion -n 40`. Check that
model paths exist, the camera is available, and the service was started from the
Hyprland session using `omarchy-motion on` (which imports its display environment).

## Development and validation

```sh
python -m unittest discover -s tests -v
uv build
# Optional: test provisioned models on a blank image without opening a camera
.venv/bin/python scripts/check_models.py ~/.local/share/omarchy-motion/models
```

The 16 engine, configuration, backend, and lifecycle tests use synthetic landmarks and mocked
desktop commands. They need no camera, models, or third-party dependencies.
Validated with Python 3.12.14, MediaPipe 0.10.35, and OpenCV 4.14.0; the two real
models also passed blank-frame inference. The staged systemd unit validates and
the widget passes QML syntax parsing. These checks do not establish live accuracy.
Hardware acceptance still requires checking pointing, pinch accuracy, hand
labels, workspace/window swipes, preview, and camera release on the target setup.
The preview and settings windows depend on graphical libraries available in the
user session. Recognition thresholds will need tuning for some cameras/users.

Architecture: `runtime.py` owns capture and local inference; `gestures.py` emits
actions; `backend.py` dispatches a fixed set of Hyprland commands; `config.py`
validates and atomically saves settings. The shell widget and settings window
control the service. The application uses no root input daemon or shell command
execution from gesture mappings.

API references: [MediaPipe hands](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python),
[MediaPipe pose](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python),
and [Hyprland dispatchers](https://wiki.hypr.land/0.54.0/Configuring/Dispatchers/).
The shell widget follows the manifest contract shipped by the installed Omarchy shell.
