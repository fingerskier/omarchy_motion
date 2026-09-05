import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
    id: root
    moduleName: "fingerskier.motion"
    property string motionState: "unknown"
    // Last failure from switching on/off; shown until the next click so it cannot be missed.
    property string lastError: ""
    property string pendingError: ""
    readonly property string executable: Quickshell.env("HOME") + "/.local/bin/omarchy-motion"
    implicitWidth: label.implicitWidth + Style.space(18)
    implicitHeight: barSize

    function stateText() {
        if (root.lastError) return "Motion error"
        if (root.motionState === "active") return "Motion ON"
        if (root.motionState === "inactive") return "Motion OFF"
        return "Motion " + root.motionState
    }

    function tooltipText() {
        return "Motion: " + root.motionState
            + (root.lastError ? "\n" + root.lastError : "")
            + "\nClick to toggle · Right-click for settings"
    }

    // The bar's tooltip takes a text snapshot, so refresh it while hovered when the state or error changes.
    function refreshTooltip() {
        if (root.bar && mouseArea.containsMouse) root.bar.showTooltip(root, root.tooltipText())
    }
    onMotionStateChanged: refreshTooltip()
    onLastErrorChanged: refreshTooltip()

    function finished(exitCode) {
        if (exitCode !== 0)
            root.lastError = root.pendingError || ("omarchy-motion exited with code " + exitCode)
        if (!poll.running) poll.running = true
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.stateText()
        color: root.lastError ? (root.bar ? root.bar.urgent : "red") : (root.bar ? root.bar.barForeground : "white")
        opacity: root.motionState === "active" || root.lastError ? 1 : 0.65
        font.family: root.bar ? root.bar.fontFamily : "sans-serif"
        font.pixelSize: Style.font.body
    }

    // systemd answers this in a few milliseconds; it used to start a Python interpreter every tick.
    Process {
        id: poll
        command: ["systemctl", "--user", "is-active", "omarchy-motion.service"]
        stdout: StdioCollector {
            onStreamFinished: {
                const state = text.trim()
                root.motionState = state ? state : "unavailable"
            }
        }
    }
    Process {
        id: stop
        command: [root.executable, "off"]
        stderr: StdioCollector { onStreamFinished: root.pendingError = text.trim() }
        onExited: function(exitCode, exitStatus) { root.finished(exitCode) }
    }
    Process {
        id: toggle
        command: [root.executable, "toggle"]
        stderr: StdioCollector { onStreamFinished: root.pendingError = text.trim() }
        onExited: function(exitCode, exitStatus) { root.finished(exitCode) }
    }
    Timer {
        interval: 1500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: if (!poll.running) poll.running = true
    }
    MouseArea {
        id: mouseArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton) {
                Quickshell.execDetached([root.executable, "settings"])
                return
            }
            root.lastError = ""
            root.pendingError = ""
            if (root.motionState === "activating" || toggle.running)
                stop.running = true
            else
                toggle.running = true
        }
        onEntered: if (root.bar) root.bar.showTooltip(root, root.tooltipText())
        onExited: if (root.bar) root.bar.hideTooltip(root)
    }
}
