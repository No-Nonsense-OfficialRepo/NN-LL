import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Popup {
    id: popup
    objectName: "termsOfServicePopup"
    property bool startupAcknowledgment: false
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(840,parent.width-32)
    height: Math.min(760,parent.height-48)
    modal: true; focus: true; z: 2000
    closePolicy: startupAcknowledgment ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: ChamferPopup { edgeColor: Theme.brass }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 16
        GText { Layout.fillWidth: true; text: "Terms of Service"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(30) }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "termsOfServiceText"
                width: scroll.availableWidth
                text: termsOfService
                textFormat: TextEdit.MarkdownText
                readOnly: true; selectByMouse: true
                wrapMode: TextEdit.Wrap
                font.family: Theme.ui; font.pixelSize: Theme.typeSmall
                color: Theme.paper; selectedTextColor: Theme.dark; selectionColor: Theme.brass
                padding: 12
                background: Rectangle { color: Theme.dark }
                onLinkActivated: link => { if(link === "https://www.gnu.org/licenses/gpl-3.0.html") Qt.openUrlExternally(link); }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 16
            GUButton { Layout.preferredWidth: 150; text: "Exit Quick Start"; iconOnly: false; visible: popup.startupAcknowledgment; onClicked: backend.requestClose() }
            Item { Layout.fillWidth: true }
            GUButton {
                objectName: "acknowledgeTermsButton"
                Layout.preferredWidth: popup.startupAcknowledgment ? 280 : 120
                text: popup.startupAcknowledgment ? "I Acknowledge & Continue" : "Close"
                iconOnly: false; primary: true
                onClicked: { if(popup.startupAcknowledgment) backend.acknowledgeTerms(); popup.close(); }
            }
        }
    }
}
