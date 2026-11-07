import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Popup {
    id: popup
    objectName: "hostNetworkDiagnosticPopup"
    property var s
    anchors.centerIn: parent
    width: Math.min(440,parent.width-24)
    height: Math.min(620,parent.height-40,Math.max(260,diagnosticRows.implicitHeight+160))
    modal: true; focus: true
    background: ChamferPopup {}
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            GText { Layout.fillWidth: true; text: "Network Diagnostic"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(24) }
            GUButton { Layout.preferredWidth: 32; Layout.preferredHeight: 32; iconOnly: true; text: "Close diagnostic"; iconName: "close"; onClicked: popup.close() }
        }
        GText {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall
            color: popup.s.diag.error ? Theme.red : Theme.brass
            text: popup.s.diag.error || (popup.s.diag.running ? "Checking... " + popup.s.diag.step : "Overall: " + (popup.s.diag.worst || "Not checked"))
        }
        BusyIndicator { Layout.alignment: Qt.AlignHCenter; visible: !!popup.s.diag.running; running: visible; implicitWidth: 30; implicitHeight: 30 }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            Column {
                id: diagnosticRows
                width: parent.width; spacing: 14
                Repeater {
                    model: popup.s.diag.rows || []
                    delegate: Column {
                        required property var modelData
                        width: parent.width; spacing: 4
                        GText { width: parent.width; wrapMode: Text.WordWrap; text: modelData.title + " - " + modelData.status; font.pixelSize: Theme.typeSmall; color: modelData.status === "ok" ? Theme.green : Theme.brass }
                        GText { width: parent.width; wrapMode: Text.WordWrap; text: modelData.detail; color: Theme.muted; font.pixelSize: Theme.typeSmall }
                        GText {
                            objectName: "hostDiagFix_"+modelData.fix
                            visible: !!modelData.fix; text: modelData.fixLabel || "Resolve"; color: Theme.brass; font.pixelSize: Theme.typeSmall; font.underline: true
                            enabled: !popup.s.diag.running && !popup.s.busy
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: backend.runFix(modelData.fix) }
                        }
                    }
                }
            }
        }
        GUButton { Layout.fillWidth: true; height: 40; text: popup.s.diag.running ? "Checking..." : "Check again"; iconName: "refresh"; iconOnly: false; enabled: !popup.s.diag.running; onClicked: backend.runDiagnostics() }
    }
}
