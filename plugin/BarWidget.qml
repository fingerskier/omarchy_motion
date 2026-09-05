import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
    id: root
    moduleName: "fingerskier.motion"
    property string motionState: "unknown"
    readonly property string executable: Quickshell.env("HOME") + "/.local/bin/omarchy-motion"
    implicitWidth: label.implicitWidth + Style.space(18)
    implicitHeight: barSize

    Text {
        id: label
        anchors.centerIn: parent
        text: root.motionState === "active" ? "Motion ON" : (root.motionState === "inactive" ? "Motion OFF" : "Motion " + root.motionState)
        color: root.bar ? root.bar.barForeground : "white"
        opacity: root.motionState === "active" ? 1 : 0.65
        font.family: root.bar ? root.bar.fontFamily : "sans-serif"
        font.pixelSize: Style.font.body
    }

    Process {
        id: poll
        command: [root.executable, "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.motionState = JSON.parse(text).state }
                catch (e) { root.motionState = "unavailable" }
            }
        }
        onExited: function(exitCode, exitStatus) {
            if (exitCode !== 0) root.motionState = "unavailable"
        }
    }
    Process {
        id: stop
        command: [root.executable, "off"]
        onExited: if (!poll.running) poll.running = true
    }
    Process {
        id: toggle
        command: [root.executable, "toggle"]
        onExited: function(exitCode, exitStatus) {
            if (exitCode !== 0) root.motionState = "error"
            if (!poll.running) poll.running = true
        }
    }
    Timer {
        interval: 1500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: if (!poll.running) poll.running = true
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton)
                Quickshell.execDetached([root.executable, "settings"])
            else if (root.motionState === "activating" || toggle.running)
                stop.running = true
            else
                toggle.running = true
        }
        onEntered: if (root.bar) root.bar.showTooltip(root, "Motion: " + root.motionState + " · Click to toggle · Right-click for settings")
        onExited: if (root.bar) root.bar.hideTooltip(root)
    }
}
