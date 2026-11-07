import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    IconLabel { x: 24; y: 21; iconName: "grid"; description: "Shared game catalog" }
    Row { x: 24; y: 77
        GText { width: 345; text: "GAME FOLDER"; color: Theme.brass; font.pixelSize: Theme.typeCaption }
        GText { width: 430; text: "LAUNCH FILE"; color: Theme.brass; font.pixelSize: Theme.typeCaption }
        GText { text: "EVENT PLAYLIST"; color: Theme.brass; font.pixelSize: Theme.typeCaption }
    }
    ListView {
        id: list; x: 24; y: 108; width: parent.width - 48; height: parent.height - 228; clip: true; spacing: 10; model: view.s.catalog
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            required property var modelData
            width: ListView.view.width; height: 59; radius: 3; color: mouse.containsMouse ? Theme.hover : Theme.insetPanel
            GText { x: 16; y: 20; width: 310; text: modelData.name; font.pixelSize: Theme.typeSmall; elide: Text.ElideRight }
            GText { x: 345; y: 21; width: 410; text: modelData.exe; color: Theme.muted; font.pixelSize: Theme.typeCaption; elide: Text.ElideMiddle }
            GText { x: parent.width - 230; y: 21; text: modelData.enabled ? "Included" : "Not included"; color: modelData.enabled ? Theme.green : Theme.muted; font.pixelSize: Theme.typeCaption }
            MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onEntered: HoverHelp.begin(mouse,modelData.name+" — edit executable, artwork and sharing."); onExited: HoverHelp.end(mouse); cursorShape: Qt.PointingHandCursor; onClicked: backend.editFolder(modelData.folder) }
        }
    }
    GText { x: 24; y: 140; visible: view.s.catalog.length===0; text: "Add a game folder directly inside Game Directory to get started."; color: Theme.muted }
    Row { x: 24; y: parent.height - 90; spacing: 14
        GUButton { text: "Add game folder"; edge: "left"; width: 204; primary: true; onClicked: backend.addGame() }
        GUButton { text: "Rescan folders"; edge: "center"; width: 190; onClicked: backend.navigate("catalog") }
        GUButton { text: "Back to room"; edge: "right"; width: 180; onClicked: backend.navigate("room") }
    }
}
