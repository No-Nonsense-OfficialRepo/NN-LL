import QtQuick
import QtQuick.Controls
Item {
 id: stat
 property string iconName: "user"
 property string text: ""
 property string description: ""
 property color textColor: Theme.muted
 implicitWidth: contents.width; implicitHeight: 20
 Accessible.role: Accessible.StaticText
 Accessible.name: description || text
 HoverHint { description: stat.description }
 Row { id: contents; spacing: 7; anchors.verticalCenter: parent.verticalCenter
  Image { width: 15; height: 15; source: Theme.iconPath+stat.iconName+".svg"; anchors.verticalCenter: parent.verticalCenter }
  GText { text: stat.text; color: stat.textColor; font.pixelSize: Theme.typeSmall; anchors.verticalCenter: parent.verticalCenter }
 }
}
