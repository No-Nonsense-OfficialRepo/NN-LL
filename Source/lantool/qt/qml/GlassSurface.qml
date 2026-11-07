import QtQuick

Item {
    readonly property bool ready: material.status === Image.Ready
    Rectangle {
        anchors.fill: parent
        visible: Theme.currentName === "Custom"
        color: Theme.fieldSurface
    }
    Image {
        id: material
        anchors.fill: parent
        source: Theme.backgroundSource
        fillMode: Image.Stretch
        opacity: Theme.currentName === "Custom" ? .14 : 1
    }
}
