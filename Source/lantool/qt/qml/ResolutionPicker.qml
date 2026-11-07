import QtQuick
import QtQuick.Controls
ComboBox {
 id: control
 property bool host: false
 objectName: host ? "hostResolutionSelector" : "clientResolutionSelector"
 model: host ? WindowPreferences.hostChoices : WindowPreferences.choices
 textRole: "label"
 valueRole: "key"
 currentIndex: WindowPreferences.indexFor(host?WindowPreferences.hostResolution:WindowPreferences.clientResolution,host)
 implicitHeight: 40
 hoverEnabled: true
 font.family: Theme.ui
 font.pixelSize: Theme.typeSmall
 Accessible.name: host ? "Host window resolution, 9:21" : "Client window resolution, 16:9"
 onActivated: WindowPreferences.apply(model[index].key,host)
 onHoveredChanged: {
  if(hovered) HoverHelp.begin(control,"Choose the "+(host?"Host (9:21)":"Client (16:9)")+" window resolution. Larger choices fit the current display. Applies immediately and saves automatically.");
  else HoverHelp.end(control);
 }
 onPressedChanged: if(pressed) HoverHelp.end(control)
 Component.onDestruction: HoverHelp.end(control)
 contentItem: GText { text: control.displayText; leftPadding: 12; rightPadding: 34; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
 indicator: Image { x: control.width-width-14; y: (control.height-height)/2; width: 13; height: 13; rotation: 90; source: Theme.iconPath+"chevron.svg" }
 background: Rectangle {
  color: Theme.fieldSurface
  Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: control.activeFocus ? 1.5 : .7; color: control.activeFocus ? Theme.brass : Theme.border }
 }
 delegate: ItemDelegate {
  required property int index
  required property var modelData
  width: control.width; height: 38
  highlighted: control.highlightedIndex===index
  contentItem: GText { text: modelData.label; leftPadding: 8; verticalAlignment: Text.AlignVCenter }
  background: Rectangle { color: highlighted ? Theme.hover : Theme.dark }
 }
 popup: Popup {
  y: control.height+4; width: control.width; padding: 6
  implicitHeight: contentItem.implicitHeight+12
  background: ChamferPopup {}
  contentItem: ListView {
   clip: true; implicitHeight: Math.min(contentHeight,280)
   model: control.popup.visible ? control.delegateModel : null
   currentIndex: control.highlightedIndex
   ScrollIndicator.vertical: ScrollIndicator {}
  }
 }
}
