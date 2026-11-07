import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    property string pendingAvatar: ""
    property real cropX: .5
    property real cropY: .5
    IconLabel { x: 24; y: 21; iconName: "user"; text: "Your player profile" }
    Rectangle { x: 28; y: 85; width: 95; height: 95; radius: 4; color: Theme.insetPanel; border.color: Theme.brass; border.width: .6; clip: true
        Image { objectName: "profileAvatar"; anchors.fill: parent; anchors.margins: 1; visible: !!view.s.avatar; source: view.s.avatar ? "file:///" + view.s.avatar.replace(/\\/g, "/") : ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
        MouseArea { id: avatarMouse; enabled: !view.s.tutorial; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onEntered: HoverHelp.begin(avatarMouse, "Choose a profile picture."); onExited: HoverHelp.end(avatarMouse); onClicked: { let p = backend.chooseFile("art"); if (p) { view.pendingAvatar = p; cropZoom.value = 1; view.cropX = .5; view.cropY = .5; cropPopup.open(); } } }
        Text { anchors.centerIn: parent; visible: !view.s.avatar; text: view.s.playerName.substring(0,2).toUpperCase(); font.family: Theme.display; font.pixelSize: Theme.scaledFont(26); color: Theme.brass }
    }
    GText { x: 155; y: 85; text: "Player name"; font.pixelSize: Theme.typeSmall }
    GUField { id: name; objectName: "profileNameField"; enabled: !view.s.tutorial || view.s.tutorialStage === "clientProfile"; x: 155; y: 108; width: parent.width - 424; text: view.s.playerName }
    GText { x: 28; y: 240; text: "THIS PC"; color: Theme.brass; font.family: Theme.display; font.pixelSize: Theme.typeSmall }
    GText { x: 28; y: 278; text: view.s.pcName; font.pixelSize: Theme.scaledFont(18) }
    GText { x: 28; y: 355; text: "Current activity"; color: Theme.muted; font.pixelSize: Theme.typeSmall }
    Text { x: 28; y: 387; text: view.s.connected ? "Connected to your LAN room" : "Not in a room"; color: Theme.green; font.family: Theme.ui; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold }
    GUButton { objectName: "saveProfileAction"; enabled: name.enabled; x: parent.width - 253; y: 108; width: 225; text: "Save profile"; edge: "right"; primary: true; onClicked: backend.saveProfile(name.text) }
    Popup {
        id: cropPopup; objectName: "avatarCropPopup"
        anchors.centerIn: parent; width: 380; height: 475; modal: true; focus: true
        background: ChamferPopup { edgeColor: Theme.brass }
        GText { x: 24; y: 18; text: "Position profile picture"; font.pixelSize: Theme.scaledFont(20); font.weight: Font.DemiBold }
        GText { x: 24; y: 52; text: "Drag to move the crop. Use zoom to frame your picture."; color: Theme.muted; font.pixelSize: Theme.typeSmall }
        Rectangle {
            id: cropFrame; x: 50; y: 83; width: 280; height: 280; color: Theme.dark; border.color: Theme.brass; border.width: 1; clip: true
            Image {
                id: cropImage
                source: view.pendingAvatar ? "file:///" + view.pendingAvatar.replace(/\\/g, "/") : ""
                asynchronous: true; fillMode: Image.Stretch; smooth: true
                readonly property real ratio: sourceSize.width > 0 && sourceSize.height > 0 ? sourceSize.width / sourceSize.height : 1
                width: Math.max(cropFrame.width, cropFrame.height * ratio) * cropZoom.value
                height: Math.max(cropFrame.height, cropFrame.width / ratio) * cropZoom.value
                x: (cropFrame.width-width) * view.cropX
                y: (cropFrame.height-height) * view.cropY
            }
            MouseArea {
                anchors.fill: parent; cursorShape: Qt.SizeAllCursor
                property real lastX: 0; property real lastY: 0
                onPressed: function(mouse) { lastX = mouse.x; lastY = mouse.y; }
                onPositionChanged: function(mouse) {
                    if (!pressed) return;
                    if (cropImage.width > cropFrame.width) view.cropX = Math.max(0, Math.min(1, view.cropX - (mouse.x-lastX)/(cropImage.width-cropFrame.width)));
                    if (cropImage.height > cropFrame.height) view.cropY = Math.max(0, Math.min(1, view.cropY - (mouse.y-lastY)/(cropImage.height-cropFrame.height)));
                    lastX = mouse.x; lastY = mouse.y;
                }
            }
        }
        GText { x: 25; y: 378; text: "Zoom"; font.pixelSize: Theme.typeSmall }
        Slider { id: cropZoom; objectName: "avatarCropZoom"; x: 85; y: 369; width: 265; from: 1; to: 3; value: 1 }
        GUButton { x: 24; y: 420; width: 145; height: 36; text: "Cancel"; onClicked: cropPopup.close() }
        GUButton { x: 211; y: 420; width: 145; height: 36; text: "Use picture"; primary: true; enabled: cropImage.status === Image.Ready; onClicked: { backend.setAvatarCrop(view.pendingAvatar, cropZoom.value, view.cropX, view.cropY); cropPopup.close(); } }
    }
}
