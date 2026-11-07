import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id: view
    property var s
    Popup {
        id: clientPopup
        objectName: "launcherUpgradePopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(540,parent.width-32); height: Math.min(520,parent.height-32)
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        visible: !view.s.host && !!view.s.launcherUpgrade && !view.s.closing
        property var u: view.s.launcherUpgrade || ({})
        background: ChamferPopup { edgeColor: Theme.brass }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 22; spacing: 14
            GText { Layout.fillWidth: true; text: clientPopup.u.status === "complete" ? "Host launcher downloaded" : "Launcher version mismatch"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(28); wrapMode: Text.WordWrap }
            GText { Layout.fillWidth: true; text: "This Client: " + view.s.version + "    Host: " + (clientPopup.u.version || "Unknown"); color: Theme.brass; font.pixelSize: Theme.typeSmall }
            GText { Layout.fillWidth: true; text: (clientPopup.u.host || "") + "  " + (clientPopup.u.address || ""); wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.typeSmall }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                GText { width: parent.width; wrapMode: Text.WordWrap; text: clientPopup.u.message || ""; font.pixelSize: Theme.typeSmall }
            }
            GText { Layout.fillWidth: true; visible: clientPopup.u.status === "mismatch" && !clientPopup.u.supported; text: clientPopup.u.unavailableReason || ""; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.typeSmall }
            RowLayout {
                visible: clientPopup.u.status === "pin"
                GUField { id: passKey; objectName: "launcherUpgradePassKey"; Layout.fillWidth: true; placeholderText: "Three-digit pass key"; maximumLength: 3; validator: RegularExpressionValidator { regularExpression: /[0-9]{3}/ } onAccepted: if(acceptableInput) { backend.submitHostVersionKey(text); clear(); } }
                GUButton { text: "Verify key"; Layout.preferredWidth: 120; iconOnly: false; enabled: passKey.acceptableInput; onClicked: { backend.submitHostVersionKey(passKey.text); passKey.clear(); } }
            }
            BusyIndicator { Layout.alignment: Qt.AlignHCenter; implicitWidth: 30; implicitHeight: 30; visible: ["requesting","waiting","unlocking","downloading"].includes(clientPopup.u.status); running: visible }
            ProgressBar { Layout.fillWidth: true; visible: clientPopup.u.status === "downloading"; value: clientPopup.u.total > 0 ? clientPopup.u.done/clientPopup.u.total : 0 }
            GUButton { objectName: "requestHostVersionButton"; Layout.fillWidth: true; text: "Request Host's Version"; iconOnly: false; visible: ["mismatch","error"].includes(clientPopup.u.status); enabled: !!clientPopup.u.supported && !view.s.busy; onClicked: backend.requestHostVersion() }
            GUButton { Layout.fillWidth: true; text: "Choose download destination"; iconOnly: false; visible: clientPopup.u.status === "destination"; onClicked: backend.chooseHostVersionDestination() }
            GUButton { Layout.fillWidth: true; text: "Repair Network/Wipe VLA"; iconName: "repair"; iconOnly: false; visible: clientPopup.u.status === "complete"; onClicked: { backend.cancelHostVersionTransfer(); backend.wipeVLA(); } }
            GUButton { Layout.fillWidth: true; text: clientPopup.u.status === "complete" ? "Close message" : "Cancel"; iconOnly: false; onClicked: backend.cancelHostVersionTransfer() }
        }
    }
    Popup {
        id: hostPopup
        objectName: "hostLauncherSharePopup"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(430,parent.width-24); height: Math.min(450,parent.height-32)
        property var request: view.s.launcherShareRequests && view.s.launcherShareRequests.length ? view.s.launcherShareRequests[0] : null
        visible: view.s.host && !!request && !view.s.closing
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        background: ChamferPopup { edgeColor: Theme.brass }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 22; spacing: 12
            GText { Layout.fillWidth: true; text: "Share Host launcher?"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(27); wrapMode: Text.WordWrap }
            GText { Layout.fillWidth: true; text: hostPopup.request ? hostPopup.request.name + "\n" + hostPopup.request.ip : ""; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap }
            GText { Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; text: !hostPopup.request ? "" : hostPopup.request.status === "pending" ? "This Client needs your launcher version. Accept to prepare a clean launcher ZIP. Games and player data are excluded." : hostPopup.request.status === "preparing" ? "Preparing and verifying launcher files..." : hostPopup.request.status === "error" ? hostPopup.request.error : hostPopup.request.status === "sending" ? "Sending the launcher package..." : "Give this pass key to the Client. Click to copy. No files transfer before the Client enters it. The request expires after ten minutes." }
            CopyText { objectName: "hostLauncherShareKey"; Layout.alignment: Qt.AlignHCenter; height: 40; text: hostPopup.request ? hostPopup.request.pin || "" : ""; font.pixelSize: Theme.scaledFont(32); normalColor: Theme.brass; description: "Copy launcher transfer pass key" }
            Item { Layout.fillHeight: true }
            GUButton { Layout.fillWidth: true; text: "Accept request"; iconOnly: false; visible: hostPopup.request && hostPopup.request.status === "pending"; onClicked: backend.decideHostVersionRequest(hostPopup.request.id, true) }
            GUButton { Layout.fillWidth: true; text: "Deny / Cancel"; iconOnly: false; onClicked: backend.decideHostVersionRequest(hostPopup.request.id, false) }
        }
    }
}
