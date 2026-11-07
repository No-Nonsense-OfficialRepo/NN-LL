import QtQuick
import QtQuick.Controls
Switch {
    id: control
    property string helpText: "Turn this setting on or off."
    HoverHint { description: control.helpText }
    implicitWidth: 42
    implicitHeight: 23
    padding: 0
    indicator: Rectangle {
        width: 42; height: 23; radius: 12
        color: control.checked ? Theme.toggleActive : Theme.toggleIdle
        border.color: control.activeFocus ? Theme.paper : "transparent"
        Rectangle {
            width: 17; height: 17; y: 3; radius: 9
            x: control.checked ? 22 : 3
            color: Theme.toggleThumb
            Behavior on x { NumberAnimation { duration: 100 } }
        }
    }
}
