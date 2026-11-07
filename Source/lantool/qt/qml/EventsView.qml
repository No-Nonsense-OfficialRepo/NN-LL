import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    IconLabel { x: 24; y: 24; iconName: "activity"; text: "Room events" }
    ListView {
        x: 24; y: 76; width: parent.width-48; height: parent.height-100; clip: true; spacing: 12; model: view.s.events
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            required property var modelData
            width: ListView.view.width; height: 85; radius: 3; color: Theme.insetPanel
            GText { x: 14; y: 12; width: parent.width-28; text: modelData.title; font.pixelSize: Theme.typeSmall; color: Theme.brass; elide: Text.ElideRight }
            GText { x: 14; y: 40; width: parent.width-28; text: modelData.message; font.pixelSize: Theme.typeCaption; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
        }
    }
    GText { x: 24; y: 90; text: "Room events and messages will appear here."; visible: view.s.events.length===0; color: Theme.muted }
}
