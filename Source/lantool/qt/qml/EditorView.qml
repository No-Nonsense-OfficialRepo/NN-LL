import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    Text { x: 24; y: 21; text: "Edit game"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
    GText { x: 24; y: 83; text: "Game name"; font.pixelSize: Theme.typeSmall }
    GUField { id: name; x: 24; y: 106; width: parent.width - 48; text: view.s.edit.name || "" }
    GText { x: 24; y: 165; text: "Game folder"; font.pixelSize: Theme.typeSmall }
    GUField { id: folder; x: 24; y: 188; width: parent.width - 48; text: view.s.edit.folder || ""; readOnly: true }
    CheckBox { id: exeRequired; objectName: "editorExeRequiredCheck"; x: 24; y: 234; text: "EXE required"; checked: view.s.edit.exeRequired !== false }
    GText { x: 24; y: 280; text: "Launch executable"; font.pixelSize: Theme.typeSmall }
    GUField { id: exe; x: 24; y: 303; width: parent.width - 272; text: view.s.edit.exe || ""; enabled: exeRequired.checked }
    GUButton { x: parent.width - 234; y: 303; width: 210; text: "Choose .exe"; edge: "right"; enabled: exeRequired.checked; onClicked: {let p=backend.chooseFile("exe"); if(p) exe.text=p;} }
    GText { x: 24; y: 362; text: "Launch arguments"; font.pixelSize: Theme.typeSmall }
    GUField { id: args; x: 24; y: 385; width: parent.width - 48; text: view.s.edit.args || ""; enabled: exeRequired.checked }
    GText { x: 24; y: 456; text: "Include in event playlist"; font.pixelSize: Theme.typeSmall }
    GUToggle { id: enabledGame; x: parent.width - 66; y: 454; checked: !!view.s.edit.enabled }
    property string artPath: ""
    Row { x: 24; y: parent.height - 90; spacing: 14
        GUButton { text: "Save game"; edge: "left"; width: 200; primary: true; onClicked: backend.saveGame(folder.text,exe.text,name.text,args.text,enabledGame.checked,view.artPath,exeRequired.checked) }
        GUButton { edge: "center"; text: view.artPath ? "Portrait cover selected" : "Portrait cover (2:3)"; width: 210; onClicked: {let p=backend.chooseFile("art"); if(p) view.artPath=p;} }
        GUButton { text: "Cancel"; edge: "right"; width: 160; onClicked: backend.navigate("catalog") }
    }
}
