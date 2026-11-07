import QtQuick
Panel {
    id: view
    property var s
    GUButton { x: 24; y: 18; width: 170; height: 36; text: "Back to game"; edge: "left"; iconName: "back"; onClicked: backend.navigate("details") }
    GText { x: 24; y: 88; text: "Host-selected executable"; font.pixelSize: Theme.typeSmall }
    GUField { x: 24; y: 111; width: parent.width - 48; text: view.s.selected.exe || ""; readOnly: true }
    GText { x: 24; y: 187; text: "Launch arguments"; font.pixelSize: Theme.typeSmall }
    GUField { id: args; x: 24; y: 210; width: parent.width - 48; text: view.s.selected.args || ""; readOnly: !!view.s.selected.argsManagedByHost }
    GText { x: 24; y: 260; text: "Use {name} for your player name and {host_ip} for the active host."; color: Theme.brass; font.pixelSize: Theme.typeCaption }
    GText { x: 24; y: 292; visible: !!view.s.selected.argsManagedByHost; text: "Launch parameters are managed by the Host for this room."; color: Theme.muted; font.pixelSize: Theme.typeSmall }
    GText { x: 24; y: 330; text: "Game directory"; font.pixelSize: Theme.typeSmall }
    GUField { x: 24; y: 353; width: parent.width - 48; text: view.s.selected.directory || ""; readOnly: true }
    Row { x: 24; y: parent.height - 90; spacing: 14
        GUButton { text: "Save launch settings"; edge: "left"; iconName: "save-launch"; width: 200; primary: true; visible: !view.s.selected.argsManagedByHost; onClicked: backend.saveLaunchArgs(args.text) }
    }
}
