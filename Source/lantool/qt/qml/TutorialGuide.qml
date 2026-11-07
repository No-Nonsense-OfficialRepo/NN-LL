import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: guide
    property var s
    readonly property bool choosing: s.tutorialStage === "choose"
    readonly property var targets: ({hostOpen:"hostStartAction", hostInvite:"hostRoomCodeCopy",
        hostAdd:"hostAddGameAction", hostExe:"hostSelectExeAction", hostArt:"hostSelectArtAction",
        hostShare:"hostShareGameCheck", hostPlayers:"hostClientsPanel", hostOptions:"hostAppearanceAction",
        clientFind:"findHostAction", clientKey:"joinRoomKeyAction", clientPlay:"gameActionButton",
        clientInstall:"gameActionButton", clientDownload:"nav-downloads", clientSettings:"nav-settings",
        clientPlayerTab:"settingsTab-Player", clientProfile:"saveProfileAction"})
    property real hintX: 16
    property real hintY: Math.max(16, height - hintPanel.height - 16)
    function findTarget(node, name) {
        if (!node || !name) return null;
        if (node.objectName === name && node.visible) return node;
        let items = node.children || [];
        for (let i = 0; i < items.length; ++i) {
            let found = findTarget(items[i], name);
            if (found) return found;
        }
        return null;
    }
    function placeHint() {
        if (!hintPanel.visible) return;
        let target = findTarget(guide.parent ? guide.parent.parent : null, targets[s.tutorialStage]);
        if (!target) { hintX = 16; hintY = Math.max(16, height - hintPanel.height - 16); return; }
        let topLeft = target.mapToItem(guide, 0, 0);
        let bottomRight = target.mapToItem(guide, target.width, target.height);
        let left = Math.min(topLeft.x, bottomRight.x), right = Math.max(topLeft.x, bottomRight.x);
        let top = Math.min(topLeft.y, bottomRight.y), bottom = Math.max(topLeft.y, bottomRight.y);
        let w = hintPanel.width, h = hintPanel.height;
        let gap = 20;
        if (width > w * 2 + 48 && right + gap + w <= width - 12) {
            hintX = right + gap;
            hintY = Math.max(12, Math.min(height - h - 12, top));
        } else if (width > w * 2 + 48 && left - gap - w >= 12) {
            hintX = left - gap - w;
            hintY = Math.max(12, Math.min(height - h - 12, top));
        } else {
            hintX = Math.max(12, Math.min(width - w - 12, left));
            hintY = bottom + gap + h <= height - 12 ? bottom + gap : top - gap - h;
        }
        hintX = Math.max(12, Math.min(width - w - 12, hintX));
        hintY = Math.max(12, Math.min(height - h - 12, hintY));
    }
    Timer { interval: 200; repeat: true; running: !guide.choosing; onTriggered: guide.placeHint() }
    Rectangle { anchors.fill: parent; visible: guide.choosing; color: Theme.dark }
    Panel {
        objectName: "tutorialRoleChooser"
        visible: guide.choosing
        anchors.centerIn: parent
        width: Math.min(680, parent.width - 48)
        height: 250
        GUButton {
            objectName: "tutorialChooserClose"
            anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 14
            width: 38; height: 34; z: 2
            text: "Back"; iconName: "back"; iconOnly: false
            onClicked: backend.backLesson()
        }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 12
            GText { text: "LAN Quick Start"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(30) }
            GText { Layout.fillWidth: true; text: "Choose a role to practice in the real launcher layout."; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                Repeater {
                    model: [{role: "host", title: "Host", detail: "Open a room and invite players."},
                            {role: "client", title: "Client", detail: "Join a room and try Play."}]
                    Panel {
                        required property var modelData
                        Layout.fillWidth: true; Layout.fillHeight: true
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 14
                            GText { Layout.fillWidth: true; text: modelData.detail; wrapMode: Text.WordWrap }
                            GUButton { Layout.fillWidth: true; primary: true; iconOnly: false; text: modelData.title; onClicked: backend.choose(modelData.role) }
                        }
                    }
                }
            }
        }
    }
    Panel {
        id: hintPanel
        objectName: "tutorialHintPanel"
        visible: !guide.choosing && guide.s.tutorialStage !== "clientPassword"
        fill: Theme.dark; stroke: Theme.brass
        x: guide.hintX; y: guide.hintY
        width: Math.min(520, parent.width - 24)
        height: lesson.implicitHeight + 36
        ColumnLayout {
            id: lesson
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 18
            spacing: 10
            GText { text: "QUICK START · PRACTICE"; color: Theme.muted; font.pixelSize: Theme.typeSmall }
            GText { Layout.fillWidth: true; text: guide.s.tutorialTitle; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(21); wrapMode: Text.WordWrap }
            GText {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: guide.s.tutorialError || (guide.s.tutorialLaunching ? "Opening the launcher…" : guide.s.tutorialText)
            }
            CopyText {
                objectName: "tutorialRoomKeyCopy"
                visible: guide.s.tutorialStage === "clientKey"
                Layout.fillWidth: true
                text: guide.s.tutorialRoomKey + "  ·  Click to copy"
                copyValue: guide.s.tutorialRoomKey
                description: "Copy practice room key"
                normalColor: Theme.actionInk
            }
            RowLayout {
                Layout.fillWidth: true
                GUButton { objectName: "tutorialCancelAction"; text: "Back"; iconOnly: false; Layout.preferredWidth: 152; enabled: !guide.s.tutorialLaunching; onClicked: backend.backLesson() }
                GUButton {
                    objectName: "tutorialNextLesson"; text: "Next"; iconOnly: false; primary: true; Layout.fillWidth: true
                    visible: guide.s.tutorialStage !== "done"
                    onClicked: backend.nextLesson()
                }
                GUButton {
                    text: "Take me there"; iconOnly: false; primary: true; Layout.fillWidth: true
                    visible: guide.s.tutorialStage === "done"; enabled: !guide.s.tutorialLaunching
                    onClicked: backend.launch()
                }
            }
        }
    }
}
