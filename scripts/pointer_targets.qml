import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
    id: root
    readonly property var output: Quickshell.screens.find(s => s.name === Quickshell.env("MOTION_TEST_OUTPUT"))
    PanelWindow {
        screen: root.output
        anchors { top: true; left: true }
        margins { top: 35; left: 30 }
        implicitWidth: 240
        implicitHeight: 50
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "motion-test-bar"
        color: "#244d38"
        Text { anchors.centerIn: parent; text: "Motion: bar click test"; color: "white" }
        MouseArea {
            anchors.fill: parent
            onPressed: console.log("MOTION_BAR_PRESS")
            onReleased: console.log("MOTION_BAR_RELEASE")
            onClicked: console.log("MOTION_BAR_CLICK")
        }
    }
    PanelWindow {
        screen: root.output
        anchors { top: true; left: true }
        margins { top: 120; left: 30 }
        implicitWidth: 240
        implicitHeight: 100
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "motion-test-launcher"
        color: "#283d62"
        Text { anchors.centerIn: parent; text: "Motion: launcher click test"; color: "white" }
        MouseArea {
            anchors.fill: parent
            onPressed: console.log("MOTION_LAUNCHER_PRESS")
            onReleased: console.log("MOTION_LAUNCHER_RELEASE")
            onClicked: console.log("MOTION_LAUNCHER_CLICK")
        }
    }
}
