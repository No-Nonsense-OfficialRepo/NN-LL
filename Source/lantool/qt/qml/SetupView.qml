import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    Text { x: 28; y: 22; text: "Make yourself at home"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
    GText { x: 28; y: 112; text: "Player name"; font.pixelSize: Theme.typeSmall }
    GUField { id: name; x: 28; y: 135; width: parent.width - 56; text: view.s.playerName }
    GText { x: 28; y: 195; text: "Game directory"; font.pixelSize: Theme.typeSmall }
    GUField { id: directory; x: 28; y: 218; width: parent.width - 272; text: view.s.gameDirectory }
    GUButton { x: parent.width - 228; y: 218; width: 200; text: "Browse folder"; edge: "right"; onClicked: { let path=backend.chooseDirectory(); if(path) directory.text=path; } }
    GText { x: 28; y: 400; text: "Keep VLA installed after closing"; font.pixelSize: Theme.typeSmall }
    GText { x: 28; y: 426; text: "A pre-existing installation is always preserved."; font.pixelSize: Theme.typeCaption; color: Theme.muted }
    GUToggle { id: keep; x: parent.width - 70; y: 398; checked: view.s.keepInstalled }
    Rectangle { x: 28; y: 468; width: parent.width - 56; height: .6; color: Theme.border }
    GText { x: 28; y: 490; text: "Windows may ask you to approve the network driver installation."; color: Theme.brass; font.pixelSize: Theme.typeCaption }
    GUButton { x: 28; y: parent.height - 96; width: 250; text: "Save setup"; edge: "left"; iconName: "setup-complete"; primary: true; onClicked: backend.finishSetup(name.text,directory.text,keep.checked,"") }
}
