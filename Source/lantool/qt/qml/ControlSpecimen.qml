import QtQuick
import QtQuick.Controls
ApplicationWindow {
 width: 1312; height: 1000; visible: true; color: "#D2D7DC"; title: "Pearl control reference"
 GlassSurface { anchors.fill: parent }
 GText { x: 58; y: 40; text: "B U T T O N   S T Y L E S"; font.pixelSize: Theme.typeSmall }
 Rectangle { x: 380; y: 50; width: 870; height: .6; color: Theme.border }
 Repeater {
  model: ["left", "center", "right"]
  Column {
   required property string modelData
   required property int index
   x: 80+index*420; y: 124; spacing: 24
   GText { text: parent.modelData.toUpperCase()+" BUTTONS"; font.letterSpacing: 3; font.pixelSize: Theme.typeSmall }
   GText { text: parent.modelData==="center" ? "Underline fades in both directions" : "Directional edge / fading light"; color: Theme.muted; font.pixelSize: Theme.typeCaption }
   Repeater {
    model: ["PLAY", "SETTINGS", "PROFILE", "EXIT"]
    GUButton { iconOnly: false; required property string modelData; required property int index; text: modelData; iconName: ["play","settings","user","power"][index]; width: 280; height: 60; primary: index===0; edge: parent.modelData }
   }
  }
 }
 Rectangle { x: 40; y: 550; width: 1232; height: .6; color: Theme.border }
 GText { x: 58; y: 585; text: "SMALL DIAMOND CONTROLS"; font.letterSpacing: 3; font.pixelSize: Theme.typeSmall }
 Repeater {
  model: [false,true]
  Column {
   required property bool modelData
   required property int index
   x: 80+index*650; y: 646; spacing: 24
   GText { text: parent.modelData ? "SELECTED / LEFT + RIGHT" : "UNSELECTED / TOP + BOTTOM"; font.letterSpacing: 2; font.pixelSize: Theme.typeCaption }
   Row { spacing: 60
    Repeater { model: ["diamond","settings","grid","power"]
     DiamondButton { required property string modelData; iconName: modelData; width: 72; height: 72; selected: parent.parent.modelData; Accessible.name: "Selection specimen" }
    }
   }
  }
 }
 Rectangle { x: 40; y: 815; width: 1232; height: .6; color: Theme.border }
 Row { x: 80; y: 864; spacing: 40
  GUButton { iconOnly: false; text: "NORMAL"; width: 220; height: 54 }
  GUButton { iconOnly: false; text: "PRIMARY"; primary: true; width: 220; height: 54 }
  GUButton { iconOnly: false; text: "SELECTED"; selected: true; width: 220; height: 54 }
  GUButton { iconOnly: false; text: "DISABLED"; enabled: false; width: 220; height: 54 }
 }
 GText { x: 80; y: 950; text: "LIVE QML CONTROLS / WHITE + SILVER / CHAMPAGNE TRACES"; font.pixelSize: Theme.typeCaption; font.letterSpacing: 2 }
}
