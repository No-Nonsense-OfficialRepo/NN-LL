import QtQuick
import QtQuick.Layouts
RowLayout {
 id: row
 property string iconName: "network"
 property string value: ""
 property string description: ""
 property string copyLabel: "Copy"
 spacing: 12
 implicitHeight: 44
 IconLabel { iconName: row.iconName; description: row.description; Layout.preferredWidth: 20; Layout.preferredHeight: 24 }
 CopyText { objectName: row.iconName === "key" ? "hostRoomCodeCopy" : "hostIpCopy"; text: row.value || "—"; copyValue: row.value; description: row.copyLabel; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: 44; verticalAlignment: Text.AlignVCenter; elide: Text.ElideMiddle; font.pixelSize: Theme.typeSmall
 }
}
