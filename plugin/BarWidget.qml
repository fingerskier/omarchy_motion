import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui as Ui
import qs.Commons

Ui.Panel {
    id: root
    moduleName: "fingerskier.motion"
    ipcTarget: "fingerskier.motion"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    property string motionState: "unknown"
    property string lastError: ""
    property string pendingError: ""
    property var live: ({})
    property var options: ({})
    property string frameSource: ""
    property double lastPacket: 0
    readonly property bool previewReady: camera.hasFrame && frameSource !== ""
    readonly property bool active: motionState === "active"
    readonly property color foreground: Color.popups.text
    readonly property string executable: Quickshell.env("HOME") + "/.local/bin/omarchy-motion"

    function refresh() {
        if (!poll.running)
            poll.running = true;
    }
    function run(args) {
        if (action.running)
            return;
        lastError = "";
        pendingError = "";
        action.command = [executable].concat(args);
        action.running = true;
    }
    function power() {
        if (active || motionState === "activating" || action.running) {
            lastError = "";
            pendingError = "";
            stop.running = true;
        } else
            run(["on"]);
    }
    function setOption(key) {
        run(["set", key, options[key] ? "false" : "true"]);
    }
    function finish(code) {
        if (code !== 0)
            lastError = pendingError || "Motion command failed. Check the service log.";
        refresh();
    }
    function readPacket(line) {
        if (!opened)
            return;
        try {
            const packet = JSON.parse(line);
            lastPacket = Date.now();
            live = packet;
            if (packet.settings)
                options = packet.settings;
            frameSource = active && packet.connected ? (packet.image || "") : "";
            if (packet.error)
                lastError = packet.error;
        } catch (e) {
            frameSource = "";
            live = ({});
            lastError = "Could not read Motion preview";
        }
    }
    onOpenedChanged: {
        frameSource = "";
        live = ({});
        if (opened)
            refresh();
    }
    onMotionStateChanged: if (!active) {
        frameSource = "";
        live = ({});
    }

    Ui.BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        slotSize: Style.bar.statusSlot
        dimmed: !root.active && !root.lastError
        tooltipText: "Motion " + (root.active ? "ON" : root.motionState) + " · Click for controls"
        iconComponent: Canvas {
            property color foreground: root.lastError ? Color.urgent : root.barForeground
            onForegroundChanged: requestPaint()
            onPaint: {
                const p = getContext("2d");
                p.clearRect(0, 0, width, height);
                p.save();
                p.scale(width / 24, height / 24);
                p.strokeStyle = foreground;
                p.lineWidth = 1.7;
                p.lineCap = "round";
                p.lineJoin = "round";
                p.beginPath();
                p.moveTo(7, 13);
                p.lineTo(7, 5);
                p.bezierCurveTo(7, 2.8, 10, 2.8, 10, 5);
                p.lineTo(10, 11);
                p.lineTo(10, 3);
                p.bezierCurveTo(10, 0.8, 13, 0.8, 13, 3);
                p.lineTo(13, 11);
                p.lineTo(13, 4.5);
                p.bezierCurveTo(13, 2.3, 16, 2.3, 16, 4.5);
                p.lineTo(16, 12);
                p.lineTo(16, 7.5);
                p.bezierCurveTo(16, 5.3, 19, 5.3, 19, 7.5);
                p.lineTo(19, 15);
                p.bezierCurveTo(19, 23, 11, 24, 7, 18);
                p.lineTo(3, 12);
                p.bezierCurveTo(2, 10, 4, 9, 5, 10.5);
                p.lineTo(7, 13);
                p.stroke();
                p.restore();
            }
        }

        onPressed: function (b) {
            if (b === Qt.LeftButton || b === Qt.RightButton)
                root.toggle();
        }
    }
    Process {
        id: poll
        command: ["systemctl", "--user", "is-active", "omarchy-motion.service"]
        stdout: StdioCollector {
            onStreamFinished: root.motionState = text.trim() || "unavailable"
        }
    }
    Process {
        id: action
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.pendingError = text.trim()
        }
        onExited: function (code) {
            root.finish(code);
        }
    }
    Process {
        id: stop
        command: [root.executable, "off"]
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.pendingError = text.trim()
        }
        onExited: function (code) {
            root.finish(code);
        }
    }
    Process {
        id: preview
        command: [root.executable, "panel"]
        running: root.opened
        stdout: SplitParser {
            onRead: function (line) {
                root.readPacket(line);
            }
        }
        onExited: function (code) {
            root.frameSource = "";
            if (root.opened && code !== 0)
                root.lastError = "Preview disconnected. Reopen the panel to retry.";
        }
    }
    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            root.refresh();
            if (root.opened && Date.now() - root.lastPacket > 2000) {
                root.frameSource = "";
                root.live = ({});
            }
        }
    }
    Ui.KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: powerToggle
        contentWidth: panel.fittedContentWidth(Style.space(440))
        contentHeight: panel.fittedContentHeight(column.implicitHeight)
        // Native controls use Tab focus; Escape dismisses from any control.
        Item {
            anchors.fill: parent
            Keys.onEscapePressed: root.close()
            Flickable {
                anchors.fill: parent
                clip: true
                contentWidth: width
                contentHeight: column.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: column
                    width: parent.width
                    spacing: Style.space(10)
                    Ui.Toggle {
                        id: powerToggle
                        width: parent.width
                        label: "Motion " + (root.active ? "ON" : root.motionState === "inactive" ? "OFF" : root.motionState)
                        description: root.active ? "Offline gesture control" : "Switch on to use the camera"
                        checked: root.active || root.motionState === "activating"
                        onClicked: root.power()
                    }
                    Rectangle {
                        width: parent.width
                        height: width * 0.75
                        color: "#141414"
                        radius: Style.cornerRadius
                        clip: true
                        Image {
                            id: camera
                            objectName: "motionCamera"
                            property bool hasFrame: false
                            anchors.fill: parent
                            source: root.opened ? root.frameSource : ""
                            cache: false
                            // Data URLs load asynchronously. Keep the last decoded
                            // frame through Loading instead of flashing the placeholder.
                            retainWhileLoading: true
                            visible: root.previewReady
                            onSourceChanged: if (source.toString() === "")
                                hasFrame = false
                            onStatusChanged: {
                                if (status === Image.Ready)
                                    hasFrame = true;
                                else if (status === Image.Error)
                                    hasFrame = false;
                            }
                            fillMode: Image.PreserveAspectFit
                        }
                        Text {
                            anchors.centerIn: parent
                            width: parent.width - Style.space(24)
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            visible: !root.previewReady
                            text: root.active ? "Waiting for camera…" : "Camera off"
                            color: "#cccccc"
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                        }
                    }
                    Text {
                        width: parent.width
                        text: root.lastError || root.live.status || (root.active ? "Show both hands to form a command" : "Motion OFF releases the webcam")
                        textFormat: Text.PlainText
                        color: root.lastError ? Color.urgent : root.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        wrapMode: Text.WordWrap
                    }
                    Rectangle {
                        width: parent.width
                        height: Style.space(3)
                        color: Qt.alpha(root.foreground, 0.15)
                        Rectangle {
                            width: parent.width * Math.max(0, Math.min(1, root.live.progress || 0))
                            height: parent.height
                            color: Color.accent
                        }
                    }
                    Row {
                        width: parent.width
                        spacing: Style.space(8)
                        Ui.Toggle {
                            width: (parent.width - parent.spacing) / 2
                            label: "ASL commands"
                            checked: !!root.options.chords_enabled
                            enabled: !action.running && !stop.running && root.options.chords_enabled !== undefined
                            onClicked: root.setOption("chords_enabled")
                        }
                        Ui.Toggle {
                            width: (parent.width - parent.spacing) / 2
                            label: "Test mode"
                            checked: !!root.options.dry_run
                            enabled: !action.running && !stop.running && root.options.dry_run !== undefined
                            onClicked: root.setOption("dry_run")
                        }
                    }
                    Row {
                        width: parent.width
                        spacing: Style.space(8)
                        Ui.Toggle {
                            width: (parent.width - parent.spacing) / 2
                            label: "Mirror"
                            checked: !!root.options.mirror
                            enabled: !action.running && !stop.running && root.options.mirror !== undefined
                            onClicked: root.setOption("mirror")
                        }
                        Ui.Toggle {
                            width: (parent.width - parent.spacing) / 2
                            label: "Swap hands"
                            checked: !!root.options.swap_hands
                            enabled: !action.running && !stop.running && root.options.swap_hands !== undefined
                            onClicked: root.setOption("swap_hands")
                        }
                    }
                    Ui.Button {
                        width: parent.width
                        text: "Gestures, calibration & camera settings"
                        bordered: true
                        focusable: true
                        onClicked: {
                            root.close();
                            Quickshell.execDetached([root.executable, "settings"]);
                        }
                    }
                    Text {
                        width: parent.width
                        text: "W + number: workspace · M + number: move window\nF + 1/0: fullscreen · T + 1/0: floating · O = 0\nHold 0.5s, then release. Preview stays on this device."
                        color: Qt.alpha(root.foreground, 0.65)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
