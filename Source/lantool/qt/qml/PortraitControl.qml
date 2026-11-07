import QtQuick
import QtQuick.Controls
Button {
    id: control
    property color statusColor: "#5A5F66"
    property string portraitIcon: ""
    property string count: ""
    implicitWidth: 31 * .85
    implicitHeight: implicitWidth
    padding: 4
    hoverEnabled: true
    Accessible.name: text
    ToolTip.visible: hovered
    ToolTip.text: text
    background: Rectangle {
        color: control.down ? Qt.darker(control.statusColor, 1.2)
             : control.hovered ? Qt.lighter(control.statusColor, 1.2) : control.statusColor
        border.width: 1
        border.color: Theme.brass
        BottomGlow {
            x: 1; y: parent.height-height+6; width: parent.width-2; height: 14
            visible: control.hovered || control.down || control.activeFocus
            hovered: control.hovered; pressed: control.down; selected: control.activeFocus
        }
    }
    contentItem: Row {
        spacing: 2
        anchors.centerIn: parent
        width: implicitWidth; height: implicitHeight
        transform: Translate { y: control.down ? 1 : 0 }
        Image {
            width: control.count.length ? 9 : 13; height: width
            anchors.verticalCenter: parent.verticalCenter
            visible: control.portraitIcon.length > 0
            source: visible ? "../assets/portrait/" + control.portraitIcon + ".svg" : ""
        }
        Text {
            visible: control.count.length > 0; text: control.count
            anchors.verticalCenter: parent.verticalCenter
            color: "#FFFFFF"; font.family: Theme.ui; font.pixelSize: Theme.typeCaption
        }
    }
}
