# Omarchy Motion

`omarchy plugin add https://github.com/YOU/YOUR-PLUGIN.git --enable`

Control Omarchy with hand and body movements captured by your webcam. MediaPipe
Hand Landmarker and Pose Landmarker run locally. The application does not send,
record, or save camera frames. Model downloads are an explicit setup step;
normal operation works offline.

## Controls

| Gesture | Default action |
| --- | --- |
| Right index finger extended, ring and little fingers folded | Move cursor |
| Right middle finger pinched to thumb | Left click, once per pinch |
| Right **W** + left **0–9** | Go to that workspace (0 = workspace 10) |
| Right **M** + left **0–9** | Move the focused window there, without following |
| Right **F** + left **1 / 0** | Fullscreen / restore the focused window |
| Right **T** + left **1 / 0** | Float / tile the focused window |
| Hand raised above shoulder | Available in the builder; unassigned by default |

Hold a two-hand chord steady for **0.5 seconds**. It fires once; release either
hand for **0.3 seconds** before another command. Changing the number while
holding the command does not repeat it. Tracking interruptions reset the pending
hold, and brief interruptions do not rearm a fired command. The preview shows
both symbols, the pending action, and a progress bar. When a right-hand command
and a left hand are visible, chords take priority over pointer and pinch.

The **ASL commands** settings tab can build, edit, enable, disable, or remove
chord mappings and tune the hold/release times. Values are workspace 1–10 or
1=on / 0=off for fullscreen/floating. The other tab retains pointer, pinch, body
gestures, and optional legacy swipes. New configurations have no swipe mappings;
existing configurations retain their mappings until you disable them.

Recognition uses a small offline geometric handshape classifier on MediaPipe
landmarks, with optional local calibration templates. It is not a pretrained ASL
alphabet model or an ASL language translator. Only right-hand W/M/F/T and left-hand
0–9 are supported, with left-hand **O** accepted as a synonym for **0**.
Occluded thumbs, especially M versus T, may require calibration.

The global switch starts/stops a user service. **Off releases the webcam and
stops all actions.** It starts off, does not automatically enable at login, and
stops when the graphical session ends. Camera, model, and compositor-connection
errors stop the service and appear in its journal. A dispatcher that Hyprland
rejects (for example moving a window on an empty workspace) is logged and skipped;
the camera keeps running. The bar uses a hand icon, dimmed while Motion is off.
Its dropdown shows starting, active, failed, or off state, and reports active only
after the first successful inference frame. Switching errors appear in the panel
and highlight the icon until the next control action.

## Install

Requires Omarchy with its Quickshell plugin host (Qt 6.8+), Hyprland, libwayland-client, a webcam, `uv`, and
Python 3.11–3.13. Python 3.12 is recommended for the MediaPipe wheels. Tkinter is
needed for the settings window; the CLI works without it. The standard Python
runtime downloaded by uv includes Tk on supported Linux builds.

For an installation managed by `omarchy plugin update`:

```sh
omarchy plugin add https://github.com/fingerskier/omarchy_motion.git
cd ~/.config/omarchy/plugins/fingerskier.motion
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-motion/venv"
uv sync --locked --python 3.12
"$UV_PROJECT_ENVIRONMENT/bin/python" -c 'import tkinter, mediapipe, cv2, pywayland'
python scripts/install.py
~/.local/bin/omarchy-motion init
~/.local/bin/omarchy-motion models
omarchy plugin enable fingerskier.motion --section right
```

The root `manifest.json` points to `plugin/BarWidget.qml`. The installer creates
the launcher, settings entry, and systemd service while preserving the installed
git checkout. Keep the checkout and its external Python environment in place;
the runtime is installed in editable mode and uses that source tree. Setup leaves
the camera off and preserves user configuration.

If upgrading from the old text-only Motion widget and a plugin rescan still
shows the old interface, run `omarchy restart shell` once to clear its cached
QML component. This does not stop the Motion worker.

**Keep the Python environment outside a managed plugin checkout.** Omarchy's
validator rejects symlinks anywhere inside a plugin, including those in `.venv`.
Its update command pulls code and reloads the shell; it does not install Python
dependencies or restart Motion. Complete an update with:

```sh
omarchy-motion off
omarchy plugin update fingerskier.motion
cd ~/.config/omarchy/plugins/fingerskier.motion
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-motion/venv"
uv sync --locked --python 3.12
python scripts/install.py
# Switch back on when ready:
omarchy-motion on
```

For a development checkout outside the plugin directory, `uv sync --python 3.12`
and `python scripts/install.py --runtime "$PWD/.venv/bin/omarchy-motion"` install a
widget snapshot. This snapshot has no git history and cannot use `omarchy plugin
update`. An existing snapshot must be moved aside before `omarchy plugin add`
can install the same ID. The installer refuses to overwrite a different managed
checkout. To stage installation files without changing the desktop, use
`python scripts/install.py --prefix /tmp/motion-stage`.

Model files live in `$XDG_DATA_HOME/omarchy-motion/models` (normally
`~/.local/share/omarchy-motion/models`). Setup downloads Google's version-1 hand
and pose-lite task bundles over HTTPS, checks them against pinned SHA-256 digests,
and validates their ZIP contents. The pose model loads only while a mapping uses
**hand_raised**; the default mappings run hand tracking alone. For an
air-gapped computer, copy the model files and a preprovisioned Python environment
onto it. There is no network access or automatic download in the tracking loop.
Model files are distributed by Google under their own terms, separately from this repository.

## Uninstall

Close the settings window, then stop and remove the runtime **before** removing
the plugin checkout. From the checkout, run these commands in order:

```sh
python scripts/uninstall.py --remove-venv && omarchy plugin remove fingerskier.motion
```

The uninstaller stops the worker and checks that it is inactive before deleting
the service, command wrapper, and desktop entry, then reloads systemd. If stopping
fails, it preserves those files and exits with an error. The shell command runs
only after runtime cleanup succeeds. Removing the widget alone does not stop
gesture control or release the camera.

`--remove-venv` deletes only the standard external environment under
`$XDG_DATA_HOME/omarchy-motion/venv` (normally `~/.local/share/omarchy-motion/venv`).
Omit it to keep that environment; development environments supplied with
`--runtime` are always left alone. Settings and calibration in
`$XDG_CONFIG_HOME/omarchy-motion` and downloaded models in
`$XDG_DATA_HOME/omarchy-motion/models` are preserved for reinstallation. You can
delete those folders separately if you no longer want that data.

For a development snapshot, run the uninstaller from the original source
checkout. For an isolated installation test, both installer and uninstaller
accept `--prefix /tmp/motion-stage`; this mode never contacts your user service
or removes the staged widget directory.

## Use and calibrate

Click the **hand icon** in the status bar to show/hide the Motion dropdown. It
uses the same themed, anchored panel as built-in Omarchy widgets. Escape or a
click outside dismisses it; Tab moves between controls. Opening or closing the
panel does not switch gesture control on or off.

Inside the panel:

- **Motion ON/OFF** starts/stops the service and webcam.
- The **camera view** shows landmarks, detected signs, and the pending command.
- **ASL commands**, **Test mode**, **Mirror**, and **Swap hands** update the
  corresponding setting, preserving your other tuning, mappings, and samples.
- **Gestures, calibration & camera settings** opens the full editor.

Quick-setting changes restart an active service. Test mode keeps tracking and
preview running while sending no desktop actions. The application launcher also
offers the full **Omarchy Motion** settings window.

```sh
omarchy-motion settings
omarchy-motion on
omarchy-motion off
omarchy-motion toggle
omarchy-motion status
```

Start by opening the dropdown, selecting **Test mode**, then switching Motion on.
The embedded preview displays tracked landmarks. Detected discrete actions appear in
`journalctl --user -u omarchy-motion -f`; test mode sends no desktop commands.
Use **Motion OFF** to stop. Turn off test mode when ready to control the desktop.
The full editor also offers **Separate preview window** (the `preview` setting);
Escape or Q in that optional window stops Motion. Escape in the dropdown only
closes the panel.

The embedded preview reuses the worker's camera capture. While the dropdown is
open, one helper reads annotated JPEG snapshots, capped at 10 fps, through a
user-only Unix socket in `XDG_RUNTIME_DIR`. Frames remain in memory: there is no
HTTP server, TCP port, recording, or image file. Closing the panel stops its
helper and clears the displayed image; preview encoding stops within half a
second. Off, disconnect, or a stalled worker clears the image instead of showing
an old frame. During normal updates, the last decoded image stays visible while
the next image loads, without flashing the waiting message. Tracking can continue
while the panel is hidden.

Try **right W + left 3** first. ASL 3 extends the **thumb, index, and middle**
fingers; W extends index, middle, and ring. ASL 6/7/8/9 touch thumb to
little/ring/middle/index respectively, with the other fingers extended. Face
your palms toward the camera and keep both hands separate and fully visible.
M tucks the thumb under three fingers; T places it between index and middle.

For zero, make a rounded **O** with your left hand: bring thumb and index tips
together and curve the other fingers together. They do not need to fold tightly
into your palm. O and 0 share the same mappings and calibration samples; the
preview displays the canonical symbol **0**. W + O goes to workspace 10,
M + O moves there, F + O restores fullscreen, and T + O tiles the window.

If a symbol is unknown (`?`) or incorrect, open **ASL commands → Calibrate**,
choose its hand and symbol, and click **Capture sample**, or run:

```sh
omarchy-motion calibrate --hand Right --symbol M
omarchy-motion calibrate --hand Left --symbol 3
omarchy-motion calibrate --hand Left --symbol O
```

Watch the two-second preview countdown, then hold the selected sign still for
one second. Capture pauses desktop actions and uses the existing service's
camera; the global off switch still stops it. It saves only numeric handshape
features in `asl_samples` in your configuration, with up to five samples per
symbol. Repeat at slightly different natural angles if needed. Samples take
effect immediately; no model download or separate training job is needed.
Ambiguous template matches are rejected. **Clear samples** restores geometric
recognition for the selected symbol. Pointer/pinch tuning is independent of ASL
calibration. Settings saves preserve calibration made while the window was open.
After capture finishes or times out, lower both hands out of view briefly to
resume desktop control.

Use even lighting with both hands visible. Hand names mean your anatomical left
and right. If camera mirroring makes them appear reversed, use **Swap hand labels**.
Turning **Mirror camera** off also reverses cursor and swipe direction, since both
follow the preview image.
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
omarchy-motion disable 'Raise left hand'
omarchy-motion enable 'Raise left hand'
omarchy-motion list
omarchy-motion remove 'Raise left hand'
```

To turn off without the widget: `systemctl --user stop omarchy-motion.service`.
If startup fails, inspect `journalctl --user -u omarchy-motion -n 40`. Check that
model paths exist, the camera is available, and the service was started from the
Hyprland session using `omarchy-motion on` (which imports its display environment).
Workspace/window actions support both legacy and Lua configuration providers.
An explicit Lua syntax rejection selects native `hl.dsp` commands for subsequent
actions. Ordinary action failures are never retried. Actions go over Hyprland's control socket, located through
`HYPRLAND_INSTANCE_SIGNATURE`; without it, a single running instance is detected.
Pointer motion and clicks use a persistent `zwlr_virtual_pointer_v1` device on
`WAYLAND_DISPLAY`, mapped to the selected output. This sends real pointer events
to the surface under the cursor, including bars and launchers implemented with
layer-shell. It needs manager protocol version 2 and `wl_output` version 4,
available on the tested Hyprland 0.56.2. Unsupported compositors fail startup with
an explicit error; there is no focused-window-only click fallback. Keep the
Wayland display and Hyprland instance variables from the same session.

## Development and validation

```sh
python -m unittest discover -s tests -v
uv build
# Optional: test provisioned models on a blank image without opening a camera
.venv/bin/python scripts/check_models.py ~/.local/share/omarchy-motion/models
# Live compositor test: briefly creates and clicks two controlled layer surfaces
.venv/bin/python scripts/check_pointer.py --monitor eDP-1
```

The engine, configuration, backend, pointer, and lifecycle tests use synthetic
landmarks, a fake Hyprland socket, and mocked models. They need no camera, models,
or third-party dependencies, but the socket test needs permission to bind a local
Unix socket. The live test additionally needs Quickshell and PyWayland. It checks
press, release, and click events on temporary bar-like and launcher-like
layer-shell surfaces, then closes them and restores the cursor. It does not
activate your real launcher or application actions or open the webcam.
On 2026-09-05 all 62 automated tests passed, and the live layer-surface test passed
on both eDP-1 and HDMI-A-1 with Hyprland 0.56.2, including display scaling and offset.
Validated with Python 3.12.14, MediaPipe 0.10.35, and OpenCV 4.14.0; the two real
models also passed blank-frame inference. The staged systemd unit validates and
the widget passes QML syntax parsing. These checks do not establish live accuracy.
The ASL tests cover the finite vocabulary rules, feature invariance, template
ambiguity, calibration persistence, dwell/rearm behavior, pointer arbitration,
configuration merging, and parameterized desktop dispatch. They do not measure
recognition accuracy on real signing hands. The user has confirmed working
pointing; physical ASL command accuracy remains a hardware acceptance check.
Live Lua-provider checks on Hyprland 0.56.2 also passed using a temporary window:
fullscreen set/set/restore, floating enable/enable/disable, silent window move,
workspace switch, and restoration of the original workspace. This caught and
fixed the legacy dispatcher syntax rejection on Lua-based Omarchy installations.
The native dropdown also passed a live Quickshell check: its camera image decoded,
the actual panel ON/OFF controls cleared and resumed the image, and close cleared
it. Installed shell summon/hide routing passed after a shell restart cleared the
old widget cache. Hiding stopped preview demand; switching off removed the private
socket and `fuser /dev/video0` confirmed the camera was released.
The preview and settings windows depend on graphical libraries available in the
user session. Recognition thresholds will need tuning for some cameras/users.

Installer/uninstaller tests cover staged install/update/removal, managed checkout
preservation, custom XDG locations, repeat removal, data preservation, and refusal
to remove an unrecognized or symlinked environment. Mocked systemd checks verify
that stop failures preserve files and that removal follows confirmed shutdown.

Architecture: `runtime.py` owns capture and local inference; `gestures.py` emits
actions; `asl.py` recognizes handshapes, `chords.py` gates two-hand commands, and
`calibration.py` captures local templates through the service; `backend.py` sends
a fixed set of workspace/window dispatchers over Hyprland's IPC socket;
`pointer.py` owns the Wayland device, bounded acknowledgements, and complete click
press/release frames; `config.py` validates and atomically saves settings. The shell widget and settings window
control the service. The application uses no root input daemon or shell command
execution from gesture mappings.
`panel.py` provides the private preview socket, its panel-only bridge, and
validated quick-setting updates. The widget uses Omarchy's shared `Panel`,
`BarIconButton`, `KeyboardPanel`, and themed controls.

API references: [MediaPipe hands](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python),
[MediaPipe pose](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python),
and [Hyprland dispatchers](https://wiki.hypr.land/Configuring/Basics/Dispatchers/).
The shell widget follows the manifest contract shipped by the installed Omarchy shell.
The [virtual-pointer protocol](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-virtual-pointer-unstable-v1.xml)
is vendored with generated bindings and its upstream license notice.

## License

Project code is licensed under [Apache License 2.0](LICENSE), with attribution
in [NOTICE](NOTICE). The vendored Wayland protocol
retains Josef Gajdusek's MIT notice. MediaPipe model files and dependencies retain
their own licenses; the project license does not relicense those assets.
