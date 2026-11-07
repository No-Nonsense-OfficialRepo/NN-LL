import QtQuick
import QtQuick.Controls
AbstractButton {
 id: option
 property string themeName: "Pearl"
 signal editCustom()
 readonly property QtObject scheme: Theme.paletteFor(themeName)
 readonly property bool selected: Theme.currentName===themeName
 implicitWidth: 200; implicitHeight: 108; hoverEnabled: true
 Accessible.name: themeName==="Custom" ? "Edit Custom theme" : "Use "+themeName+" theme"
 onClicked: if (themeName==="Custom") editCustom(); else Theme.apply(themeName)
 onHoveredChanged: { if(hovered) HoverHelp.begin(option,"Apply the "+themeName+" colour scheme and its supplied fonts."); else HoverHelp.end(option); }
 onPressed: HoverHelp.end(option)
 onVisibleChanged: if(!visible) HoverHelp.end(option)
 Component.onDestruction: HoverHelp.end(option)
 background: Rectangle {
  color: option.scheme.dark; radius: 3
  Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: option.selected || option.activeFocus ? 2 : .6; color: option.selected || option.activeFocus ? option.scheme.selectedGold : option.scheme.border }
 }
 contentItem: Item {
  GText { x: Math.min(16, parent.width*.08); y: 14; width: parent.width-2*x; text: option.themeName; color: option.scheme.paper; font.pixelSize: Theme.scaledFont(parent.width < 110 ? 10 : 12); wrapMode: Text.WordWrap }
  Row { x: Math.min(16, parent.width*.08); y: 58; spacing: parent.width < 110 ? 5 : 9
   Repeater { model: [option.scheme.brass,option.scheme.selectedGold,option.scheme.green]
    Rectangle { required property color modelData; width: 13; height: 13; radius: 7; color: modelData }
   }
  }
  Canvas {
   anchors.right: parent.right; y: parent.width < 110 ? 80 : 15; anchors.rightMargin: Math.min(15, parent.width*.08); width: 18; height: 18
   visible: option.selected
   Connections { target: Theme; function onCurrentNameChanged(){ selectionMark.requestPaint(); } }
   id: selectionMark
   onPaint: { let c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=String(option.scheme.selectedGold);c.lineWidth=1.5;c.beginPath();c.moveTo(3,9);c.lineTo(7,13);c.lineTo(15,4);c.stroke(); }
  }
 }
}
